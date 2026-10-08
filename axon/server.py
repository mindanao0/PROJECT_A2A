"""Authenticated GUI transport. Binds loopback only; remote access goes through a proxy on this machine
(`tailscale serve`), whose host name must be allowed and which then needs the password login."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import mimetypes
import os
import secrets
import struct
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http.cookies import SimpleCookie, CookieError
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .core import ControlError

WEB = Path(__file__).with_name("web")
WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
LOGIN_LOCK = threading.Lock()  # one password guess at a time, 1 s apart after a miss
FILES = {"/": "index.html", "/app.js": "app.js", "/style.css": "style.css", "/axon-wordmark.svg": "axon-wordmark.svg",
         "/axon-icon.svg": "axon-icon.svg", "/xterm.js": "xterm.js", "/xterm.css": "xterm.css", "/addon-fit.js": "addon-fit.js"}


def hash_password(password, iterations=600_000):
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${digest.hex()}"


def check_password(password, stored):
    try:
        _, iterations, salt, digest = stored.strip().split("$")
        got = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iterations))
    except ValueError:
        return False
    return hmac.compare_digest(got.hex(), digest)


def ws_recv(rfile):
    """One client frame as (opcode, payload), or None when the connection closed."""
    head = rfile.read(2)
    if len(head) < 2:
        return None
    op, n = head[0] & 0x0F, head[1] & 0x7F
    if n == 126:
        n = struct.unpack(">H", rfile.read(2))[0]
    elif n == 127:
        n = struct.unpack(">Q", rfile.read(8))[0]
    if n > 1 << 20:
        return None
    mask = rfile.read(4) if head[1] & 0x80 else b""
    data = rfile.read(n)
    if mask:
        data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
    return None if op == 8 else (op, data)


def ws_frame(data, op=2):
    n = len(data)
    size = bytes([n]) if n < 126 else b"\x7e" + struct.pack(">H", n) if n < 65536 else b"\x7f" + struct.pack(">Q", n)
    return bytes([0x80 | op]) + size + data


class ControlServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, runtime, port=0, token=None, hosts=(), password_file=None):
        self.runtime = runtime
        self.token = token or secrets.token_urlsafe(32)
        self.session_token = secrets.token_urlsafe(32)
        self.password_file = password_file
        super().__init__(("127.0.0.1", port), Handler)
        self.origin = f"http://127.0.0.1:{self.server_port}"
        self.session_cookie = f"axon_session_{self.server_port}"
        self.local_hosts = {f"127.0.0.1:{self.server_port}", f"localhost:{self.server_port}"}
        self.remote_hosts = set(hosts)

    def password(self):
        try:
            return Path(self.password_file).read_text() if self.password_file else None
        except OSError:
            return None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        # No request URLs, fragments, tokens, or user content in access logs.
        pass

    def reply(self, status, content, kind="application/json; charset=utf-8", extra_headers=None):
        if not isinstance(content, bytes):
            content = json.dumps(content, ensure_ascii=False).encode()
        self.send_response(status)
        for name, value in {
            "Content-Type": kind, "Content-Length": str(len(content)), "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
            # Inline styles only for the terminal (xterm.js writes <style>); url() loads stay limited to 'self'.
            "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
        }.items():
            self.send_header(name, value)
        for name, value in (extra_headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(content)

    def session_ok(self):
        try:
            cookie = SimpleCookie(self.headers.get("Cookie", ""))
            value = cookie[self.server.session_cookie].value if self.server.session_cookie in cookie else ""
            return hmac.compare_digest(value.encode(), self.server.session_token.encode())
        except CookieError:
            return False

    def boundary(self, api=False, mutation=False):
        host, origin, remotes = self.headers.get("Host", ""), self.headers.get("Origin"), self.server.remote_hosts
        if host not in self.server.local_hosts and host not in remotes:
            self.reply(403, {"error": "Invalid host"})
            return False
        # A proxy may pass the Host on, or rewrite it to 127.0.0.1 while the browser's Origin keeps the remote name.
        allowed = {f"http://{host}", f"https://{host}"} | {f"https://{h}" for h in remotes}
        if (origin is not None or mutation) and origin not in allowed:
            self.reply(403, {"error": "Invalid origin"})
            return False
        if (host in remotes or origin in {f"https://{h}" for h in remotes}) and not self.server.password():
            self.reply(403, {"error": "Remote access needs a password: run `axon passwd` on the Axon machine"})
            return False
        if api:
            auth = self.headers.get("Authorization", "")
            ok = hmac.compare_digest(auth.encode(), ("Bearer " + self.server.token).encode()) if auth else self.session_ok()
            if not ok:
                login = bool(self.server.password())
                self.reply(401, {"error": "Sign in with your Axon password" if login else "Open the launch link (run `axon`)",
                                 "login": login})
                return False
        return True

    def set_session(self):
        secure = "; Secure" if (self.headers.get("Origin") or "").startswith("https://") else ""
        return {"Set-Cookie": f"{self.server.session_cookie}={self.server.session_token}; HttpOnly; SameSite=Strict; Path=/api/{secure}"}

    def do_GET(self):
        url = urlsplit(self.path)
        path, query = url.path, parse_qs(url.query)
        if not self.boundary(api=path.startswith("/api/"), mutation=path == "/api/chat/ws"):
            return
        if path == "/api/snapshot":
            try:
                cursor = int(query.get("cursor", ["0"])[0])
                if not 0 <= cursor <= 2**63 - 1:
                    raise ValueError
            except ValueError:
                self.reply(400, {"error": "Invalid event cursor"})
                return
            self.reply(200, self.server.runtime.snapshot(cursor))
            return
        if path == "/api/chat/ws":
            self.terminal(query.get("session", [""])[0])
            return
        if path.startswith("/api/tasks/"):
            task_id = path.removeprefix("/api/tasks/")
            if not task_id or "/" in task_id:
                self.reply(404, {"error": "Not found"})
                return
            try:
                self.reply(200, self.server.runtime.task_detail(task_id))
            except ControlError as exc:
                self.reply(404, {"error": str(exc)})
            return
        if path not in FILES or not (WEB / FILES[path]).exists():
            self.reply(404, {"error": "Not found"})
            return
        file = WEB / FILES[path]
        kind = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
        self.reply(200, file.read_bytes(), kind + ("; charset=utf-8" if kind.startswith("text/") or kind == "application/javascript" else ""))

    def terminal(self, session):
        """WebSocket <-> a pty attached to the chat's tmux session: keys go in as typed, output comes back as written.
        Client text frames are JSON: {"data": "..."} or {"resize": [cols, rows]}."""
        attach = getattr(self.server.runtime, "chat_attach", None)  # the simulation has no chats
        if attach is None or self.headers.get("Upgrade", "").lower() != "websocket":
            self.reply(404, {"error": "Not found"})
            return
        try:
            proc, fd = attach(session)
        except ControlError as exc:
            self.reply(400, {"error": str(exc)})
            return
        key = self.headers.get("Sec-WebSocket-Key", "")
        self.protocol_version = "HTTP/1.1"  # 101 exists only in HTTP/1.1; Firefox refuses an "HTTP/1.0 101"
        self.send_response(101)
        self.send_header("Upgrade", "websocket")
        self.send_header("Connection", "Upgrade")
        self.send_header("Sec-WebSocket-Accept", base64.b64encode(hashlib.sha1((key + WS_GUID).encode()).digest()).decode())
        self.end_headers()
        self.wfile.flush()
        self.close_connection = True
        lock, pty_open = threading.Lock(), [True]  # the pump closes the pty; writes check it under the lock (no fd reuse)

        def send(data, op=2):
            with lock:
                self.wfile.write(ws_frame(data, op))

        def to_pty(fn, *args):
            with lock:
                if pty_open[0]:
                    fn(fd, *args)

        def pump():
            try:
                while data := os.read(fd, 65536):
                    send(data)
            except OSError:
                pass  # the pty closed (session ended) or the browser went away
            with lock:
                pty_open[0] = False
                os.close(fd)
            try:
                send(b"", 8)
            except OSError:
                pass

        threading.Thread(target=pump, daemon=True).start()
        try:
            while frame := ws_recv(self.rfile):
                op, data = frame
                if op == 9:
                    send(data, 10)
                elif op == 2:
                    to_pty(os.write, data)
                elif op == 1:
                    msg = json.loads(data)
                    if isinstance(msg.get("data"), str):
                        to_pty(os.write, msg["data"].encode())
                    if isinstance(msg.get("resize"), list):
                        to_pty(self.server.runtime.chat_resize, *msg["resize"])
        except (OSError, ValueError, TypeError, AttributeError):
            pass
        finally:
            proc.terminate()  # detaches this viewer only; the tmux session keeps running
            proc.wait()

    def do_POST(self):
        path = urlsplit(self.path).path
        if path == "/api/login":
            self.login()
            return
        if not self.boundary(api=True, mutation=True):
            return
        if path == "/api/session":
            # Only the launch capability can establish a browser session.
            if not hmac.compare_digest(self.headers.get("Authorization", "").encode(), ("Bearer " + self.server.token).encode()):
                self.reply(401, {"error": "Open the launch link to establish a session"})
                return
            self.reply(200, {"ok": True}, extra_headers=self.set_session())
            return
        if path == "/api/chat/upload":
            upload = getattr(self.server.runtime, "chat_upload", None)  # the simulation has no chats
            if upload is None:
                self.reply(404, {"error": "Not found"})
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 8_000_000:
                    raise ValueError
            except ValueError:
                self.reply(413, {"error": "Invalid or oversized image (limit 8 MB)"})
                return
            self.connection.settimeout(30)
            try:
                session = parse_qs(urlsplit(self.path).query).get("session", [""])[0]
                result = upload(session, self.headers.get("Content-Type", "").split(";")[0], self.rfile.read(size))
            except (ValueError, ControlError) as exc:
                self.reply(400, {"error": str(exc)})
                return
            except TimeoutError:
                self.reply(408, {"error": "Request timed out"})
                return
            self.reply(200, result)
            return
        if path != "/api/command":
            self.reply(404, {"error": "Not found"})
            return
        ok, payload = self.json_body()
        if not ok:
            return
        try:
            result = self.server.runtime.command(payload)
        except (ValueError, UnicodeError, ControlError) as exc:
            self.reply(400, {"error": str(exc)})
            return
        self.reply(200, result)

    def json_body(self):
        """(True, parsed body), or (False, None) after replying with the error."""
        if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
            self.reply(415, {"error": "Expected application/json"})
            return False, None
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 16384:
                raise ValueError
        except ValueError:
            self.reply(413, {"error": "Invalid or oversized request"})
            return False, None
        self.connection.settimeout(5)
        try:
            return True, json.loads(self.rfile.read(size))
        except (ValueError, UnicodeError):
            self.reply(400, {"error": "Invalid JSON"})
        except TimeoutError:
            self.reply(408, {"error": "Request timed out"})
        return False, None

    def login(self):
        if not self.boundary(mutation=True):
            return
        stored = self.server.password()
        if not stored:
            self.reply(404, {"error": "No password is set; run `axon passwd` on the Axon machine"})
            return
        ok, body = self.json_body()
        if not ok:
            return
        password = body.get("password") if isinstance(body, dict) else None
        with LOGIN_LOCK:
            ok = isinstance(password, str) and 0 < len(password) <= 200 and check_password(password, stored)
            if not ok:
                time.sleep(1)
        if not ok:
            self.reply(401, {"error": "Wrong password", "login": True})
            return
        self.reply(200, {"ok": True}, extra_headers=self.set_session())
