"""Model and effort per agent: validation, precedence, CLI flags, persistence, and what an attempt records."""

import json
import shutil
import tempfile
import tomllib
import unittest
from pathlib import Path

from navis import agent_options as ao
from navis import cli, runtime, usage
from test_navis import DONE, NavisTest, edit


class Pure(unittest.TestCase):
    def test_validation(self):
        self.assertEqual(ao.validate("claude", " haiku ", "LOW"), ("haiku", "low"))
        self.assertEqual(ao.validate("codex", "", ""), ("", ""))
        self.assertEqual(ao.validate("codex", "gpt-6.1-sol", "ultra"), ("gpt-6.1-sol", "ultra"))
        for agent, model, effort in (("claude", "", "ultra"), ("codex", "", "extreme"), ("claude", "-rm -rf", ""),
                                     ("claude", "a b", ""), ("claude", "x" * 81, ""), ("claude", "m;ls", ""), ("fake", "", ""),
                                     ("local", "x", "")):
            with self.assertRaises(ValueError, msg=(agent, model, effort)):
                ao.validate(agent, model, effort)

    def test_a_model_can_never_look_like_a_flag(self):
        with self.assertRaises(ValueError):
            ao.validate("claude", "--dangerously-skip-permissions", "")

    def test_flags_for_each_cli(self):
        self.assertEqual(ao.flags("claude", "haiku", "low"), ["--model", "haiku", "--effort", "low"])
        self.assertEqual(ao.flags("claude", "", ""), [])
        self.assertEqual(ao.flags("codex", "gpt-6-luna", "low"), ["-m", "gpt-6-luna", "-c", 'model_reasoning_effort="low"'])
        self.assertEqual(ao.flags("codex", "", "high"), ["-c", 'model_reasoning_effort="high"'])
        self.assertEqual(ao.flags("fake", "x", "y"), [])

    def test_task_override_beats_config_beats_the_cli_default(self):
        cfg = {"agents": {"claude_model": "sonnet", "claude_effort": "high"}}
        self.assertEqual(ao.effective(cfg, "claude"), ("sonnet", "high"))
        self.assertEqual(ao.effective(cfg, "claude", "haiku", None), ("haiku", "high"))
        self.assertEqual(ao.effective(cfg, "claude", "haiku", "low"), ("haiku", "low"))
        self.assertEqual(ao.effective({}, "codex"), ("", ""))

    def test_save_keeps_the_other_sections_and_round_trips(self):
        d = Path(tempfile.mkdtemp(prefix="nvao-"))
        f = d / "cfg" / "config.toml"
        f.parent.mkdir()
        f.write_text('[limits]\nquota_backoff = [1, 2]\n[slots]\nfake = 3\n')
        self.assertEqual(ao.save(f, "claude", "haiku", "low"), ("haiku", "low"))
        ao.save(f, "codex", "", "medium")
        cfg = tomllib.loads(f.read_text())
        self.assertEqual(cfg["limits"]["quota_backoff"], [1, 2])
        self.assertEqual(cfg["slots"]["fake"], 3)
        self.assertEqual(cfg["agents"], {"claude_model": "haiku", "claude_effort": "low", "codex_model": "", "codex_effort": "medium"})
        with self.assertRaises(ValueError):
            ao.save(f, "claude", "", "ultra")
        self.assertEqual(tomllib.loads(f.read_text())["agents"]["claude_effort"], "low")  # a refused save changes nothing
        shutil.rmtree(d)

    def test_codex_model_suggestions_come_from_its_cache_and_only_listed_ones(self):
        d = Path(tempfile.mkdtemp(prefix="nvao-"))
        (d / "codex").mkdir()
        (d / "codex" / "models_cache.json").write_text(json.dumps({"models": [
            {"slug": "a", "visibility": "list"}, {"slug": "hidden", "visibility": "hide"}, {"slug": "b", "visibility": "list"}]}))
        self.assertEqual(ao.known_models("codex", d), ["a", "b"])
        self.assertEqual(ao.known_models("codex", d / "missing"), [])
        self.assertIn("haiku", ao.known_models("claude"))
        shutil.rmtree(d)


class Adapters(unittest.TestCase):
    def test_claude_argv_carries_model_and_effort_only_when_set(self):
        with tempfile.TemporaryDirectory() as io:
            plain, _, _ = runtime.claude_cmd("p", ["py", "m.py", "s"], Path("/h"), Path(io))
            argv, _, _ = runtime.claude_cmd("p", ["py", "m.py", "s"], Path("/h"), Path(io), model="haiku", effort="low")
        self.assertNotIn("--model", plain)
        self.assertNotIn("--effort", plain)
        self.assertEqual((argv[argv.index("--model") + 1], argv[argv.index("--effort") + 1]), ("haiku", "low"))

    @unittest.skipUnless(shutil.which("codex"), "needs the codex CLI on PATH")
    def test_codex_argv_carries_model_and_effort_only_when_set(self):
        plain, _, _ = runtime.codex_cmd("p", ["py", "m.py", "s"], Path("/h"), Path("/io"))
        argv, _, _ = runtime.codex_cmd("p", ["py", "m.py", "s"], Path("/h"), Path("/io"), model="gpt-6-luna", effort="low")
        self.assertNotIn("-m", plain)
        self.assertFalse([a for a in plain if "model_reasoning_effort" in a])
        self.assertEqual(argv[argv.index("-m") + 1], "gpt-6-luna")
        self.assertIn('model_reasoning_effort="low"', argv)
        self.assertEqual(argv[-1], "p")  # the prompt stays last


class Runtime(NavisTest):
    def set_config(self, **agents):
        f = self.tmp / "cfg" / "config.toml"
        f.write_text(f.read_text().split("[agents]")[0] + "[agents]\n" + "".join(f'{k} = "{v}"\n' for k, v in agents.items()))
        self.rt = runtime.Runtime(self.store)

    def recording(self):
        seen = []
        real = runtime.fake_cmd

        def cmd(prompt, mcp, home, io, readonly=False, model="", effort=""):
            seen.append((model, effort))
            return real(prompt, mcp, home, io, readonly)

        original = runtime.ADAPTERS["claude"]
        runtime.ADAPTERS["claude"] = cmd  # a "claude" agent that is really the fake, to see what the Runner passes
        self.addCleanup(runtime.ADAPTERS.__setitem__, "claude", original)
        return seen

    def run_claude(self, **kw):
        tid, dup = runtime.add_task(self.store, "p", "claude", edit("src/x.py") + DONE, ["src"], **kw)
        self.assertIsNone(dup)
        self.run_all()
        self.assertEqual(self.task(tid)["status"], "COMPLETED", self.task(tid)["note"])
        return tid

    def test_config_task_override_and_default_reach_the_adapter_and_are_recorded(self):
        seen = self.recording()
        self.run_claude()
        self.assertEqual(seen, [("", "")])  # nothing set: the CLI default
        self.set_config(claude_model="sonnet", claude_effort="high")
        tid = self.run_claude(effort="low")
        self.assertEqual(seen[-1], ("sonnet", "low"))  # the task overrides effort, config supplies the model
        row = self.store.one("select model, effort from attempts where task = ?", tid)
        self.assertEqual((row["model"], row["effort"]), ("sonnet", "low"))
        ev = [json.loads(e["data"]) for e in self.store.q("select data from events where task = ? and kind = 'settings'", tid)]
        self.assertEqual(ev, [{"model": "sonnet", "effort": "low"}])
        self.assertEqual(usage.report(self.store, 0)[("claude", "implement")]["settings"], ["default/default", "sonnet/low"])

    def test_invalid_overrides_and_unsupported_agents_are_refused_and_distinct_settings_are_distinct_work(self):
        with self.assertRaises(ValueError):
            runtime.add_task(self.store, "p", "claude", DONE, ["src"], effort="ultra")
        with self.assertRaises(ValueError):
            runtime.add_task(self.store, "p", "fake", DONE, ["src"], model="x")
        a, _ = runtime.add_task(self.store, "p", "claude", DONE, ["src"], effort="low")
        b, dup = runtime.add_task(self.store, "p", "claude", DONE, ["src"], effort="high")
        self.assertEqual((bool(b), dup), (True, None))  # same text, different effort: not a duplicate
        self.assertEqual(runtime.add_task(self.store, "p", "claude", DONE, ["src"], effort="low"), (None, a))

    def test_a_revision_by_the_same_agent_keeps_the_task_override(self):
        self.recording()
        tid = self.run_claude(effort="low", model="haiku")
        runtime.request_review(self.store, tid, "fake", '[[step]]\ndo = "mcp"\ntool = "report_result"\nargs = {status = "failed", summary = "x"}\n')
        self.run_all()
        rid, _ = runtime.revise(self.store, tid)
        self.assertEqual((self.task(rid)["model"], self.task(rid)["effort"]), ("haiku", "low"))

    def test_the_cli_shows_and_sets_options(self):
        import contextlib
        import io
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli.main(["agent-options", "claude", "--model", "haiku", "--effort", "low"])
            cli.main(["agent-options"])
        text = out.getvalue()
        self.assertIn("claude  model haiku", text)
        self.assertIn("effort low", text)
        self.assertIn("codex   model default", text)
        self.assertEqual(runtime.load_config()["agents"]["claude_effort"], "low")
        with self.assertRaises(SystemExit):
            cli.main(["agent-options", "claude", "--effort", "ultra"])


if __name__ == "__main__":
    unittest.main()
