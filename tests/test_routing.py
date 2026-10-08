"""Quota-aware routing: agent "auto" goes to the first agent that can start now, and moves on after a quota limit."""

import json
import time
import unittest

from navis import cli, routing, runtime
from test_navis import DONE, NavisTest, edit, step


class Routing(NavisTest):
    def setUp(self):
        super().setUp()
        original = {a: runtime.ADAPTERS[a] for a in ("claude", "codex")}
        real = runtime.fake_cmd
        for a in original:  # both "real" agents are the scripted fake, so routing can be seen without quota
            runtime.ADAPTERS[a] = lambda prompt, mcp, home, io, readonly=False, model="", effort="", _r=real, **_: _r(prompt, mcp, home, io, readonly)
        self.addCleanup(lambda: runtime.ADAPTERS.update(original))
        self.set_config(backoff=600)

    def set_config(self, backoff=0.5, extra=""):
        f = self.tmp / "cfg" / "config.toml"
        f.write_text(f"[limits]\nattempt_timeout = 30\nmax_attempts = 2\nquota_backoff = [{backoff}]\n[slots]\nfake = 2\nclaude = 1\ncodex = 1\n{extra}")
        self.rt = runtime.Runtime(self.store)

    def login(self, *names):
        for n in names:
            home = self.tmp / "home" / "agents" / n
            home.mkdir(parents=True, exist_ok=True)
            (home / routing.LOGIN_FILE[n]).write_text("{}")

    def cool(self, agent, secs=600):
        self.store.x("insert or replace into cooldowns(agent, until, strikes) values (?,?,1)", agent, time.time() + secs)

    def auto(self, spec=None, scope=("src",), **kw):
        tid, dup = runtime.add_task(self.store, "p", "auto", spec or edit("src/x.py") + DONE, list(scope), **kw)
        self.assertIsNone(dup)
        return tid

    def routed(self, tid):
        return [json.loads(e["data"]) for e in self.store.q("select data from events where task = ? and kind = 'routed' order by id", tid)]

    def test_the_first_logged_in_agent_in_the_pool_gets_the_task(self):
        self.login("claude", "codex")
        tid = self.auto()
        self.run_all()
        self.assertEqual((self.task(tid)["status"], self.task(tid)["agent"], self.task(tid)["routing"]), ("COMPLETED", "claude", "auto"))
        self.assertEqual(self.routed(tid), [{"agent": "claude", "skipped": {}}])

    def test_an_agent_that_is_not_logged_in_or_cooling_is_skipped_with_the_reason_recorded(self):
        self.login("codex")
        a = self.auto()
        self.run_all()
        self.assertEqual((self.task(a)["agent"], self.routed(a)[0]["skipped"]), ("codex", {"claude": "not logged in"}))
        self.login("claude")
        self.cool("claude")
        b = self.auto(edit("src/y.py") + DONE, scope=("src/y.py",))
        self.run_all()
        self.assertEqual((self.task(b)["agent"], self.routed(b)[0]["skipped"]), ("codex", {"claude": "cooling down after a quota limit"}))

    def test_a_quota_limit_moves_an_auto_task_to_the_other_agent_instead_of_waiting(self):
        self.login("claude", "codex")
        tid = self.auto(step("rate_limit", attempt=1) + edit("src/x.py") + DONE)
        self.run_all(90)
        self.assertEqual(self.task(tid)["status"], "COMPLETED", self.task(tid)["note"])
        self.assertEqual([r["agent"] for r in self.routed(tid)], ["claude", "codex"])
        self.assertEqual(self.outcomes(tid), ["quota", "done"])
        statuses = [json.loads(e["data"])["status"] for e in self.store.q("select data from events where task = ? and kind = 'status'", tid)]
        self.assertNotIn("WAITING_QUOTA", statuses)
        self.assertEqual(self.task(tid)["attempts"], 0)  # a quota limit is not a failed try

    def test_a_task_with_an_explicit_agent_is_never_moved_and_still_waits_for_its_quota(self):
        self.login("claude", "codex")
        tid, _ = runtime.add_task(self.store, "p", "claude", step("rate_limit", attempt=1) + edit("src/x.py") + DONE, ["src"])
        self.rt.tick()
        for th in self.rt.threads:
            th.join(30)
        self.assertEqual((self.task(tid)["status"], self.task(tid)["agent"]), ("WAITING_QUOTA", "claude"))
        self.assertEqual(self.routed(tid), [])

    def test_when_every_agent_is_unavailable_the_task_stays_queued_and_starts_when_one_returns(self):
        self.login("claude", "codex")
        self.cool("claude")
        self.cool("codex")
        tid = self.auto()
        end = time.time() + 2
        while time.time() < end:
            self.rt.tick()
            time.sleep(0.2)
        self.assertEqual((self.task(tid)["status"], self.task(tid)["agent"]), ("QUEUED", "auto"))
        self.assertEqual(self.store.q("select 1 from attempts where task = ?", tid), [])
        self.store.x("delete from cooldowns where agent = 'codex'")
        self.run_all()
        self.assertEqual((self.task(tid)["status"], self.task(tid)["agent"]), ("COMPLETED", "codex"))

    def test_a_busy_agent_is_skipped_so_two_auto_tasks_use_both(self):
        self.login("claude", "codex")
        a = self.auto(step("sleep", s=2) + edit("src/a.py") + DONE, scope=("src/a.py",))
        b = self.auto(edit("src/b.py") + DONE, scope=("src/b.py",))
        self.run_all()
        self.assertEqual(sorted([self.task(a)["agent"], self.task(b)["agent"]]), ["claude", "codex"])
        self.assertEqual(self.routed(b)[0]["skipped"], {"claude": "slots full"})

    def test_a_review_prefers_an_agent_other_than_the_implementer(self):
        self.login("claude", "codex")
        tid, _ = runtime.add_task(self.store, "p", "claude", edit("src/x.py") + DONE, ["src"])
        self.run_all()
        rid, _ = runtime.request_review(self.store, tid, "auto", DONE)
        self.run_all()
        self.assertEqual(self.task(rid)["agent"], "codex")  # claude wrote it; the pool's first choice would have been claude
        self.assertEqual(runtime.reviews(self.store, tid)[0]["reviewer"], "codex")

    def test_the_pool_order_is_a_preference_the_user_can_change(self):
        self.login("claude", "codex")
        self.set_config(extra='[routing]\npool = ["codex", "claude"]\n')
        tid = self.auto()
        self.run_all()
        self.assertEqual(self.task(tid)["agent"], "codex")

    def test_model_and_effort_cannot_be_set_on_an_unchosen_agent_and_unknown_agents_are_refused(self):
        with self.assertRaisesRegex(ValueError, "belong to a specific agent"):
            runtime.add_task(self.store, "p", "auto", DONE, ["src"], effort="low")
        with self.assertRaisesRegex(ValueError, "unknown agent"):
            runtime.add_task(self.store, "p", "gpt", DONE, ["src"])

    def test_local_coding_is_never_picked_automatically(self):
        self.set_config(extra='[local]\ncoding = true\n[routing]\npool = ["local", "claude"]\n')
        self.assertEqual(routing.pool(runtime.load_config()), ["claude"])

    def test_the_cli_shows_and_sets_the_first_choice(self):
        import contextlib
        import io
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli.main(["routing"])
            cli.main(["routing", "--first", "codex"])
        self.assertEqual(out.getvalue().splitlines(), ["auto tries, in order: claude -> codex", "auto tries, in order: codex -> claude"])


if __name__ == "__main__":
    unittest.main()
