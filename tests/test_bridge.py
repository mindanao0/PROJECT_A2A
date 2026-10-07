"""The GUI drives the real runtime through navis.bridge (fake-agent only; no quota)."""

import http.client
import json
import threading
import time
import unittest

from navis import runtime
from navis.bridge import Bridge
from navis.core import ControlError
from navis.server import ControlServer
from test_navis import DONE, NavisTest, edit, step


class BridgeTest(NavisTest):
    def setUp(self):
        super().setUp()
        self.b = Bridge()

    def tearDown(self):
        self.b.close()
        super().tearDown()

    def pump(self, cond, timeout=30):
        end = time.time() + timeout
        while time.time() < end:
            self.b.tick()
            snap = self.b.snapshot()
            if cond(snap):
                return snap
            time.sleep(0.1)
        self.fail(f"condition not reached: {[(t['id'], t['state']) for t in self.b.snapshot()['tasks']]}")

    def login(self, name):
        home = runtime.data_dir() / "agents" / name
        home.mkdir(parents=True, exist_ok=True)
        (home / {"claude": ".credentials.json", "codex": "auth.json"}[name]).write_text("{}")

    def create(self, spec, **kw):
        r = self.b.command({"action": "create_task", "project_id": "p", "title": "t", "spec": spec,
                            "scope": "src/", "agent": "fake", **kw})
        return r["task_id"]

    def task(self, snap, tid):
        return next(t for t in snap["tasks"] if t["id"] == tid)

    def cmd(self, tid, action, **extra):
        t = self.task(self.b.snapshot(), tid)
        return self.b.command({"action": action, "task_id": tid, "attempt_id": t["attempt_id"], **extra})


class Snapshot(BridgeTest):
    def test_completed_task_poll_is_light_and_detail_has_the_evidence(self):
        tid = self.create(edit("src/new.py", "print(1)\n") + DONE)
        snap = self.pump(lambda s: self.task(s, tid)["state"] == "COMPLETED")
        t = self.task(snap, tid)
        self.assertEqual((snap["mode"], [p["id"] for p in snap["projects"]]), ("real", ["p"]))
        self.assertEqual({a["kind"] for a in t["artifacts"]}, {"verification", "diff", "agent_log", "prompt"})
        self.assertFalse(any("content" in a for a in t["artifacts"]), "the poll must not carry artifact bodies")
        self.assertFalse(any("output" in e for e in snap["events"]))
        d = self.b.task_detail(tid)
        kinds = {a["kind"]: a for a in d["task"]["artifacts"]}
        self.assertIn("+print(1)", kinds["diff"]["content"])
        self.assertEqual(kinds["diff"]["files"], [{"path": "src/new.py", "out_of_scope": False, "protected": False}])
        self.assertEqual(kinds["diff"]["hash"], t["head"])
        self.assertIn("report_result", kinds["agent_log"]["content"])
        self.assertIn(f"Navis task {tid}, attempt 1", kinds["prompt"]["content"])
        self.assertEqual(t["result_ref"], f"refs/navis/attempts/{tid}-1")
        self.assertEqual(snap["resources"]["slots"][0], {"backend": "fake", "used": 0, "limit": 2})
        types = [e["type"] for e in snap["events"]]
        self.assertTrue({"STATE", "ATTEMPT", "TOOL", "CHECK", "OUTCOME"} <= set(types), types)
        self.assertTrue(all(e["task_id"] == tid for e in d["events"]))
        self.assertTrue(any("output" in e for e in d["events"] if e["type"] == "CHECK"))
        self.assertGreaterEqual(t["updated_at"], max(e["time"] for e in d["events"]))
        again = self.b.snapshot(snap["cursor"])
        self.assertEqual((again["events"], again["cursor"]), ([], snap["cursor"]))
        with self.assertRaises(ControlError):
            self.b.task_detail("999")

    def test_diff_flags_out_of_scope_and_protected_files(self):
        tid = self.create(edit("docs/b.md") + edit("tests/t.sh") + edit("src/ok.py") + DONE)
        self.pump(lambda s: self.task(s, tid)["state"] == "REVIEW")
        diff = next(a for a in self.b.task_detail(tid)["task"]["artifacts"] if a["kind"] == "diff")
        flags = {f["path"]: (f["out_of_scope"], f["protected"]) for f in diff["files"]}
        self.assertEqual(flags, {"docs/b.md": (True, False), "tests/t.sh": (True, True), "src/ok.py": (False, False)})

    def test_queue_reasons_explain_the_wait(self):
        hold = self.create(step("hang"))
        self.pump(lambda s: self.task(s, hold)["state"] == "RUNNING")
        overlap = self.create(DONE, scope="src/sub")
        other = self.create(DONE + "# o\n", scope="docs")
        self.b.command({"action": "pause"})
        snap = self.b.snapshot()
        codes = lambda tid: [r["code"] for r in self.task(snap, tid)["queue_reasons"]]
        self.assertEqual(codes(overlap), ["paused", "scope"])
        self.assertEqual(self.task(snap, overlap)["queue_reasons"][1]["task_id"], hold)
        self.assertEqual(codes(other), ["paused"])
        self.b.command({"action": "resume"})
        self.assertEqual([r["code"] for r in self.task(self.b.snapshot(), other)["queue_reasons"]], ["ready"])
        self.cmd(hold, "kill")

    def test_continue_from_a_completed_task_starts_at_its_result(self):
        first = self.create(edit("src/one.py") + DONE)
        snap = self.pump(lambda s: self.task(s, first)["state"] == "COMPLETED")
        t = self.task(snap, first)
        base = {"action": "create_task", "project_id": "p", "title": "review", "spec": "review it", "scope": "src",
                "agent": "fake", "source_task_id": first}
        with self.assertRaises(ControlError):
            self.b.command({**base, "source_attempt_id": "stale"})
        second = self.b.command({**base, "source_attempt_id": t["attempt_id"]})["task_id"]
        snap = self.pump(lambda s: self.task(s, second)["state"] in ("COMPLETED", "REVIEW", "FAILED"))
        self.assertEqual(self.task(snap, second)["source"]["task_id"], first)
        self.assertEqual(self.shown(f"{second}-1", "src/one.py"), "x\n")  # sees the first task's file
        with self.assertRaises(ControlError):  # no such task
            self.b.command({**base, "source_task_id": "999", "source_attempt_id": "x", "spec": "other"})
        running = self.create(step("hang"), scope="docs")
        self.pump(lambda s: self.task(s, running)["state"] == "RUNNING")
        with self.assertRaises(ControlError):  # not completed
            self.b.command({**base, "source_task_id": running, "source_attempt_id": self.task(self.b.snapshot(), running)["attempt_id"], "spec": "third"})
        self.cmd(running, "kill")

    def test_providers_report_login_state_and_handoff_capability(self):
        snap = self.b.snapshot()
        by = {p["id"]: p for p in snap["providers"]}
        self.assertEqual((by["fake"]["status"], by["fake"]["slot_limit"]), ("Ready", 2))
        self.assertEqual((by["codex"]["status"], by["codex"]["reason"]), ("Unavailable", "Not logged in"))
        self.assertEqual(snap["capabilities"]["handoff"], {"claude_review": False, "codex_continue": False})
        self.assertFalse(snap["capabilities"]["controls"]["graceful_stop"])
        self.login("claude")
        snap = self.b.snapshot()
        self.assertTrue(snap["capabilities"]["handoff"]["claude_review"])
        self.assertEqual({p["id"]: p["status"] for p in snap["providers"]}["claude"], "Ready")

    def test_duplicate_and_bad_input(self):
        a = self.create(DONE)
        r = self.b.command({"action": "create_task", "project_id": "p", "title": "x", "spec": DONE,
                            "scope": "src", "agent": "fake"})
        self.assertEqual(r, {"task_id": a, "duplicate": True})
        for bad in ({"project_id": "nope"}, {"base": "--output=/x"}, {"agent": "gpt"}, {"scope": "../etc"}):
            with self.assertRaises(ControlError, msg=bad):
                self.create(DONE + "# other\n", **bad)
        with self.assertRaises(ControlError):
            self.b.command({"action": "create_project", "name": "x"})


class Controls(BridgeTest):
    def test_stop_is_bound_to_the_observed_attempt(self):
        tid = self.create(step("hang"))
        self.pump(lambda s: self.task(s, tid)["attempt_id"] is not None and self.task(s, tid)["state"] == "RUNNING")
        with self.assertRaises(ControlError):
            self.b.command({"action": "stop", "task_id": tid, "attempt_id": "0-0"})
        self.cmd(tid, "kill")
        snap = self.pump(lambda s: self.task(s, tid)["state"] == "CANCELLED")
        self.assertEqual(self.task(snap, tid)["attempts"][0]["state"], "cancelled")
        with self.assertRaises(ControlError):
            self.cmd(tid, "kill")  # already inactive
        self.cmd(tid, "retry")
        self.assertEqual(self.task(self.b.snapshot(), tid)["state"], "QUEUED")
        self.cmd(tid, "stop")

    def test_pause_holds_queued_tasks_until_resume(self):
        self.b.command({"action": "pause"})
        tid = self.create(DONE)
        for _ in range(5):
            self.b.tick()
            time.sleep(0.1)
        snap = self.b.snapshot()
        self.assertTrue(snap["paused"])
        self.assertEqual(self.task(snap, tid)["state"], "QUEUED")
        self.b.command({"action": "resume"})
        self.pump(lambda s: self.task(s, tid)["state"] == "COMPLETED")

    def test_review_approval_is_bound_to_the_observed_attempt(self):
        tid = self.create(edit("docs/b.md") + DONE)
        snap = self.pump(lambda s: self.task(s, tid)["state"] == "REVIEW")
        self.assertIsNone(self.task(snap, tid)["pending"])  # the UI shows the diff instead of a question
        with self.assertRaises(ControlError):
            self.b.command({"action": "approve", "task_id": tid, "attempt_id": "0-0"})
        self.cmd(tid, "approve")
        self.assertEqual(self.task(self.b.snapshot(), tid)["state"], "COMPLETED")

    def test_answer_and_instruction_reach_the_next_attempt(self):
        spec = (step("mcp", tool="ask_user", args={"question": "which?"}, attempt=1)
                + step("prompt", path="src/prompt.txt", attempt=2)
                + step("mcp", tool="report_result", args={"status": "done", "summary": "ok"}, attempt=2))
        tid = self.create(spec)
        snap = self.pump(lambda s: self.task(s, tid)["state"] == "WAITING_INPUT")
        self.cmd(tid, "instruction", text="use blue")
        self.cmd(tid, "answer", text="blue", pending_id=self.task(snap, tid)["pending"]["id"])
        snap = self.pump(lambda s: self.task(s, tid)["state"] == "COMPLETED")
        self.assertEqual([i["text"] for i in self.task(snap, tid)["instructions"]], ["use blue"])
        text = self.shown(f"{tid}-2", "src/prompt.txt")
        self.assertIn("User instruction: use blue", text)
        self.assertIn("A: blue", text)


class Runtime(BridgeTest):
    def test_hand_off_to_claude_needs_login_and_starts_from_the_result(self):
        first = self.create(edit("src/one.py") + DONE)
        self.pump(lambda s: self.task(s, first)["state"] == "COMPLETED")
        with self.assertRaises(ControlError):
            self.cmd(first, "review_with_claude")  # not logged in
        self.login("claude")
        new = self.cmd(first, "review_with_claude")["task_id"]
        t = self.task(self.b.snapshot(), new)
        self.assertEqual((t["backend"], t["state"], t["source"]["task_id"]), ("claude", "QUEUED", first))
        self.assertIn("Review", t["title"])
        base = self.store.one("select base from tasks where id = ?", int(new))["base"]
        self.assertEqual(base, self.task(self.b.snapshot(), first)["head"])
        self.cmd(new, "stop")

    def test_settings_validate_apply_and_persist(self):
        items = {i["key"]: i for i in self.b.snapshot()["settings"]["items"]}
        self.assertEqual(items["slots.fake"]["value"], 2)
        for bad in ({"slots.fake": "0"}, {"slots.fake": "x"}, {"slots.checks": "3"}, {"limits.attempt_timeout": "5"}):
            with self.assertRaises(ControlError, msg=bad):
                self.b.command({"action": "update_settings", "values": bad})
        self.b.command({"action": "update_settings", "values": {"slots.fake": "3", "limits.attempt_timeout": "120"}})
        self.assertEqual(self.b.rt.cfg["slots"]["fake"], 3)
        self.assertEqual(runtime.load_config()["limits"]["attempt_timeout"], 120)
        self.assertEqual(runtime.load_config()["slots"]["fake"], 3)

    def test_create_project_validates_the_repository(self):
        self.git("config", "user.name", "t")
        for bad in ({"name": "bad name", "path": str(self.proj)}, {"name": "x", "path": str(self.proj / "src")},
                    {"name": "x", "path": "/nonexistent"}, {"name": "p", "path": str(self.proj)}):
            with self.assertRaises(ControlError, msg=bad):
                self.b.command({"action": "create_project", **bad})
        self.assertEqual(self.b.command({"action": "create_project", "name": "second", "path": str(self.proj)}), {"id": "second"})
        self.assertEqual({p["id"] for p in self.b.snapshot()["projects"]}, {"p", "second"})

    def test_running_attempt_reports_measured_memory(self):
        tid = self.create(step("hang"))
        snap = self.pump(lambda s: self.task(s, tid)["state"] == "RUNNING")
        mem = self.pump(lambda s: self.task(s, tid)["attempts"][0]["memory_bytes"] is not None)
        self.assertGreater(self.task(mem, tid)["attempts"][0]["memory_bytes"], 0)
        self.cmd(tid, "kill")
        self.pump(lambda s: self.task(s, tid)["state"] == "CANCELLED")
        self.assertIsNone(self.task(self.b.snapshot(), tid)["attempts"][0]["memory_bytes"])

    def test_integrate_then_fast_forward_from_the_gui(self):
        tid = self.create(edit("src/x.py") + DONE)
        self.pump(lambda s: self.task(s, tid)["state"] == "COMPLETED")
        self.assertEqual(self.b.snapshot()["integration"], [])
        self.cmd(tid, "integrate")
        snap = self.pump(lambda s: any(i["can_promote"] for i in s["integration"]))
        (i,) = snap["integration"]
        self.assertEqual((i["project_id"], i["tasks"], i["busy"]), ("p", [int(tid)], None))
        self.assertIn("Integrated into the integration branch", " ".join(e["message"] for e in snap["events"]))
        before = self.git("rev-parse", "HEAD").strip()
        with self.assertRaisesRegex(ControlError, "changed"):
            self.b.command({"action": "promote_integration", "project_id": "p", "commit": before})
        self.b.command({"action": "promote_integration", "project_id": "p", "commit": i["commit"]})
        self.assertEqual(self.git("rev-parse", "HEAD").strip(), i["commit"])
        self.assertEqual(self.b.snapshot()["integration"], [])
        with self.assertRaisesRegex(ControlError, "Unknown project"):
            self.b.command({"action": "promote_integration", "project_id": "nope"})

    def test_review_verdict_shows_on_the_task_and_the_gate_blocks_integration(self):
        cfg = self.tmp / "cfg" / "projects" / "p.toml"
        cfg.write_text(cfg.read_text().replace("protected", "require_review = true\nprotected", 1))
        tid = self.create(edit("src/x.py") + DONE)
        self.pump(lambda s: self.task(s, tid)["state"] == "COMPLETED")
        with self.assertRaisesRegex(ControlError, "requires an approving review"):
            self.cmd(tid, "integrate")
        rid, _ = runtime.request_review(self.store, int(tid), "fake", DONE)
        snap = self.pump(lambda s: self.task(s, str(rid))["state"] == "COMPLETED")
        (r,) = self.task(snap, tid)["reviews"]
        self.assertEqual((r["verdict"], r["stale"], r["review_task_id"]), ("approve", False, str(rid)))
        self.assertEqual((self.task(snap, str(rid))["kind"], self.task(snap, tid)["kind"]), ("review", "task"))
        self.assertIn("Review of task", " ".join(e["message"] for e in snap["events"]))
        self.cmd(tid, "integrate")
        self.pump(lambda s: any(i["can_promote"] for i in s["integration"]))

    def test_dependency_reason_and_bounded_revision_from_the_gui(self):
        a = self.create(edit("src/a/x.py") + DONE, scope="src/a/")
        b = self.create(edit("src/b/y.py") + DONE, scope="src/b/", after_task_id=a)
        reasons = self.task(self.b.snapshot(), b)["queue_reasons"]
        self.assertIn(("dependency", a), [(r["code"], r.get("task_id")) for r in reasons])
        with self.assertRaisesRegex(ControlError, "Invalid dependency"):
            self.create(DONE, after_task_id="x")
        snap = self.pump(lambda s: self.task(s, a)["state"] == "COMPLETED" and self.task(s, b)["state"] == "COMPLETED")
        self.assertEqual(self.task(snap, b)["after"], a)
        with self.assertRaisesRegex(ControlError, "does not ask for changes"):
            self.cmd(a, "revise")
        rid, _ = runtime.request_review(self.store, int(a), "fake", step("mcp", tool="report_result",
                                        args={"status": "failed", "summary": "src/a/x.py:1 wrong"}))
        snap = self.pump(lambda s: self.task(s, str(rid))["state"] == "COMPLETED")
        self.assertEqual(self.task(snap, a)["reviews"][0]["verdict"], "changes")
        new = self.cmd(a, "revise")
        self.assertFalse(new["duplicate"])
        snap = self.pump(lambda s: self.task(s, new["task_id"])["state"] == "COMPLETED")
        self.assertEqual(self.task(snap, new["task_id"])["round"], 1)
        self.assertTrue(self.cmd(a, "revise")["duplicate"])

    def test_integration_review_and_discard_commands(self):
        tid = self.create(edit("src/x.py") + DONE)
        self.pump(lambda s: self.task(s, tid)["state"] == "COMPLETED")
        with self.assertRaisesRegex(ControlError, "nothing in the integration branch"):
            self.b.command({"action": "review_integration", "project_id": "p", "agent": "fake"})
        self.cmd(tid, "integrate")
        snap = self.pump(lambda s: any(i["can_promote"] for i in s["integration"]))
        (i,) = snap["integration"]
        self.assertFalse(i["review_needed"])
        with self.assertRaisesRegex(ControlError, "changed"):
            self.b.command({"action": "discard_integration", "project_id": "p", "commit": "0" * 40})
        self.b.command({"action": "discard_integration", "project_id": "p", "commit": i["commit"]})
        self.assertEqual(self.b.snapshot()["integration"], [])
        self.assertIn("Integration branch discarded", " ".join(e["message"] for e in self.b.snapshot()["events"]))
        with self.assertRaisesRegex(ControlError, "Unknown project"):
            self.b.command({"action": "discard_integration", "project_id": "nope"})

    def test_verify_integration_runs_every_check_from_the_gui(self):
        self.project({"a": "test -f src/a/a.py", "b": "test -f src/b/b.py"})
        a, _ = runtime.add_task(self.store, "p", "fake", edit("src/a/a.py") + DONE, ["src/a"], checks=["a"])
        b, _ = runtime.add_task(self.store, "p", "fake", edit("src/b/b.py") + DONE, ["src/b"], checks=["b"])
        self.pump(lambda s: self.task(s, str(a))["state"] == "COMPLETED" and self.task(s, str(b))["state"] == "COMPLETED")
        self.cmd(str(a), "integrate")
        self.pump(lambda s: any(i["tasks"] == [a] and not i["busy"] for i in s["integration"]))
        self.cmd(str(b), "integrate")
        snap = self.pump(lambda s: any(i["tasks"] == [a, b] and not i["busy"] for i in s["integration"]))
        (i,) = snap["integration"]
        self.assertEqual((i["verify_needed"], i["can_promote"]), (True, False))
        self.b.command({"action": "verify_integration", "project_id": "p"})
        snap = self.pump(lambda s: any(x["can_promote"] for x in s["integration"]))
        self.assertFalse(snap["integration"][0]["verify_needed"])
        with self.assertRaisesRegex(ControlError, "Unknown project"):
            self.b.command({"action": "verify_integration", "project_id": "nope"})

    def test_agent_options_are_listed_validated_saved_and_used_by_new_tasks(self):
        ao = self.b.snapshot()["agent_options"]
        self.assertEqual(sorted(ao), ["claude", "codex"])
        self.assertEqual((ao["claude"]["model"], ao["claude"]["effort"]), ("", ""))
        self.assertEqual(ao["claude"]["efforts"], ["low", "medium", "high", "xhigh", "max"])
        self.assertIn("haiku", ao["claude"]["models"])
        with self.assertRaisesRegex(ControlError, "effort for claude must be one of"):
            self.b.command({"action": "set_agent_options", "agent": "claude", "effort": "ultra"})
        with self.assertRaisesRegex(ControlError, "no model or effort setting"):
            self.b.command({"action": "set_agent_options", "agent": "fake", "effort": "low"})
        out = self.b.command({"action": "set_agent_options", "agent": "claude", "model": "haiku", "effort": "low"})
        self.assertIn("effort low", out["message"])
        ao = self.b.snapshot()["agent_options"]["claude"]
        self.assertEqual((ao["model"], ao["effort"]), ("haiku", "low"))
        self.assertEqual(runtime.load_config()["agents"]["claude_effort"], "low")  # persisted, not just in memory
        tid = self.create(DONE, agent="claude", effort="high", model="")
        row = self.store.one("select model, effort from tasks where id = ?", int(tid))
        self.assertEqual((row["model"], row["effort"]), (None, "high"))
        t = self.task(self.b.snapshot(), tid)
        self.assertEqual((t["model"], t["effort"]), (None, "high"))
        with self.assertRaisesRegex(ControlError, "effort for claude"):
            self.create(DONE, agent="claude", effort="ultra")
        self.cmd(tid, "stop")

    def test_auto_tasks_explain_the_wait_and_the_routing_preference_is_saved(self):
        self.assertEqual(self.b.snapshot()["routing"], {"pool": ["claude", "codex"]})
        tid = self.create(DONE, agent="auto")
        t = self.task(self.b.snapshot(), tid)
        self.assertEqual((t["backend"], t["routing"]), ("auto", "auto"))
        reasons = [r["message"] for r in t["queue_reasons"] if r["code"] == "routing"]
        self.assertEqual(reasons, ["No agent can start this yet: claude not logged in; codex not logged in"])
        self.login("codex")
        reasons = [r["code"] for r in self.task(self.b.snapshot(), tid)["queue_reasons"]]
        self.assertNotIn("routing", reasons)  # codex can take it now
        out = self.b.command({"action": "set_routing", "first": "codex"})
        self.assertIn("codex then claude", out["message"])
        self.assertEqual(self.b.snapshot()["routing"], {"pool": ["codex", "claude"]})
        self.assertEqual(runtime.load_config()["routing"]["pool"], ["codex", "claude"])  # persisted
        with self.assertRaisesRegex(ControlError, "claude or codex"):
            self.b.command({"action": "set_routing", "first": "fake"})
        with self.assertRaisesRegex(ControlError, "belong to a specific agent"):
            self.create(DONE, agent="auto", effort="low")
        self.cmd(tid, "stop")


class Http(BridgeTest):
    def test_server_drives_the_real_runtime(self):
        server = ControlServer(self.b)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(lambda: (server.shutdown(), server.server_close()))
        hdr = {"Authorization": "Bearer " + server.token, "Origin": server.origin, "Content-Type": "application/json"}

        def call(method, path, body=None):
            c = http.client.HTTPConnection("127.0.0.1", server.server_port)
            c.request(method, path, body=json.dumps(body) if body else None, headers=hdr)
            r = c.getresponse()
            return r.status, json.loads(r.read())

        status, out = call("POST", "/api/command", {"action": "create_task", "project_id": "p", "title": "via http",
                                                    "spec": edit("src/h.py") + DONE, "scope": "src", "agent": "fake"})
        self.assertEqual(status, 200)
        self.pump(lambda s: self.task(s, out["task_id"])["state"] == "COMPLETED")
        status, snap = call("GET", "/api/snapshot?cursor=0")
        self.assertEqual((status, snap["mode"]), (200, "real"))
        status, detail = call("GET", f"/api/tasks/{out['task_id']}")
        self.assertEqual(status, 200)
        self.assertTrue(any(a["kind"] == "diff" and "content" in a for a in detail["task"]["artifacts"]))
        self.assertEqual(call("GET", "/api/tasks/999")[0], 404)
        status, err = call("POST", "/api/command", {"action": "stop", "task_id": out["task_id"], "attempt_id": "x"})
        self.assertEqual(status, 400)
        self.assertIn("Attempt changed", err["error"])


if __name__ == "__main__":
    unittest.main()
