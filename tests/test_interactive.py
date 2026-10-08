"""Interactive mode: the agent runs as a real terminal session (tmux) instead of one `-p` prompt."""

import subprocess
import threading
import unittest

from axon import runtime
from tests.test_axon import DONE, AxonTest, edit, step


def sessions():
    return runtime.chat_sessions()


class Interactive(AxonTest):
    def setUp(self):
        super().setUp()
        with open(self.tmp / "cfg" / "config.toml", "a") as f:
            f.write('[agents]\nfake_mode = "interactive"\n')
        self.rt = runtime.Runtime(self.store)

    def test_a_session_that_stays_open_ends_when_the_agent_reports(self):
        tid = self.add(edit("src/new.py", "print(1)") + DONE + step("hang"))  # a TUI does not exit by itself
        self.run_all()
        self.assertEqual(self.task(tid)["status"], "COMPLETED")
        self.assertEqual(self.shown(f"{tid}-1", "src/new.py"), "print(1)")
        self.assertNotIn(f"axon-chat-task{tid}", sessions())
        self.assertTrue(self.store.one("select 1 from events where task = ? and kind = 'interactive'", tid))

    def test_stop_ends_the_session_and_its_processes(self):
        tid = self.add(step("hang"))
        runner = threading.Thread(target=self.rt.run_until_idle, kwargs={"timeout": 60})
        runner.start()
        self.wait(lambda: f"axon-chat-task{tid}" in sessions())
        runtime.stop_task(self.store, tid)
        runner.join(30)
        self.assertEqual(self.task(tid)["status"], "CANCELLED")
        self.assertNotIn(f"axon-chat-task{tid}", sessions())

    def test_the_user_closing_the_session_files_it_as_unreported(self):
        tid = self.add(step("hang"))
        runner = threading.Thread(target=self.rt.run_until_idle, kwargs={"timeout": 60})
        runner.start()
        self.wait(lambda: f"axon-chat-task{tid}" in sessions())
        subprocess.run(["tmux", "kill-session", "-t", f"=axon-chat-task{tid}"])
        runner.join(30)
        self.assertEqual(self.outcomes(tid), ["unreported"])
        self.assertEqual(self.task(tid)["status"], "REVIEW")

    def test_the_usage_limit_text_in_the_terminal_files_quota_and_a_later_attempt_finishes(self):
        tid = self.add(step("shell", cmd="echo '5-hour limit reached, resets 3pm'", attempt=1) + step("hang", attempt=1)
                       + edit("src/q.py", attempt=2) + DONE)
        self.run_all()
        self.assertEqual(self.outcomes(tid), ["quota", "done"])
        self.assertEqual(self.task(tid)["status"], "COMPLETED")

    def test_the_limit_text_is_found_when_the_terminal_places_words_with_cursor_codes(self):
        raw = "5-hour limit\x1b[3Greached \x1b[1m· resets 3pm"
        self.assertTrue(runtime.TUI_QUOTA_RE.search(runtime.ANSI_RE.sub(" ", raw)))
        self.assertFalse(runtime.TUI_QUOTA_RE.search("the rate limit module handles a quota"))

    def test_claude_opens_with_the_prompt_instead_of_dash_p(self):
        argv, _, _ = runtime.claude_cmd("p", ["mcp"], self.tmp, self.tmp, interactive=True)
        self.assertNotIn("-p", argv)
        self.assertEqual(argv[1], "p")
        argv, _, _ = runtime.claude_cmd("p", ["mcp"], self.tmp, self.tmp)
        self.assertEqual(argv[1:3], ["-p", "p"])

    def test_trusting_a_clone_keeps_claudes_other_settings_and_drops_gone_clones(self):
        home, gone = self.tmp / "h", runtime.data_dir() / "attempts" / "9-1" / "repo"
        home.mkdir()
        (home / ".claude.json").write_text('{"theme": "dark", "projects": {"%s": {"hasTrustDialogAccepted": true}, "/x": {}}}' % gone)
        runtime.trust_folder(home, self.tmp / "clone")
        d = __import__("json").loads((home / ".claude.json").read_text())
        self.assertEqual(d["theme"], "dark")
        self.assertEqual(sorted(d["projects"]), sorted(["/x", str(self.tmp / "clone")]))
        self.assertTrue(d["projects"][str(self.tmp / "clone")]["hasTrustDialogAccepted"])

if __name__ == "__main__":
    unittest.main()
