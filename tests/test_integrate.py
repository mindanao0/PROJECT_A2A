"""Integration branch (D-014): merge on a Navis-owned ref, check the exact commit, user fast-forwards."""

import unittest

from navis import integrate
from test_navis import DONE, NavisTest, edit

REF = "refs/navis/integration/p"


class Integration(NavisTest):
    def done(self, path, text="x\n"):
        tid = self.add(edit(path, text) + DONE)
        self.run_all()
        self.assertEqual(self.task(tid)["status"], "COMPLETED", self.task(tid)["note"])
        return tid

    def commit_in_checkout(self, path, text):
        (self.proj / path).write_text(text)
        self.git("add", "-A")
        self.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "mine")

    def test_integrate_two_tasks_then_promote_fast_forwards_the_users_branch(self):
        base = self.git("rev-parse", "HEAD").strip()
        a, b = self.done("src/x.py"), self.done("src/y.py")
        integrate.integrate(self.rt, a)
        tip = integrate.integrate(self.rt, b)
        self.assertEqual(self.git("rev-parse", REF).strip(), tip)
        self.assertEqual(self.git("rev-parse", "HEAD").strip(), base)  # the user's branch is untouched
        self.assertEqual(self.git("status", "--porcelain"), "")
        self.assertNotIn("x.py", self.git("ls-files"))
        st = integrate.status(self.store, "p")
        self.assertEqual((st["can_promote"], st["tasks"], [c["rc"] for c in st["checks"]]), (True, [a, b], [0]))
        self.assertEqual(integrate.promote(self.store, "p"), tip)
        self.assertEqual(self.git("rev-parse", "HEAD").strip(), tip)
        self.assertIn("y.py", self.git("ls-files"))
        self.assertEqual(self.git("status", "--porcelain"), "")
        self.assertEqual(integrate.status(self.store, "p")["reason"], "nothing to promote")

    def test_conflicting_result_is_rejected_and_the_ref_stays(self):
        a, b = self.done("src/a.py", "a = 2\n"), self.done("src/a.py", "a = 3\n")
        tip = integrate.integrate(self.rt, a)
        with self.assertRaisesRegex(integrate.IntegrationError, "conflicts .* src/a.py"):
            integrate.integrate(self.rt, b)
        self.assertEqual(self.git("rev-parse", REF).strip(), tip)
        self.assertIn("integrate-error", [e["kind"] for e in self.store.q("select kind from events where task = ?", b)])

    def test_checks_run_on_the_merged_commit_and_a_failure_does_not_advance_the_ref(self):
        self.project({"few-files": "[ $(ls src | wc -l) -le 2 ]"})  # each task alone passes; both together do not
        a, b = self.done("src/x.py"), self.done("src/y.py")
        tip = integrate.integrate(self.rt, a)
        with self.assertRaisesRegex(integrate.IntegrationError, "checks failed on the integration commit: few-files"):
            integrate.integrate(self.rt, b)
        self.assertEqual(self.git("rev-parse", REF).strip(), tip)
        failed = [e for e in self.store.q("select data from events where task = ? and kind = 'integrate'", b)]
        self.assertIn('"ok": false', failed[0]["data"])

    def test_promote_refuses_a_dirty_tree_and_a_moved_branch_then_syncs(self):
        a, b = self.done("src/x.py"), self.done("src/y.py")
        integrate.integrate(self.rt, a)
        (self.proj / "docs/b.md").write_text("edited, not committed\n")
        with self.assertRaisesRegex(integrate.IntegrationError, "uncommitted"):
            integrate.promote(self.store, "p")
        self.git("checkout", "--", "docs/b.md")
        self.commit_in_checkout("docs/b.md", "my own change\n")
        st = integrate.status(self.store, "p")
        self.assertFalse(st["can_promote"])
        self.assertIn("your branch moved", st["reason"])
        tip = integrate.integrate(self.rt, b)  # brings the user's commit in, then merges the task
        self.assertTrue(integrate.status(self.store, "p")["can_promote"])
        integrate.promote(self.store, "p")
        self.assertEqual(self.git("rev-parse", "HEAD").strip(), tip)
        self.assertEqual(sorted(self.git("ls-files").split()), sorted(
            ["docs/b.md", "src/a.py", "src/x.py", "src/y.py", "tests/t.sh"]))
        self.assertEqual((self.proj / "docs/b.md").read_text(), "my own change\n")

    def test_promote_is_bound_to_the_commit_the_user_saw_and_runs_no_hooks(self):
        a, b = self.done("src/x.py"), self.done("src/y.py")
        first = integrate.integrate(self.rt, a)
        integrate.integrate(self.rt, b)
        with self.assertRaisesRegex(integrate.IntegrationError, "changed"):
            integrate.promote(self.store, "p", expected=first)
        marker = self.tmp / "hook-ran"
        hook = self.proj / ".git/hooks/post-merge"
        hook.write_text(f"#!/bin/sh\ntouch {marker}\n")
        hook.chmod(0o755)
        integrate.promote(self.store, "p")
        self.assertFalse(marker.exists())

    def test_only_a_completed_task_can_be_integrated_and_never_twice(self):
        tid = self.add(edit("src/x.py"))  # no report_result: ends in REVIEW
        self.run_all()
        with self.assertRaisesRegex(integrate.IntegrationError, "completed"):
            integrate.integrate(self.rt, tid)
        a = self.done("src/y.py")
        integrate.integrate(self.rt, a)
        with self.assertRaisesRegex(integrate.IntegrationError, "already"):
            integrate.integrate(self.rt, a)


if __name__ == "__main__":
    unittest.main()
