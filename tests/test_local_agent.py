"""Phase 4: the local Agent Runner. Unit tests drive the loop with a scripted model; end-to-end tests run
it through the Runner (bubblewrap + cgroup) against a scripted loopback model server."""

import json
import os
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from navis import local_agent as la
from navis import runtime, usage
from test_navis import NavisTest


def call(_tool, **args):
    return json.dumps({"name": _tool, "arguments": args})


def reply(content, **extra):
    return {"message": {"role": "assistant", "content": content}, "prompt_eval_count": 100, "eval_count": 10, **extra}


class StubMcp:
    def __init__(self):
        self.calls = []

    def call(self, tool, args):
        self.calls.append((tool, args))
        return {"content": [{"type": "text", "text": "exit 0" if tool == "run_check" else "recorded"}], "isError": False}


class Script:
    """A model that answers from a list, then repeats its last answer."""

    def __init__(self, *answers):
        self.answers, self.seen = list(answers), []

    def __call__(self, url, model, messages, tools, timeout=0, options=None):
        self.options = options
        self.seen.append([dict(m) for m in messages])
        a = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        return a if isinstance(a, dict) else reply(a)


class Parsing(unittest.TestCase):
    def test_calls_are_found_in_text_fences_prose_and_structured_form(self):
        c = call("read_file", path="a.py")
        self.assertEqual(la.parse_calls({"content": c}), [("read_file", {"path": "a.py"})])
        self.assertEqual(la.parse_calls({"content": f"Sure!\n```json\n{c}\n```\nDone."}), [("read_file", {"path": "a.py"})])
        self.assertEqual(la.parse_calls({"content": c + "\n" + call("run_check", name="ok")}),
                         [("read_file", {"path": "a.py"}), ("run_check", {"name": "ok"})])
        self.assertEqual(la.parse_calls({"content": "", "tool_calls": [{"function": {"name": "x", "arguments": {"a": 1}}}]}),
                         [("x", {"a": 1})])
        self.assertEqual(la.parse_calls({"content": '{"name": "t", "parameters": {"p": 1}}'}), [("t", {"p": 1})])

    def test_garbage_is_no_call(self):
        for text in ("", "I will do it.", "{not json", '{"nope": 1}', "[1, 2]"):
            self.assertEqual(la.parse_calls({"content": text}), [])

    def test_validation_messages(self):
        v = la.validate
        self.assertIsNone(v("write_file", {"path": "a", "content": "b"}, False))
        self.assertIn("unknown tool", v("rm", {}, False))
        self.assertIn("missing argument", v("write_file", {"path": "a"}, False))
        self.assertIn("must be string", v("write_file", {"path": "a", "content": 5}, False))
        self.assertIn("must be integer", v("read_file", {"path": "a", "start_line": True}, False))
        self.assertIn("unknown argument", v("read_file", {"path": "a", "mode": "x"}, False))
        self.assertIn("JSON object", v("read_file", "a.py", False))
        self.assertIn("unknown tool", v("write_file", {"path": "a", "content": "b"}, True))  # read-only role


class Permissions(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="nvl-")).resolve()
        self.root = str(self.tmp / "ws")
        os.makedirs(self.root + "/.git")
        (self.tmp / "secret.txt").write_text("outside")
        os.symlink(self.tmp / "secret.txt", self.root + "/link.txt")
        os.symlink(self.tmp, self.root + "/dirlink")
        self.agent = la.Agent(self.root, StubMcp(), False)

    def denied(self, name, **args):
        ok, text = self.agent.run(name, args)
        self.assertFalse(ok, text)
        self.assertIn("denied", text)

    def test_nothing_outside_the_workspace_or_in_dot_git_is_reachable(self):
        for path in ("../secret.txt", str(self.tmp / "secret.txt"), "/etc/passwd", "link.txt", "dirlink/secret.txt",
                     ".git/config", "a/../../secret.txt", "a/../.git/HEAD"):
            self.denied("read_file", path=path)
            self.denied("write_file", path=path, content="x")
        self.denied("list_files", path="..")
        self.denied("replace_in_file", path="link.txt", old="o", new="x")
        self.assertEqual((self.tmp / "secret.txt").read_text(), "outside")
        self.assertEqual(os.listdir(self.root + "/.git"), [])

    def test_normal_work_inside_works(self):
        self.assertTrue(self.agent.run("write_file", {"path": "src/a.py", "content": "x = 1\n"})[0])
        self.assertEqual(self.agent.run("read_file", {"path": "src/a.py"}), (True, "1: x = 1"))
        self.assertTrue(self.agent.run("replace_in_file", {"path": "src/a.py", "old": "1", "new": "2"})[0])
        self.assertEqual((Path(self.root) / "src/a.py").read_text(), "x = 2\n")
        self.assertIn("src/", self.agent.run("list_files", {})[1])
        self.assertNotIn(".git", self.agent.run("list_files", {})[1])

    def test_replace_needs_exactly_one_match_and_limits_hold(self):
        self.agent.run("write_file", {"path": "a.txt", "content": "aa"})
        self.assertIn("exactly once", self.agent.run("replace_in_file", {"path": "a.txt", "old": "a", "new": "b"})[1])
        self.assertIn("too large", self.agent.run("write_file", {"path": "big", "content": "x" * (la.MAX_WRITE_BYTES + 1)})[1])
        self.agent.writes = la.MAX_WRITES
        self.assertIn("write limit", self.agent.run("write_file", {"path": "b.txt", "content": "x"})[1])
        (Path(self.root) / "bin").write_bytes(b"\0\1\2")
        self.assertEqual(self.agent.run("read_file", {"path": "bin"}), (False, "binary file"))


class Loop(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="nvl-")
        self.mcp = StubMcp()
        self.agent = la.Agent(os.path.realpath(self.root), self.mcp, False)

    def run_loop(self, script, max_turns=20, readonly=False):
        self.agent.readonly = readonly
        la.loop("do it", self.agent, "u", "m", max_turns, readonly, ask=script)

    def reports(self):
        return [a for t, a in self.mcp.calls if t == "report_result"]

    def test_finishes_when_the_model_reports(self):
        s = Script(call("write_file", path="a.py", content="x"), call("run_check", name="ok"), call("report_result", status="done", summary="ok"))
        self.run_loop(s)
        self.assertEqual(self.reports(), [{"status": "done", "summary": "ok"}])
        self.assertEqual(len(s.seen), 3)

    def test_turn_limit_ends_with_a_clean_failure_report(self):
        self.run_loop(Script(*[call("list_files", path=str(i)) for i in range(50)]), max_turns=4)
        self.assertEqual(self.reports()[0]["status"], "failed")
        self.assertIn("turn limit reached (4)", self.reports()[0]["summary"])

    def test_invalid_calls_are_fed_back_then_stop_the_run(self):
        s = Script(call("rm", path="x"), call("write_file", path="a"), "{broken", call("read_file", path=5), call("nope"))
        self.run_loop(s)
        self.assertIn("too many invalid tool calls", self.reports()[0]["summary"])
        fed_back = [m["content"] for m in s.seen[1] if m["role"] == "tool"]
        self.assertTrue(fed_back and fed_back[0].startswith("invalid call: unknown tool"))

    def test_prose_without_a_call_is_nudged_then_stops(self):
        s = Script("I think this is done.")
        self.run_loop(s)
        self.assertIn("stopped calling tools", self.reports()[0]["summary"])
        self.assertEqual(len(s.seen), la.MAX_NO_TOOL)

    def test_a_repeated_identical_call_is_cut_off(self):
        self.run_loop(Script(call("list_files", path=".")))
        self.assertIn("repeated", self.reports()[0]["summary"])

    def test_per_turn_limits_reach_the_model_call_and_a_cut_off_reply_is_reported(self):
        s = Script(reply('{"name": "report_result", "arg', done_reason="length"), call("report_result", status="done", summary="ok"))
        la.loop("do it", self.agent, "u", "m", 5, False, ask=s, options={"num_predict": 77, "num_gpu": 99})
        self.assertEqual(s.options, {"num_predict": 77, "num_gpu": 99})
        self.assertEqual(self.reports(), [{"status": "done", "summary": "ok"}])  # the truncated reply was nudged, not obeyed

    def test_ask_user_is_discouraged_in_the_system_prompt(self):
        self.assertIn("reasonable assumption instead of asking", la.SYSTEM)

    def test_the_first_question_is_pushed_back_and_a_second_one_reaches_the_user(self):
        s = Script(call("ask_user", question="Should I create the file?"), call("write_file", path="a.py", content="x"),
                   call("ask_user", question="Which of a.py or b.py is the entry point?"))
        self.run_loop(s, max_turns=6)
        asked = [a for t, a in self.mcp.calls if t == "ask_user"]
        self.assertEqual(asked, [{"question": "Which of a.py or b.py is the entry point?"}])  # only the real one
        self.assertIn("Do not ask for confirmation", [m["content"] for m in s.seen[1] if m["role"] == "tool"][0])
        self.assertTrue((Path(self.root) / "a.py").exists())

    def test_only_the_first_of_several_calls_runs(self):
        s = Script(call("write_file", path="a.py", content="x") + "\n" + call("report_result", status="done", summary="early"),
                   call("report_result", status="done", summary="real"))
        self.run_loop(s)
        self.assertEqual(self.reports(), [{"status": "done", "summary": "real"}])  # the early report was not executed
        self.assertIn("Only the first tool call was run", s.seen[1][-1]["content"])

    def test_old_tool_output_is_dropped_when_the_conversation_grows(self):
        (Path(self.root) / "big.txt").write_text("line\n" * 4000)
        calls = [call("read_file", path="big.txt", start_line=i * 400 + 1, max_lines=400) for i in range(9)] + [
            call("report_result", status="done", summary="ok")]
        s = Script(*calls)
        self.run_loop(s)
        last = [m["content"] for m in s.seen[-1]]
        self.assertTrue(any(c == "[older output omitted]" for c in last))
        self.assertEqual(sum(c != "[older output omitted]" and c.startswith("3") for c in last), 1)  # the newest read is intact
        # The conversation stays bounded: at most the limit plus the recent turns that are never dropped.
        self.assertLessEqual(sum(map(len, last)), la.CONTEXT_CHARS + la.KEEP_RECENT * 4000)
        self.assertEqual(self.reports()[0]["summary"], "ok")

    def test_read_only_role_has_no_write_tools(self):
        s = Script(call("write_file", path="a.py", content="x"), call("report_result", status="done", summary="looks fine"))
        self.run_loop(s, readonly=True)
        self.assertFalse((Path(self.root) / "a.py").exists())
        self.assertIn("unknown tool", [m["content"] for m in s.seen[1] if m["role"] == "tool"][0])
        self.assertEqual(self.reports()[0]["summary"], "looks fine")

    def test_the_model_sees_no_write_tool_schema_when_read_only(self):
        self.assertNotIn("write_file", [t["function"]["name"] for t in la.schemas(True)])
        self.assertIn("write_file", [t["function"]["name"] for t in la.schemas(False)])


class FakeModel(BaseHTTPRequestHandler):
    answers, delay, hits = [], 0.0, 0

    def do_POST(self):
        self.rfile.read(int(self.headers["Content-Length"]))
        type(self).hits += 1
        time.sleep(type(self).delay)
        a = type(self).answers.pop(0) if len(type(self).answers) > 1 else type(self).answers[0]
        body = json.dumps(a if isinstance(a, dict) else reply(a)).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


class Runner(NavisTest):
    def setUp(self):
        super().setUp()
        FakeModel.answers, FakeModel.delay, FakeModel.hits = [], 0.0, 0
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), FakeModel)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.configure(f"http://127.0.0.1:{self.srv.server_port}")

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        super().tearDown()

    def configure(self, url, coding=True, extra=""):
        base = (self.tmp / "cfg" / "config.toml").read_text().split("[local]")[0]
        (self.tmp / "cfg" / "config.toml").write_text(
            base + f'[local]\ncoding = {str(coding).lower()}\nurl = "{url}"\nmodel = "m"\nmax_turns = 6\n{extra}')
        self.rt = runtime.Runtime(self.store)

    def add_local(self, spec="Create src/x.py containing x = 1, check it, then report.", scope=("src",)):
        tid, dup = runtime.add_task(self.store, "p", "local", spec, scope)
        self.assertIsNone(dup)
        return tid

    def test_a_task_runs_end_to_end_through_the_sandboxed_runner_and_usage_is_recorded(self):
        FakeModel.answers = [call("write_file", path="src/x.py", content="x = 1\n"), call("run_check", name="ok"),
                             call("report_result", status="done", summary="wrote x")]
        tid = self.add_local()
        self.run_all()
        self.assertEqual(self.task(tid)["status"], "COMPLETED", self.task(tid)["note"])
        self.assertEqual(self.shown(f"{tid}-1", "src/x.py"), "x = 1\n")
        r = usage.report(self.store, 0)[("local", "implement")]
        self.assertEqual((r["with_usage"], r["input"], r["output"]), (1, 300, 30))
        self.assertEqual(FakeModel.hits, 3)

    def test_local_coding_must_be_switched_on(self):
        self.configure(f"http://127.0.0.1:{self.srv.server_port}", coding=False)
        with self.assertRaisesRegex(ValueError, "local coding is off"):
            runtime.add_task(self.store, "p", "local", "x", ["src"])

    def test_boundary_violations_by_the_model_are_denied_and_leave_nothing_on_the_host(self):
        marker = Path.home() / f".navis-local-escape-{os.getpid()}"
        FakeModel.answers = [call("write_file", path=str(marker), content="x"), call("write_file", path="../escape.txt", content="x"),
                             call("write_file", path=".git/hooks/pre-commit", content="x"), call("read_file", path="/etc/shadow"),
                             call("write_file", path="src/ok.py", content="ok = 1\n"), call("report_result", status="done", summary="d")]
        tid = self.add_local()
        self.run_all()
        self.assertEqual(self.task(tid)["status"], "COMPLETED", self.task(tid)["note"])
        self.assertFalse(marker.exists())
        self.assertEqual(self.shown(f"{tid}-1", "src/ok.py"), "ok = 1\n")
        log = (self.tmp / "home" / "attempts" / f"{tid}-1" / "agent.log").read_text()
        self.assertEqual(log.count('"ok": false'), 4)

    def test_a_looping_model_ends_failed_not_retried_forever(self):
        FakeModel.answers = [call("list_files", path=".")]
        tid = self.add_local()
        self.run_all()
        t = self.task(tid)
        self.assertEqual((t["status"], self.outcomes(tid)), ("FAILED", ["failed"]))
        self.assertIn("repeated", t["note"])

    def test_stop_cancels_a_slow_model_and_leaves_no_process(self):
        FakeModel.delay = 30
        tid = self.add_local()
        self.rt.tick()
        self.wait(lambda: FakeModel.hits >= 1)
        t0 = time.time()
        runtime.stop_task(self.store, tid)
        for th in self.rt.threads:
            th.join(30)
        self.assertLess(time.time() - t0, 15)
        self.assertEqual(self.task(tid)["status"], "CANCELLED")
        self.assertFalse(runtime.sandbox.active(self.store.one("select unit from attempts where task = ?", tid)["unit"]))

    def test_a_runner_crash_mid_run_is_recovered_and_the_late_result_is_rejected(self):
        FakeModel.delay = 20
        tid = self.add_local()
        self.rt.tick()  # the old runner starts the attempt, then "dies"
        self.wait(lambda: FakeModel.hits >= 1)
        unit = self.store.one("select unit from attempts where task = ?", tid)["unit"]
        runtime.Runtime(self.store).recover()  # the next runner
        for th in self.rt.threads:
            th.join(30)
        self.assertEqual((self.task(tid)["status"], self.outcomes(tid)), ("QUEUED", ["interrupted"]))
        self.assertFalse(runtime.sandbox.active(unit))
        kinds = [e["kind"] for e in self.store.q("select kind from events where task = ?", tid)]
        self.assertIn("stale-result-dropped", kinds)
        runtime.stop_task(self.store, tid)

    def test_an_unreachable_model_is_a_clean_failure(self):
        self.configure("http://127.0.0.1:9")  # nothing listens there
        tid = self.add_local()
        self.run_all()
        self.assertEqual(self.task(tid)["status"], "FAILED")
        self.assertIn("unreachable", self.task(tid)["note"])
        self.assertEqual(self.outcomes(tid), ["failed"])

    def test_a_remote_model_url_is_refused_local_only(self):
        self.configure("http://example.com:11434")
        tid = self.add_local()
        self.run_all()
        self.assertEqual(self.task(tid)["status"], "FAILED")
        self.assertIn("must be loopback", self.task(tid)["note"])
        self.assertEqual(FakeModel.hits, 0)

    def test_a_local_reviewer_is_read_only_and_its_verdict_counts(self):
        tid = self.add(__import__("test_navis").edit("src/x.py") + __import__("test_navis").DONE)
        self.run_all()
        FakeModel.answers = [call("write_file", path="src/evil.py", content="x"), call("read_file", path="src/x.py"),
                             call("report_result", status="failed", summary="src/x.py:1 needs a test")]
        rid, _ = runtime.request_review(self.store, tid, "local")
        self.run_all()
        self.assertEqual(self.task(rid)["status"], "COMPLETED", self.task(rid)["note"])
        (v,) = runtime.reviews(self.store, tid)
        self.assertEqual((v["verdict"], v["reviewer"]), ("changes", "local"))
        self.assertNotIn("evil.py", self.git("ls-tree", "-r", "--name-only", self.task(rid)["head"]))


if __name__ == "__main__":
    unittest.main()
