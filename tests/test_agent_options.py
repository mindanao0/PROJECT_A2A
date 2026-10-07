"""ask_user options, per-task model/effort, and readable agent logs."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from navis import cli, runtime
from navis.core import ControlError
from test_bridge import BridgeTest
from test_navis import DONE, NavisTest, step

# Lines as printed by `claude -p --output-format stream-json --verbose` and `codex exec --json` (claude 2.1.292, codex 0.160.1).
CLAUDE = [
    '{"type":"system","subtype":"hook_started","hook_name":"SessionStart:startup"}',
    '{"type":"system","subtype":"init","cwd":"/x","tools":["Read"]}',
    '{"type":"assistant","message":{"content":[{"type":"tool_use","id":"t1","name":"Read","input":{"file_path":"/x/README.md"}}]}}',
    '{"type":"rate_limit_event","rate_limit_info":{"status":"allowed_warning"}}',
    '{"type":"user","message":{"role":"user","content":[{"tool_use_id":"t1","type":"tool_result","content":"1\\thello from README"}]}}',
    '{"type":"assistant","message":{"content":[{"type":"text","text":"The README says hello."}]}}',
    '{"type":"result","subtype":"success","is_error":false,"num_turns":2,"total_cost_usd":0.17}',
]
CODEX = [
    '{"type":"thread.started","thread_id":"01a1"}',
    '{"type":"turn.started"}',
    '{"type":"item.completed","item":{"id":"i0","type":"agent_message","text":"I will read it.\\n"}}',
    '{"type":"item.started","item":{"id":"i1","type":"command_execution","command":"/bin/bash -lc \'cat README.md\'","aggregated_output":"","exit_code":null,"status":"in_progress"}}',
    '{"type":"item.completed","item":{"id":"i1","type":"command_execution","command":"/bin/bash -lc \'cat README.md\'","aggregated_output":"hello from README\\n","exit_code":0,"status":"completed"}}',
    '{"type":"turn.completed","usage":{"input_tokens":35759,"output_tokens":66}}',
]


class ReadableLog(unittest.TestCase):
    def test_claude_conversation(self):
        text = runtime.readable_log("\n".join(CLAUDE))
        self.assertEqual(text.splitlines(), [
            "→ Read(file_path=/x/README.md)", "  ← 1\thello from README", "The README says hello.",
            "■ finished (num_turns 2, cost $0.17)"])

    def test_codex_conversation(self):
        text = runtime.readable_log("\n".join(CODEX))
        self.assertEqual(text.splitlines(), [
            "I will read it.", "→ $ /bin/bash -lc 'cat README.md'", "  ← exit 0", "    hello from README",
            "■ finished (35759 in, 66 out tokens)"])

    def test_plain_text_and_garbage_pass_through_and_long_output_is_clipped(self):
        self.assertEqual(runtime.readable_log("plain line\n{broken"), "plain line\n{broken")
        big = json.dumps({"type": "user", "message": {"content": [{"type": "tool_result", "content": "y" * 5000}]}})
        self.assertLess(len(runtime.readable_log(big)), 600)


class AdapterFlags(unittest.TestCase):
    def argv(self, adapter, **kw):
        with mock.patch.object(runtime, "_which", return_value=Path("/opt/x/bin/tool")), tempfile.TemporaryDirectory() as io:
            return adapter("PROMPT", ["py", "mcp"], Path("/h"), Path(io), **kw)[0]

    def test_claude_gets_model_and_effort_only_when_set(self):
        a = self.argv(runtime.claude_cmd)
        self.assertNotIn("--model", a)
        self.assertNotIn("--effort", a)
        a = self.argv(runtime.claude_cmd, model="sonnet", effort="high")
        self.assertEqual((a[a.index("--model") + 1], a[a.index("--effort") + 1]), ("sonnet", "high"))

    def test_codex_gets_model_and_effort_and_the_prompt_stays_last(self):
        a = self.argv(runtime.codex_cmd, model="gpt-x", effort="high")
        self.assertEqual(a[a.index("-m") + 1], "gpt-x")
        self.assertIn('model_reasoning_effort="high"', a)
        self.assertEqual(a[-1], "PROMPT")
        self.assertNotIn("-m", self.argv(runtime.codex_cmd))

    def test_validation(self):
        runtime.check_model("claude", "opus[1m]", "max")
        runtime.check_model("codex", "gpt-6.1-sol", "high")
        for agent, model, effort in (("claude", "a b", ""), ("claude", "", "turbo"), ("codex", "", "HIGH"),
                                     ("fake", "m", ""), ("claude", "--model", "")):
            with self.assertRaises(ValueError, msg=(agent, model, effort)):
                runtime.check_model(agent, model, effort)


class AskOptions(NavisTest):
    def test_options_are_kept_capped_and_a_number_answers(self):
        spec = (step("mcp", tool="ask_user", args={"question": "color?", "options": ["red", "blue", " ", "x" * 300] + list("abcd")}, attempt=1)
                + step("prompt", path="src/prompt.txt", attempt=2)
                + step("mcp", tool="report_result", args={"status": "done", "summary": "ok"}, attempt=2))
        tid = self.add(spec)
        self.run_all()
        opts = runtime.ask_options(self.store, tid)
        self.assertEqual((opts[:2], len(opts), len(opts[2])), (["red", "blue"], 6, 120))
        cli.main(["answer", str(tid), "2"])  # "2" is the second option
        self.run_all()
        self.assertEqual(self.task(tid)["status"], "COMPLETED")
        self.assertIn("A: blue", self.shown(f"{tid}-2", "src/prompt.txt"))

    def test_a_question_without_options_has_none(self):
        tid = self.add(step("mcp", tool="ask_user", args={"question": "why?"}, attempt=1) + DONE)
        self.run_all()
        self.assertEqual(runtime.ask_options(self.store, tid), [])

    def test_model_effort_are_checked_and_project_defaults_are_logged(self):
        with self.assertRaises(ValueError):
            runtime.add_task(self.store, "p", "fake", DONE, ["src"], model="m")
        p = self.tmp / "cfg" / "projects" / "p.toml"
        p.write_text(p.read_text() + '[agents.fake]\nmodel = "m1"\neffort = "low"\n')
        self.add(DONE)
        self.run_all()
        e = next(json.loads(r["data"]) for r in self.store.q("select data from events where kind = 'attempt'"))
        self.assertEqual((e["model"], e["effort"]), ("m1", "low"))


class InTheGui(BridgeTest):
    def test_options_reach_the_gui_and_a_click_answers(self):
        spec = (step("mcp", tool="ask_user", args={"question": "which?", "options": ["red", "blue"]}, attempt=1)
                + step("mcp", tool="report_result", args={"status": "done", "summary": "ok"}, attempt=2))
        tid = self.create(spec)
        snap = self.pump(lambda s: self.task(s, tid)["state"] == "WAITING_INPUT")
        pending = self.task(snap, tid)["pending"]
        self.assertEqual(pending["options"], ["red", "blue"])
        self.cmd(tid, "answer", text=pending["options"][1], pending_id=pending["id"])
        self.pump(lambda s: self.task(s, tid)["state"] == "COMPLETED")
        self.assertIn("Agent asked: which? [options: red | blue]",
                      [e["message"] for e in self.b.task_detail(str(tid))["events"]])

    def test_log_tab_has_the_conversation_and_the_raw_output(self):
        tid = self.create(DONE)
        snap = self.pump(lambda s: self.task(s, tid)["state"] == "COMPLETED")
        aid = self.task(snap, tid)["attempt_id"]
        (runtime.data_dir() / "attempts" / aid / "agent.log").write_text("\n".join(CODEX))
        logs = [a for a in self.b.task_detail(str(tid))["task"]["artifacts"] if a["kind"] == "agent_log"]
        self.assertEqual(len({a["id"] for a in logs}), 2)
        self.assertIn("→ $ /bin/bash -lc 'cat README.md'", logs[0]["content"])
        self.assertIn("thread.started", logs[1]["content"])

    def test_gui_task_with_a_bad_effort_is_refused(self):
        with self.assertRaisesRegex(ControlError, "effort for claude"):
            self.create(DONE, agent="claude", effort="turbo")


if __name__ == "__main__":
    unittest.main()
