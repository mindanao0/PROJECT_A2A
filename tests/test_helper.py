"""Local helper acceptance (docs/MVP_CONTRACT.md §8): summaries cite sources, nothing sensitive or executable."""

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from navis import helper, runtime
from test_navis import DONE, TOKEN, NavisTest, edit


class FakeOllama(BaseHTTPRequestHandler):
    seen, reply = [], ""

    def do_POST(self):
        FakeOllama.seen.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
        body = json.dumps({"message": {"role": "assistant", "content": FakeOllama.reply}}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


class Helper(NavisTest):
    def setUp(self):
        super().setUp()
        FakeOllama.seen, FakeOllama.reply = [], ""
        self.srv = HTTPServer(("127.0.0.1", 0), FakeOllama)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.config(f'[helper]\nurl = "http://127.0.0.1:{self.srv.server_port}"\nmodel = "m"\n')

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        super().tearDown()

    def config(self, extra):
        cfg = self.tmp / "cfg" / "config.toml"
        base = cfg.read_text().split("[helper]")[0]
        cfg.write_text(base + extra)

    def finished_task(self):
        tid = self.add(edit("src/x.py") + DONE)
        self.run_all()
        return tid

    def test_summary_cites_sources_and_flags_invented_refs(self):
        tid = self.finished_task()
        first = self.store.one("select min(id) i from events where task = ?", tid)["i"]
        FakeOllama.reply = f"It ran and completed [event:{first}]. It also deployed [event:99999]."
        r = helper.summarize(self.store, tid)
        self.assertEqual(r["cited"], [f"event:{first}"])
        self.assertEqual(r["unknown_refs"], ["event:99999"])
        self.assertIn(f"log:{tid}-1", r["sources"])
        self.assertEqual(self.store.one("select kind from events where task = ? order by id desc", tid)["kind"], "summary")

    def test_helper_gets_no_tools_and_no_credentials(self):
        tid = self.finished_task()
        self.store.log(tid, None, "note", text=f"leaked {TOKEN}")
        log = runtime.data_dir() / "attempts" / f"{tid}-1" / "agent.log"
        log.write_text(f"agent printed {TOKEN}\n")
        FakeOllama.reply = f"The agent printed {TOKEN} [log:{tid}-1]"
        r = helper.summarize(self.store, tid)
        sent = json.dumps(FakeOllama.seen)
        self.assertNotIn(TOKEN, sent)
        self.assertIn("[REDACTED]", sent)
        self.assertNotIn(TOKEN, r["text"])
        self.assertEqual(set(FakeOllama.seen[0]), {"model", "stream", "messages"})  # no tools, no files

    def test_remote_url_is_refused_without_a_request(self):
        tid = self.finished_task()
        self.config('[helper]\nurl = "http://example.com:11434"\n')
        with self.assertRaises(ValueError):
            helper.summarize(self.store, tid)
        self.assertEqual(FakeOllama.seen, [])

    def test_proxy_environment_is_ignored(self):
        tid = self.finished_task()
        FakeOllama.reply = "ok"
        import os
        os.environ["http_proxy"] = "http://127.0.0.1:9"  # nothing listens there
        try:
            helper.summarize(self.store, tid)
        finally:
            del os.environ["http_proxy"]
        self.assertEqual(len(FakeOllama.seen), 1)


if __name__ == "__main__":
    unittest.main()
