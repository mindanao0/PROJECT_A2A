"""Local coding agent: a bounded tool loop over a loopback model (D-004, OD-006, Phase 4).

Runs as the agent process of an attempt, inside the same bubblewrap sandbox and cgroup as Codex and
Claude, so Stop, Kill, recovery, the credential scan and usage accounting apply unchanged. The model
has no shell and no network: it can only call the tools below, and every file path is resolved
against the workspace (the current directory) before it is touched.

Local models often print tool calls as JSON text instead of structured `tool_calls` (qwen2.5-coder in
Ollama does), so calls are parsed out of the text, validated, and executed one per message. Everything
is bounded: turns, invalid calls, repeated calls, output sizes, files written and conversation size."""

import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

from .mcpclient import Mcp

MAX_READ_CHARS, MAX_WRITE_BYTES, MAX_WRITES, MAX_LIST = 20_000, 100_000, 50, 200
MAX_INVALID, MAX_REPEAT, MAX_NO_TOOL, CONTEXT_CHARS, KEEP_RECENT, MAX_PUSHBACKS = 5, 3, 3, 24_000, 6, 3

SYSTEM = (
    "You are a careful coding agent working in the current directory. Complete the task using ONLY the tools. "
    'Reply with exactly ONE tool call per message, as JSON {"name": ..., "arguments": {...}}, and nothing else. '
    "Workflow: read the relevant files, write the code, run the check with run_check, fix failures, then call "
    'report_result with status "done" (or "failed") and a short summary. Do not claim success without running the '
    "check when checks exist. Make a reasonable assumption instead of asking; use ask_user only when the task cannot "
    "be done without an answer. Paths are relative to the current directory.")

# name -> (description, {argument: type}, required)
TOOLS = {
    "list_files": ("List a directory (default '.').", {"path": str}, []),
    "read_file": ("Read a text file with line numbers.", {"path": str, "start_line": int, "max_lines": int}, ["path"]),
    "write_file": ("Create or overwrite a file with the given full content.", {"path": str, "content": str}, ["path", "content"]),
    "replace_in_file": ("Replace one exact occurrence of old with new in a file.", {"path": str, "old": str, "new": str},
                        ["path", "old", "new"]),
    "run_check": ("Run a project check (tests, lint); returns exit code and output.", {"name": str}, ["name"]),
    "report_result": ("Finish the task. status is done or failed.", {"status": str, "summary": str}, ["status", "summary"]),
    "ask_user": ("Ask the user a question, then stop.", {"question": str}, ["question"]),
    "delegate": ("Queue follow-up work as a separate task.", {"title": str, "spec": str, "scope": list}, ["title", "spec", "scope"]),
}
WRITERS = {"write_file", "replace_in_file"}
JSON_TYPE = {str: "string", int: "integer", list: "array"}


class Denied(Exception):
    pass


def emit(**event):
    print(json.dumps(event), flush=True)


def schemas(readonly):
    return [{"type": "function", "function": {"name": n, "description": d, "parameters": {
        "type": "object", "required": req, "properties": {k: ({"type": "array", "items": {"type": "string"}} if t is list
                                                              else {"type": JSON_TYPE[t]}) for k, t in props.items()}}}}
            for n, (d, props, req) in TOOLS.items() if not (readonly and n in WRITERS)]


def json_objects(text):
    """Every JSON object embedded in free text, in order (the model may add prose or code fences)."""
    dec, i, out = json.JSONDecoder(), 0, []
    while (i := text.find("{", i)) != -1:
        try:
            obj, end = dec.raw_decode(text, i)
        except ValueError:
            i += 1
            continue
        out.append(obj)
        i = end
    return out


def parse_calls(message):
    """[(name, arguments)] from a chat message: structured tool_calls if present, else JSON in the text."""
    calls = []
    for c in message.get("tool_calls") or []:
        f = c.get("function") or {}
        calls.append((f.get("name"), f.get("arguments")))
    if calls:
        return calls
    for obj in json_objects(message.get("content") or ""):
        if isinstance(obj, dict) and isinstance(obj.get("name"), str):
            calls.append((obj["name"], obj.get("arguments", obj.get("parameters", {}))))
    return calls


def validate(name, args, readonly):
    """An error message for the model, or None. Strings holding JSON are accepted as arguments."""
    if name not in TOOLS or (readonly and name in WRITERS):
        return f"unknown tool {name!r}; available: {', '.join(n for n in TOOLS if not (readonly and n in WRITERS))}"
    if not isinstance(args, dict):
        return "arguments must be a JSON object"
    _, props, required = TOOLS[name]
    missing = [k for k in required if k not in args]
    if missing:
        return f"missing argument(s): {', '.join(missing)}"
    for k, v in args.items():
        if k not in props:
            return f"unknown argument {k!r}; allowed: {', '.join(props)}"
        if not isinstance(v, props[k]) or isinstance(v, bool):
            return f"argument {k!r} must be {JSON_TYPE[props[k]]}"
    return None


def resolve(root, rel):
    """An absolute path inside the workspace, else Denied. Symlinks are resolved first, so they cannot lead out."""
    if not isinstance(rel, str) or not rel or "\0" in rel:
        raise Denied("path must be a non-empty string")
    p = os.path.realpath(os.path.join(root, rel))
    if os.path.commonpath([root, p]) != root:
        raise Denied("path is outside the workspace")
    if ".git" in Path(p).relative_to(root).parts:
        raise Denied(".git is not accessible")
    return p


class Agent:
    def __init__(self, root, mcp, readonly):
        self.root, self.mcp, self.readonly, self.writes = root, mcp, readonly, 0
        self.finished, self.pushbacks = False, MAX_PUSHBACKS

    def run(self, name, a):
        """(ok, text) for one validated call."""
        try:
            return getattr(self, "t_" + name)(**a)
        except Denied as e:
            return False, f"denied: {e}"
        except OSError as e:
            return False, f"error: {e.strerror or e}"

    def t_list_files(self, path="."):
        d = resolve(self.root, path)
        if not os.path.isdir(d):
            return False, "not a directory"
        names = sorted(n + ("/" if os.path.isdir(os.path.join(d, n)) else "") for n in os.listdir(d) if n != ".git")
        more = f"\n... {len(names) - MAX_LIST} more" if len(names) > MAX_LIST else ""
        return True, "\n".join(names[:MAX_LIST]) + more

    def t_read_file(self, path, start_line=1, max_lines=200):
        p = resolve(self.root, path)
        if not os.path.isfile(p):
            return False, "not a file"
        raw = Path(p).read_bytes()
        if b"\0" in raw[:4096]:
            return False, "binary file"
        lines = raw.decode(errors="replace").splitlines()
        a, n = max(1, start_line), max(1, min(max_lines, 400))
        out = "\n".join(f"{i}: {l}" for i, l in enumerate(lines[a - 1:a - 1 + n], a))
        if len(out) > MAX_READ_CHARS:
            out = out[:MAX_READ_CHARS] + "\n... truncated; read with start_line to continue"
        return True, out or "(empty)"

    def _write(self, p, text):
        if len(text.encode()) > MAX_WRITE_BYTES:
            return False, f"file too large (max {MAX_WRITE_BYTES} bytes)"
        if self.writes >= MAX_WRITES:
            return False, f"write limit reached ({MAX_WRITES})"
        os.makedirs(os.path.dirname(p), exist_ok=True)
        Path(p).write_text(text)
        self.writes += 1
        return True, f"wrote {len(text)} characters"

    def t_write_file(self, path, content):
        return self._write(resolve(self.root, path), content)

    def t_replace_in_file(self, path, old, new):
        p = resolve(self.root, path)
        if not os.path.isfile(p):
            return False, "not a file"
        text = Path(p).read_text()
        if text.count(old) != 1:
            return False, f"old text must occur exactly once (found {text.count(old)})"
        return self._write(p, text.replace(old, new))

    def _mcp(self, tool, args):
        r = self.mcp.call(tool, args)
        return not r.get("isError"), "\n".join(c.get("text", "") for c in r.get("content", []))

    def t_run_check(self, name):
        return self._mcp("run_check", {"name": name})

    def t_delegate(self, title, spec, scope):
        return self._mcp("delegate", {"title": title, "spec": spec, "scope": scope})

    def t_ask_user(self, question):
        if self.pushbacks:  # small models ask for permission they do not need; the task text is the decision
            self.pushbacks -= 1
            return False, ("Do not ask for confirmation: the task description is the decision, so do the work. "
                           "If you are truly blocked after trying, ask again with a specific blocking question.")
        ok, text = self._mcp("ask_user", {"question": question})
        self.finished = ok
        return ok, text

    def t_report_result(self, status, summary):
        ok, text = self._mcp("report_result", {"status": status, "summary": summary})
        self.finished = ok
        return ok, text


def chat(url, model, messages, tools, timeout=300, options=None):
    # num_predict bounds one turn: a model that loops on its own output must not run until the request times out.
    opts = {"temperature": 0, "num_ctx": 8192, "num_predict": 1024, **(options or {})}
    req = urllib.request.Request(
        url.rstrip("/") + "/api/chat", method="POST", headers={"Content-Type": "application/json"},
        data=json.dumps({"model": model, "stream": False, "messages": messages, "tools": tools, "options": opts}).encode())
    # No proxies: an http_proxy in the environment must not carry the task off the machine.
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=timeout) as r:
        return json.load(r)


def shrink(messages):
    """Keep the system prompt, the task and the recent turns; blank older tool output once the conversation is big."""
    if sum(len(m.get("content") or "") for m in messages) <= CONTEXT_CHARS:
        return
    for m in messages[2:-KEEP_RECENT]:
        if m["role"] == "tool" and m["content"] != "[older output omitted]":
            m["content"] = "[older output omitted]"


def loop(prompt, agent, url, model, max_turns, readonly, ask=chat, options=None):
    tools = schemas(readonly)
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}]
    used = {"input": 0, "output": 0, "turns": 0}
    invalid = no_tool = repeats = 0
    last = None

    def stop(why):
        emit(type="usage", **used)
        agent.run("report_result", {"status": "failed", "summary": f"local agent stopped: {why}"})
        emit(type="stopped", reason=why)

    for turn in range(1, max_turns + 1):
        shrink(messages)
        reply = ask(url, model, messages, tools, options=options)
        msg = reply.get("message") or {}
        used["input"] += reply.get("prompt_eval_count", 0)
        used["output"] += reply.get("eval_count", 0)
        used["turns"] = turn
        calls = parse_calls(msg)
        emit(type="turn", n=turn, calls=[c[0] for c in calls], input=reply.get("prompt_eval_count"), output=reply.get("eval_count"),
             cut=reply.get("done_reason") == "length")
        messages.append({"role": "assistant", "content": msg.get("content") or (json.dumps({"name": calls[0][0], "arguments": calls[0][1]}) if calls else "")})
        if not calls:
            no_tool += 1
            if no_tool >= MAX_NO_TOOL:
                return stop("the model stopped calling tools")
            messages.append({"role": "user", "content": 'Reply with one tool call as JSON {"name": ..., "arguments": {...}}.'})
            continue
        no_tool = 0
        name, args = calls[0]
        if isinstance(args, str):  # some models send the arguments as a JSON string
            try:
                args = json.loads(args)
            except ValueError:
                pass
        err = validate(name, args, readonly)
        if err:
            invalid += 1
            ok, text = False, f"invalid call: {err}"
            emit(type="invalid", n=turn, reason=err)
            if invalid >= MAX_INVALID:
                return stop(f"too many invalid tool calls ({MAX_INVALID})")
        else:
            repeats = repeats + 1 if (name, json.dumps(args, sort_keys=True)) == last else 1
            last = (name, json.dumps(args, sort_keys=True))
            if repeats > MAX_REPEAT:
                return stop(f"the same call was repeated {MAX_REPEAT} times")
            ok, text = agent.run(name, args)
            emit(type="tool", n=turn, tool=name, ok=ok)
        if len(calls) > 1:
            text += "\n(Only the first tool call was run. Send one tool call per message.)"
        if agent.finished:
            return emit(type="usage", **used)
        messages.append({"role": "tool", "content": (text or "(no output)")[:MAX_READ_CHARS]})
    stop(f"turn limit reached ({max_turns})")


def main(prompt):
    url = os.environ.get("AXON_LOCAL_URL", "http://127.0.0.1:11434")
    host = urllib.parse.urlparse(url).hostname
    mcp = Mcp(json.loads(os.environ["AXON_MCP"]))
    agent = Agent(os.path.realpath(os.getcwd()), mcp, os.environ.get("AXON_LOCAL_READONLY") == "1")
    emit(type="start", model=os.environ.get("AXON_LOCAL_MODEL"))
    if host not in ("127.0.0.1", "localhost", "::1"):  # local-only: never fail over to a remote endpoint
        agent.run("report_result", {"status": "failed", "summary": f"local model url must be loopback, got {url}"})
        return
    try:
        options = {"num_predict": int(os.environ.get("AXON_LOCAL_MAX_TOKENS", "1024"))}
        if int(os.environ.get("AXON_LOCAL_NUM_GPU", "0")):
            options["num_gpu"] = int(os.environ["AXON_LOCAL_NUM_GPU"])
        loop(prompt, agent, url, os.environ["AXON_LOCAL_MODEL"], int(os.environ.get("AXON_LOCAL_MAX_TURNS", "20")),
             agent.readonly, options=options)
    except OSError as e:  # the model server is down or too slow: a clean failure, not a crash that gets retried
        agent.run("report_result", {"status": "failed", "summary": f"local model unreachable: {e}"})


if __name__ == "__main__":
    main(sys.argv[1])
