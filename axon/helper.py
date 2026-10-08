"""Local helper (D-004): summarize a task's events and agent log with a local model.

The helper has no tools: one HTTP call to a loopback Ollama, carrying only redacted text.
Nothing it returns is executed or written to a workspace."""

import json
import re
import urllib.parse
import urllib.request

from . import runtime

LOG_TAIL = 6000
EVENT_CAP = 200
SYSTEM = ("You summarize the activity of a coding task for its owner. Use only the sources given. "
          "After every claim cite its source as [event:N] or [log:ID]. Say 'inference:' before anything "
          "the sources do not state outright. If the sources are not enough, say so.")


def _loopback(url):
    return urllib.parse.urlparse(url).hostname in ("127.0.0.1", "localhost", "::1")


def sources(store, tid):
    """{ref: text} of what the helper may read: the task's events and its newest agent log."""
    found = {f"event:{e['id']}": f"{e['kind']} {e['attempt'] or '-'} {e['data']}"
             for e in store.q("select * from events where task = ? order by id desc limit ?", tid, EVENT_CAP)}
    last = store.one("select id from attempts where task = ? order by n desc", tid)
    log = last and runtime.data_dir() / "attempts" / last["id"] / "agent.log"
    if log and log.exists():
        found[f"log:{last['id']}"] = log.read_bytes()[-LOG_TAIL:].decode(errors="replace")
    return dict(sorted(found.items()))


def summarize(store, tid):
    cfg = runtime.load_config()["helper"]
    if not _loopback(cfg["url"]):
        raise ValueError(f"helper url must be loopback (local-only, no cloud fallback): {cfg['url']}")
    if not store.one("select 1 from tasks where id = ?", tid):
        raise ValueError(f"no task {tid}")
    redact = runtime.Runtime(store).redact
    src = {ref: redact(text) for ref, text in sources(store, tid).items()}
    body = "\n".join(f"[{ref}] {text}" for ref, text in src.items())
    req = urllib.request.Request(
        cfg["url"].rstrip("/") + "/api/chat", method="POST", headers={"Content-Type": "application/json"},
        data=json.dumps({"model": cfg["model"], "stream": False, "messages": [
            {"role": "system", "content": SYSTEM}, {"role": "user", "content": body}]}).encode())
    # No proxies: an http_proxy in the environment must not carry local text off the machine.
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=cfg["timeout"]) as r:
        text = redact(json.load(r)["message"]["content"])
    cited = sorted(set(re.findall(r"\[((?:event|log):[\w-]+)\]", text)))
    out = {"text": text, "cited": [c for c in cited if c in src], "unknown_refs": [c for c in cited if c not in src],
           "sources": list(src), "model": cfg["model"]}
    store.log(tid, None, "summary", **out)
    return out
