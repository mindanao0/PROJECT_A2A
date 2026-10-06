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
    def test_completed_task_shows_evidence_and_events(self):
        tid = self.create(edit("src/new.py", "print(1)") + DONE)
        snap = self.pump(lambda s: self.task(s, tid)["state"] == "COMPLETED")
        t = self.task(snap, tid)
        self.assertEqual(snap["mode"], "real")
        self.assertEqual([p["id"] for p in snap["projects"]], ["p"])
        names = [a["name"] for a in t["artifacts"]]
        self.assertIn("check ok", names)
        self.assertIn("Changes (git diff --stat)", names)
        self.assertIn("src/new.py", next(a for a in t["artifacts"] if a["kind"] == "result")["content"])
        self.assertEqual(len(t["attempts"]), 1)
        types = [e["type"] for e in snap["events"]]
        self.assertTrue({"STATE", "ATTEMPT", "TOOL", "CHECK", "OUTCOME"} <= set(types), types)
        again = self.b.snapshot(snap["cursor"])
        self.assertEqual(again["events"], [])
        self.assertEqual(again["cursor"], snap["cursor"])

    def test_agents_report_login_state(self):
        agents = {a["name"]: a for a in self.b.snapshot()["agents"]}
        self.assertEqual(agents["fake"]["status"], "Ready")
        self.assertEqual(agents["codex"]["status"], "Not logged in")
        self.assertEqual(agents["claude"]["status"], "Not logged in")
        self.assertFalse(agents["codex"]["ok"])

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

    def test_review_approval_needs_the_current_request(self):
        tid = self.create(edit("docs/b.md") + DONE)
        snap = self.pump(lambda s: self.task(s, tid)["state"] == "REVIEW")
        t = self.task(snap, tid)
        self.assertIn("outside scope", t["pending"]["message"])
        with self.assertRaises(ControlError):
            self.cmd(tid, "approve", pending_id="stale")
        self.cmd(tid, "approve", pending_id=t["pending"]["id"])
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
        status, err = call("POST", "/api/command", {"action": "stop", "task_id": out["task_id"], "attempt_id": "x"})
        self.assertEqual(status, 400)
        self.assertIn("Attempt changed", err["error"])


if __name__ == "__main__":
    unittest.main()
