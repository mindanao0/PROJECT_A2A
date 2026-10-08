"""Phase 3: usage accounting, fair scheduling between projects, retention."""

import json
import subprocess
import time
import unittest

from navis import bridge, retention, runtime, usage
from test_navis import DONE, NavisTest, edit

# Shapes copied from real runs of codex-cli 0.160.1 and claude 2.1.291.
CODEX = "\n".join([
    "WARNING: something that is not json",
    '{"type":"thread.started","thread_id":"t"}',
    '{"type":"turn.completed","usage":{"input_tokens":59373,"cached_input_tokens":51584,"cache_write_input_tokens":0,"output_tokens":198,"reasoning_output_tokens":2}}',
    '{"type":"turn.completed","usage":{"input_tokens":100,"cached_input_tokens":50,"output_tokens":10,"reasoning_output_tokens":0}}'])
CLAUDE = "\n".join([
    '{"type":"system","subtype":"init"}',
    '{"type":"result","subtype":"success","num_turns":3,"total_cost_usd":0.0699,"usage":{"input_tokens":2,'
    '"cache_creation_input_tokens":17042,"cache_read_input_tokens":8364,"output_tokens":4}}'])


class Parse(unittest.TestCase):
    def test_codex_sums_turns_and_keeps_cached_inside_input(self):
        self.assertEqual(usage.parse("codex", CODEX),
                         {"input": 59473, "cached": 51634, "output": 210, "turns": 2, "cost_usd": None})

    def test_claude_reports_total_input_cache_reads_and_cost(self):
        self.assertEqual(usage.parse("claude", CLAUDE),
                         {"input": 25408, "cached": 8364, "output": 4, "turns": 3, "cost_usd": 0.0699})

    def test_nothing_exposed_is_none_not_zero(self):
        self.assertIsNone(usage.parse("fake", CODEX))
        self.assertIsNone(usage.parse("codex", "plain text\n"))
        self.assertIsNone(usage.parse("claude", '{"type":"system"}\n'))


class Limits(unittest.TestCase):
    """The 5h/week windows shown in the Agent fleet."""
    def test_codex_reads_its_last_recorded_turn(self):
        import tempfile
        from pathlib import Path
        home = Path(tempfile.mkdtemp())
        day = home / "sessions" / "2026" / "10" / "07"
        day.mkdir(parents=True)
        rl = {"primary": {"used_percent": 14.0, "window_minutes": 300, "resets_at": 1791362581},
              "secondary": {"used_percent": 2.0, "window_minutes": 10080, "resets_at": 1791949381}}
        line = lambda used: json.dumps({"timestamp": "2026-10-07T04:53:16.974Z", "type": "event_msg",
                                        "payload": {"type": "token_count", "rate_limits": rl | {"primary": rl["primary"] | {"used_percent": used}}}})
        (day / "rollout-2026-10-07T09-00-00-a.jsonl").write_text(line(90.0) + "\n")
        (day / "rollout-2026-10-07T11-00-00-b.jsonl").write_text(line(10.0) + "\n" + line(14.0) + "\n" + '{"type":"other"}\n')
        got = usage.codex_limits(home)
        self.assertEqual(got["windows"], [{"window": "5h", "used": 14.0, "resets_at": 1791362581},
                                          {"window": "week", "used": 2.0, "resets_at": 1791949381}])
        self.assertAlmostEqual(got["as_of"], 1791348796.974, places=2)
        self.assertIsNone(usage.codex_limits(home / "nothing"))

    def test_claude_asks_only_with_a_valid_token_and_otherwise_shows_the_last_answer(self):
        import io, tempfile
        from pathlib import Path
        from unittest import mock
        home, cache = Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp()) / "c.json"
        creds = lambda expires: (home / ".credentials.json").write_text(json.dumps(
            {"claudeAiOauth": {"accessToken": "tok", "expiresAt": expires * 1000}}))
        answer = {"five_hour": {"utilization": 4.0, "resets_at": "2026-10-07T14:19:59+00:00"},
                  "seven_day": {"utilization": 88.0, "resets_at": "2026-10-08T00:59:59+00:00"}, "seven_day_opus": None}
        creds(time.time() + 3600)
        with mock.patch("urllib.request.urlopen", return_value=io.BytesIO(json.dumps(answer).encode())) as call:
            got = usage.claude_limits(home, cache)
        req = call.call_args[0][0]
        self.assertEqual((req.full_url, req.get_header("Authorization")), (usage.CLAUDE_USAGE, "Bearer tok"))
        self.assertEqual([(w["window"], w["used"]) for w in got["windows"]], [("5h", 4.0), ("week", 88.0)])
        creds(time.time() - 60)  # expired: no request, the saved answer
        with mock.patch("urllib.request.urlopen", side_effect=AssertionError("must not call")):
            self.assertEqual(usage.claude_limits(home, cache), got)
        self.assertIsNone(usage.claude_limits(home / "none", cache.with_name("none.json")))


class Accounting(NavisTest):
    def test_attempts_record_context_bytes_and_the_report_sums_exposed_usage(self):
        tid = self.add(edit("src/x.py") + DONE)
        self.run_all()
        row = self.store.one("select * from attempts where task = ?", tid)
        prompt = (self.tmp / "home" / "attempts" / f"{tid}-1" / "prompt.txt").read_text()
        self.assertEqual((row["prompt_bytes"], row["usage"]), (len(prompt.encode()), None))  # fake exposes nothing
        self.store.x("update attempts set usage = ? where id = ?", json.dumps(
            {"input": 1000, "cached": 400, "output": 50, "turns": 2, "cost_usd": 0.25}), row["id"])
        rep = usage.report(self.store, 0)
        r = rep[("fake", "implement")]
        self.assertEqual((r["attempts"], r["outcomes"], r["input"], r["cached"], r["output"], r["with_usage"]),
                         (1, {"done": 1}, 1000, 400, 50, 1))
        self.assertAlmostEqual(r["cost_usd"], 0.25)
        self.assertGreater(r["prompt_bytes"], 0)
        self.assertEqual(usage.report(self.store, time.time() + 10), {})  # outside the window

    def test_reviews_are_reported_separately_from_implementation(self):
        tid = self.add(edit("src/x.py") + DONE)
        self.run_all()
        runtime.request_review(self.store, tid, "fake", DONE)
        self.run_all()
        self.assertEqual(sorted(k[1] for k in usage.report(self.store, 0)), ["implement", "review"])


class Fairness(NavisTest):
    def test_a_quiet_project_goes_before_a_busy_one_even_with_a_higher_task_id(self):
        other = self.tmp / "other"
        (other / "src").mkdir(parents=True)
        (other / "src/a.py").write_text("a = 1\n")
        for cmd in (["init", "-q"], ["add", "-A"], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "i"]):
            subprocess.run(["git", "-C", str(other), *cmd], check=True, capture_output=True)
        (self.tmp / "cfg" / "projects" / "q.toml").write_text(f'path = "{other}"\n[checks]\nok = "true"\n')
        (self.tmp / "cfg" / "config.toml").write_text("[limits]\nattempt_timeout = 30\nmax_attempts = 2\n[slots]\nfake = 1\n")
        self.rt = runtime.Runtime(self.store)
        p1, _ = runtime.add_task(self.store, "p", "fake", edit("src/one.py") + DONE, ["src/one.py"])
        p2, _ = runtime.add_task(self.store, "p", "fake", edit("src/two.py") + DONE, ["src/two.py"])
        q1, _ = runtime.add_task(self.store, "q", "fake", edit("src/q.py") + DONE, ["src"])
        self.run_all(120)
        order = [r["task"] for r in self.store.q("select task from attempts order by started")]
        self.assertEqual(order, [p1, q1, p2])  # one slot: p1 ran, so q1 (no recent use) jumped ahead of p2

    def test_equal_projects_keep_task_id_order(self):
        (self.tmp / "cfg" / "config.toml").write_text("[limits]\nattempt_timeout = 30\nmax_attempts = 2\n[slots]\nfake = 1\n")
        self.rt = runtime.Runtime(self.store)
        ids = [runtime.add_task(self.store, "p", "fake", edit(f"src/f{i}.py") + DONE, [f"src/f{i}.py"])[0] for i in range(3)]
        self.run_all(120)
        self.assertEqual([r["task"] for r in self.store.q("select task from attempts order by started")], ids)


class Retention(NavisTest):
    def test_gc_removes_old_attempt_dirs_of_finished_tasks_only(self):
        old, recent = self.add(edit("src/a.py") + DONE, scope=["src/a.py"]), self.add(edit("src/b.py") + DONE, scope=["src/b.py"])
        self.run_all()
        running = self.add(edit("src/c.py") + DONE, scope=["src/c.py"])
        self.store.x("update attempts set ended = ? where task = ?", time.time() - 40 * 86400, old)
        self.store.x("insert into attempts(id, task, n, unit, base, status, started) values (?,?,?,?,?,'running',?)",
                     f"{running}-1", running, 1, "u", "x", time.time() - 90 * 86400)
        self.store.x("update tasks set status = 'RUNNING' where id = ?", running)
        dirs = {n: self.tmp / "home" / "attempts" / f"{n}-1" for n in (old, recent, running)}
        dirs[running].mkdir(parents=True)
        dry = retention.gc(self.store, 30, dry_run=True)
        self.assertEqual((dry["attempt_dirs"], dirs[old].exists()), (1, True))  # a dry run deletes nothing
        done = retention.gc(self.store, 30)
        self.assertEqual(done["attempt_dirs"], 1)
        self.assertGreater(done["bytes"], 0)
        self.assertEqual([d.exists() for d in dirs.values()], [False, True, True])
        self.assertEqual(self.task(old)["status"], "COMPLETED")
        self.assertTrue(self.git("rev-parse", f"refs/navis/attempts/{old}-1").strip())  # result commits stay reachable
        self.assertTrue(self.store.one("select 1 from events where task = ? and kind = 'check'", old))  # evidence rows stay


class Caches(unittest.TestCase):
    def test_the_diff_cache_is_bounded(self):
        b = bridge.Bridge.__new__(bridge.Bridge)
        b.diffs = {i: ("x", []) for i in range(bridge.MAX_DIFFS)}
        t = {"project": "p", "base": "a", "head": "b", "scope": "[]"}
        proj = {"path": "/nonexistent", "protected": []}
        try:
            b.diff(t, proj)
        except Exception:
            pass  # the git call may fail; the cache must already have made room
        self.assertLessEqual(len(b.diffs), bridge.MAX_DIFFS)
        self.assertNotIn(0, b.diffs)  # the oldest entry went first


if __name__ == "__main__":
    unittest.main()
