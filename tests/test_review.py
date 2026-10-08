"""Read-only reviews bound to the exact result commit (Phase 2) with fake-agent as reviewer."""

import tempfile
import unittest
from unittest import mock
from pathlib import Path

from axon import integrate, runtime
from test_axon import DONE, AxonTest, edit, step

def verdict(status, summary):
    return step("mcp", tool="report_result", args={"status": status, "summary": summary})


class Review(AxonTest):
    def implemented(self):
        tid = self.add(edit("src/x.py", "x = 1\n") + DONE)
        self.run_all()
        self.assertEqual(self.task(tid)["status"], "COMPLETED", self.task(tid)["note"])
        return tid

    def review(self, tid, note, agent="fake"):
        rid, dup = runtime.request_review(self.store, tid, agent, note)
        self.assertIsNone(dup)
        self.run_all()
        return rid

    def prompt_of(self, rid):
        return (self.tmp / "home" / "attempts" / f"{rid}-1" / "prompt.txt").read_text()

    def test_reviewer_sees_requirement_diff_and_evidence_but_not_the_implementers_account(self):
        tid = self.implemented()
        rid = self.review(tid, verdict("done", "looks right"))
        prompt = self.prompt_of(rid)
        self.assertIn("independent reviewer", prompt)
        self.assertIn("+x = 1", prompt)  # the immutable diff
        self.assertIn("- ok: exit 0", prompt)  # verifier evidence
        self.assertIn(self.task(tid)["spec"].strip(), prompt)  # the requirement
        impl_log = (self.tmp / "home" / "attempts" / f"{tid}-1" / "agent.log").read_text()
        self.assertIn("recorded; end your turn now", impl_log)
        self.assertNotIn("recorded; end your turn now", prompt)  # nothing of the implementer's own session
        r = self.task(rid)
        self.assertEqual((r["status"], r["kind"], r["target"], r["base"]), ("COMPLETED", "review", tid, self.task(tid)["head"]))
        (v,) = runtime.reviews(self.store, tid)
        self.assertEqual((v["verdict"], v["commit"], v["reviewer"], v["implementer"]),
                         ("approve", self.task(tid)["head"], "fake", "fake"))

    def test_changes_requested_is_a_completed_review_with_findings(self):
        tid = self.implemented()
        rid = self.review(tid, verdict("failed", "src/x.py:1 no test for x"))
        self.assertEqual(self.task(rid)["status"], "COMPLETED")
        (v,) = runtime.reviews(self.store, tid)
        self.assertEqual((v["verdict"], v["summary"]), ("changes", "src/x.py:1 no test for x"))
        self.assertFalse(runtime.review_approved(self.store, tid, self.task(tid)["head"]))

    def test_a_reviewer_that_edits_files_voids_its_verdict(self):
        tid = self.implemented()
        rid = self.review(tid, edit("src/x.py", "x = 2\n") + verdict("done", "fine"))
        self.assertEqual(self.task(rid)["status"], "FAILED")
        self.assertIn("verdict ignored", self.task(rid)["note"])
        self.assertEqual(runtime.reviews(self.store, tid), [])

    def test_review_gate_blocks_integration_until_the_exact_commit_is_approved(self):
        cfg = self.tmp / "cfg" / "projects" / "p.toml"
        cfg.write_text(cfg.read_text().replace("protected", "require_review = true\nprotected", 1))
        tid = self.implemented()
        with self.assertRaisesRegex(integrate.IntegrationError, "requires an approving review"):
            integrate.integrate(self.rt, tid)
        self.review(tid, verdict("failed", "needs work"))
        with self.assertRaisesRegex(integrate.IntegrationError, "requires an approving review"):
            integrate.integrate(self.rt, tid)
        self.review(tid, verdict("done", "ok now") + "# second opinion\n")
        self.assertTrue(integrate.integrate(self.rt, tid))

    def test_only_completed_implementation_tasks_are_reviewable_and_reviews_are_not_integrable(self):
        pending = self.add(step("hang"))
        with self.assertRaises(ValueError):
            runtime.request_review(self.store, pending, "fake")
        runtime.stop_task(self.store, pending)
        tid = self.implemented()
        rid = self.review(tid, verdict("done", "ok"))
        with self.assertRaises(ValueError):
            runtime.request_review(self.store, rid, "fake")
        with self.assertRaisesRegex(integrate.IntegrationError, "implementation task"):
            integrate.integrate(self.rt, rid)

    def test_the_same_review_is_not_queued_twice(self):
        tid = self.implemented()
        rid, _ = runtime.request_review(self.store, tid, "fake", verdict("done", "ok"))
        again, dup = runtime.request_review(self.store, tid, "fake", verdict("done", "ok"))
        self.assertEqual((again, dup), (None, rid))


@mock.patch.object(runtime, "_which", lambda name: Path(f"/opt/{name}/bin/{name}"))  # argv only: no CLI needed
class Adapters(unittest.TestCase):
    def test_claude_review_has_read_only_tools(self):
        with tempfile.TemporaryDirectory() as io:
            argv, _, _ = runtime.claude_cmd("p", ["py", "mcp.py", "s"], Path("/h"), Path(io), readonly=True)
        self.assertEqual(argv[argv.index("--tools") + 1], "Read,Glob,Grep")
        self.assertNotIn("Edit", argv[argv.index("--allowedTools") + 1])

    def test_codex_review_uses_the_read_only_sandbox(self):
        argv, _, _ = runtime.codex_cmd("p", ["py", "mcp.py", "s"], Path("/h"), Path("/io"), readonly=True)
        self.assertEqual(argv[argv.index("--sandbox") + 1], "read-only")


if __name__ == "__main__":
    unittest.main()
