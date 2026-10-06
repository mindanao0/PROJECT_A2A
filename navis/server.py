"""Authenticated loopback GUI transport; never binds a remote address."""
from __future__ import annotations

import hmac
import json
import mimetypes
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .core import ControlError

WEB = Path(__file__).with_name("web")


class ControlServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, runtime, port=0, token=None):
        self.runtime = runtime
        self.token = token or secrets.token_urlsafe(32)
        super().__init__(("127.0.0.1", port), Handler)
        self.origin = f"http://127.0.0.1:{self.server_port}"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        # No request URLs, fragments, tokens, or user content in access logs.
        pass

    def reply(self, status, content, kind="application/json; charset=utf-8"):
        if not isinstance(content, bytes):
            content = json.dumps(content, ensure_ascii=False).encode()
        self.send_response(status)
        for name, value in {
            "Content-Type": kind, "Content-Length": str(len(content)), "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
            "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
        }.items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(content)

    def boundary(self, api=False, mutation=False):
        if self.headers.get("Host") != f"127.0.0.1:{self.server.server_port}":
            self.reply(403, {"error": "Invalid local host"})
            return False
        origin = self.headers.get("Origin")
        if (origin is not None and origin != self.server.origin) or (mutation and origin != self.server.origin):
            self.reply(403, {"error": "Invalid origin"})
            return False
        if api:
            auth = self.headers.get("Authorization", "")
            if not hmac.compare_digest(auth.encode("utf-8"), ("Bearer " + self.server.token).encode("utf-8")):
                self.reply(401, {"error": "Open the local launch link to authenticate"})
                return False
        return True

    def do_GET(self):
        path = urlsplit(self.path).path
        if not self.boundary(api=path.startswith("/api/")):
            return
        if path == "/api/snapshot":
            try:
                raw = parse_qs(urlsplit(self.path).query).get("cursor", ["0"])[0]
                cursor = int(raw)
                if not 0 <= cursor <= 2**63 - 1:
                    raise ValueError
            except ValueError:
                self.reply(400, {"error": "Invalid event cursor"})
                return
            self.reply(200, self.server.runtime.snapshot(cursor))
            return
        files = {"/": "index.html", "/app.js": "app.js", "/style.css": "style.css"}
        if path not in files:
            self.reply(404, {"error": "Not found"})
            return
        file = WEB / files[path]
        kind = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
        self.reply(200, file.read_bytes(), kind + "; charset=utf-8")

    def do_POST(self):
        if not self.boundary(api=True, mutation=True):
            return
        if self.path != "/api/command":
            self.reply(404, {"error": "Not found"})
            return
        if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
            self.reply(415, {"error": "Expected application/json"})
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 16384:
                raise ValueError
        except ValueError:
            self.reply(413, {"error": "Invalid or oversized request"})
            return
        self.connection.settimeout(5)
        try:
            payload = json.loads(self.rfile.read(size))
            result = self.server.runtime.command(payload)
        except (ValueError, UnicodeError, ControlError) as exc:
            self.reply(400, {"error": str(exc)})
            return
        except TimeoutError:
            self.reply(408, {"error": "Request timed out"})
            return
        self.reply(200, result)
