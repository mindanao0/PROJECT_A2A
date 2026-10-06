"""Lets the GUI (navis.server) drive the real runtime.

Same two methods as the simulated navis.core.Runtime: snapshot(cursor) and command(payload).
"""

import hashlib
import json
import subprocess
import time
from pathlib import Path

from . import runtime, sandbox
from .core import ControlError, clean_text, normalize_scope

ACTIVE = ("RUNNING", "WAITING_INPUT", "WAITING_APPROVAL", "REVIEW")
DONE = ("COMPLETED", "FAILED", "CANCELLED")
LOGIN_FILE = {"codex": "auth.json", "claude": ".credentials.json"}
MAX_DIFF, MAX_LOG = 200_000, 30_000
KINDS = {"status": "STATE", "attempt": "ATTEMPT", "tool": "TOOL", "check": "CHECK", "prepare": "PREPARE",
         "outcome": "OUTCOME", "error": "ERROR", "control": "CONTROL", "instruction": "INSTRUCTION",
         "leak": "LEAK", "stale-result-dropped": "STALE"}


def message(kind, d):
    if kind == "status":
        return f"{d['status']}: {d.get('note') or ''}".rstrip(": ")
    return {"attempt": lambda: f"Attempt {d.get('n')} started on {d.get('agent')} from {str(d.get('base'))[:10]}",
            "tool": lambda: f"Agent called {d.get('tool')}",
            "check": lambda: f"Check {d.get('name')}: exit {d.get('rc')}",
            "prepare": lambda: f"Prepare {d.get('name')}: exit {d.get('rc')}",
            "outcome": lambda: f"Attempt outcome: {d.get('outcome')}",
            "error": lambda: f"Runtime error: {d.get('error')}",
            "control": lambda: "Dispatch paused; running attempts continue" if d.get("paused") else "Dispatch resumed",
            "instruction": lambda: "Instruction saved for the next attempt",
            "leak": lambda: "Agent credential found in a diff; result blocked",
            "stale-result-dropped": lambda: "Late result from a revoked attempt was dropped",
            }.get(kind, lambda: kind)()


class Bridge:
    def __init__(self, store=None):
        self.rt = runtime.Runtime(store)
        self.store = self.rt.store
        self.rt.start()
        self.diffs = {}

    def close(self):
        self.rt.shutdown()

    def tick(self):
        self.rt.tick()

    # Reading

    def projects(self):
        out = []
        for f in sorted((runtime.config_dir() / "projects").glob("*.toml")):
            try:
                p = runtime.load_project(f.stem)
            except Exception as e:  # a broken config must not hide the other projects
                out.append({"id": f.stem, "name": f.stem, "path": "invalid", "description": f"Config error: {e}"[:200]})
                continue
            out.append({"id": f.stem, "name": f.stem, "path": p["path"],
                        "description": f"{len(p['checks'])} check(s) · protected: {', '.join(p['protected']) or 'none'}"})
        return out

    def agents(self, busy, cool):
        slots, out = self.rt.cfg["slots"], []
        for name, desc in (("fake", "Scripted test agent · sandboxed, no quota"),
                           ("codex", "Codex CLI · adapter not yet verified"),
                           ("claude", "Claude Code CLI · adapter not yet verified")):
            login = LOGIN_FILE.get(name)
            ok = not login or (runtime.data_dir() / "agents" / name / login).exists()
            n = busy.get(name, 0)
            out.append({"name": name, "desc": desc, "ok": ok,
                        "until": cool.get(name) if cool.get(name, 0) > time.time() else None,
                        "status": "Not logged in" if not ok else "Busy" if n else "Ready",
                        "sub": f"{n} / {slots.get(name, 1)} slots" if ok else f"login: see Runtime settings"})
        return out

    def diff(self, t, proj):
        """Full patch plus per-file scope/protected classification, cached per commit pair."""
        key = (t["project"], t["base"], t["head"], t["scope"])
        if key not in self.diffs:
            git = ["git", "-C", proj["path"]]
            patch = subprocess.run([*git, "diff", "--no-ext-diff", "--no-textconv", "--no-color", t["base"], t["head"]],
                                   capture_output=True, text=True, errors="replace").stdout
            if len(patch) > MAX_DIFF:
                patch = patch[:MAX_DIFF] + f"\n… patch truncated at {MAX_DIFF} characters; use git diff for the rest\n"
            scope = json.loads(t["scope"])
            files = [{"path": f, "out_of_scope": not any(runtime.under(f, sc) for sc in scope),
                      "protected": any(runtime.under(f, p) for p in proj["protected"])}
                     for f in sandbox.changed_files(proj["path"], t["base"], t["head"])]
            self.diffs[key] = (patch or "(no changes)", files)
        return self.diffs[key]

    def read(self, aid, name, limit):
        try:
            data = (runtime.data_dir() / "attempts" / aid / name).read_bytes()[-limit:]
        except OSError:
            return None
        return self.rt.redact(data.decode(errors="replace"))

    def artifact(self, aid, kind, name, content):
        return {"id": f"{kind}{aid}", "kind": kind, "name": name, "attempt_id": aid, "content": content,
                "hash": hashlib.sha256(content.encode()).hexdigest(), "simulated": False}

    def snapshot(self, cursor=0):
        s, now = self.store, time.time()
        slots = self.rt.cfg["slots"]
        rows = list(s.q("select * from tasks order by id"))
        paused = runtime.is_paused(s)
        cool = {r["agent"]: r["until"] for r in s.q("select * from cooldowns")}
        running = [t for t in rows if t["status"] == "RUNNING"]
        busy = {}
        for t in running:
            busy[t["agent"]] = busy.get(t["agent"], 0) + 1
        attempts, latest = {}, {}
        for a in s.q("select * from attempts order by started"):
            attempts.setdefault(a["task"], []).append(a)
            latest[a["task"]] = a["id"]
        evidence = {}
        for e in s.q("select * from events where task is not null and kind in ('check', 'prepare') order by id"):
            evidence.setdefault(e["task"], []).append(e)
        instr = {}
        for e in s.q("select * from events where task is not null and kind = 'instruction' order by id"):
            instr.setdefault(e["task"], []).append(e)
        projects, tasks = {}, []
        for t in rows:
            tid, state, aid = t["id"], t["status"], latest.get(t["id"])
            if state == "RUNNING" and t["cancel"]:
                state = "CANCELLING"
            arts = []
            for e in evidence.get(tid, []):
                d = json.loads(e["data"])
                body = f"exit {d['rc']}\n{d.get('tail', '')}"
                arts.append(self.artifact(e["attempt"], "verification", f"{e['kind']} {d['name']}", body) | {"id": f"ev{e['id']}", "exit_code": d["rc"]})
            if t["head"] and t["head"] != t["base"]:
                if t["project"] not in projects:
                    projects[t["project"]] = runtime.load_project(t["project"])
                patch, files = self.diff(t, projects[t["project"]])
                arts.append(self.artifact(aid, "diff", "Code diff", patch) | {"hash": t["head"], "files": files})
            if aid:
                for kind, name, label, limit in (("agent_log", "agent.log", "Agent output", MAX_LOG), ("prompt", "prompt.txt", "Prompt sent", 20_000)):
                    text = self.read(aid, name, limit)
                    if text is not None:
                        arts.append(self.artifact(aid, kind, f"{label} / attempt {aid}", text))
            reasons = []
            if state == "QUEUED":
                if paused:
                    reasons.append({"code": "paused", "message": "Dispatch is paused"})
                if cool.get(t["agent"], 0) > now:
                    reasons.append({"code": "cooldown", "until": cool[t["agent"]], "message": f"{t['agent']} is cooling down after a quota limit"})
                mine = json.loads(t["scope"])
                for o in running:
                    if o["project"] == t["project"] and runtime.overlaps(mine, json.loads(o["scope"])):
                        reasons.append({"code": "scope", "task_id": str(o["id"]), "message": f"Scope held by {o['title'] or 'task ' + str(o['id'])}"})
                if busy.get(t["agent"], 0) >= slots.get(t["agent"], 1):
                    reasons.append({"code": "slot", "message": f"{t['agent']} slots full ({busy[t['agent']]}/{slots.get(t['agent'], 1)})"})
                if not reasons:
                    reasons.append({"code": "ready", "message": "Ready for the next dispatch tick"})
            elif state == "WAITING_QUOTA":
                reasons.append({"code": "cooldown", "until": cool.get(t["agent"], t["updated"]), "message": f"{t['agent']} quota cooldown"})
            pending = None
            if state in ("WAITING_INPUT", "WAITING_APPROVAL", "REVIEW"):
                pending = {"id": f"{tid}:{aid}:{state}", "message": t["note"] or state, "attempt_id": aid,
                           "expires": t["updated"] + 86400, "payload_hash": ""}
            tasks.append({
                "id": str(tid), "project_id": t["project"], "title": t["title"] or t["spec"][:80], "spec": t["spec"],
                "scope": json.loads(t["scope"]), "scenario": "real", "state": state, "backend": t["agent"],
                "attempt_id": aid, "pending": pending, "artifacts": arts, "queue_reasons": reasons,
                "due": cool.get(t["agent"], t["updated"]) if state == "WAITING_QUOTA" else None,
                "activity": t["note"] or state.replace("_", " ").title(), "head": t["head"],
                "result_ref": f"refs/navis/attempts/{aid}" if state == "COMPLETED" and t["head"] and aid else None,
                "source": json.loads(t["source"]) if t["source"] else None,
                "attempts": [{"id": a["id"], "started_at": a["started"], "ended_at": a["ended"], "backend": t["agent"],
                              "state": (a["outcome"] or "RUNNING") if a["status"] != "running" else "RUNNING"}
                             for a in attempts.get(tid, [])],
                "instructions": [{"version": i + 1, "text": json.loads(e["data"])["text"], "time": e["at"]}
                                 for i, e in enumerate(instr.get(tid, []))],
                "created_at": t["created"], "updated_at": t["updated"],
            })
        proj_of = {str(t["id"]): t["project"] for t in rows}
        evs = list(s.q("select * from events where id > ? order by id limit 300", cursor))
        events = []
        for r in evs:
            d = json.loads(r["data"])
            events.append({"schema_version": 1, "seq": r["id"], "type": KINDS.get(r["kind"], r["kind"].upper()),
                           "task_id": str(r["task"]) if r["task"] else None, "project_id": proj_of.get(str(r["task"])),
                           "attempt_id": r["attempt"], "time": r["at"], "producer": "runtime",
                           "message": message(r["kind"], d), **({"output": d["tail"]} if "tail" in d else {})})
        last = s.one("select coalesce(max(id), 0) m from events")["m"]
        names = ("fake", "codex", "claude")
        return {"schema_version": 1, "mode": "real", "paused": paused, "projects": self.projects(),
                "tasks": tasks, "events": events, "cursor": evs[-1]["id"] if evs else cursor, "latest_cursor": last,
                "agents": self.agents(busy, cool),
                "resources": {"slots": [{"backend": n, "used": busy.get(n, 0), "limit": slots.get(n, 1)} for n in names],
                              "memory_available": False, "mode": "real"},
                "capabilities": {"fake": "scripted, sandboxed", "codex": "unverified", "claude": "unverified", "local": "not connected"},
                "settings": [["Mode", "Real runtime / each attempt runs in bwrap + cgroup"],
                             ["State", str(runtime.data_dir())], ["Projects", str(runtime.config_dir() / "projects")],
                             ["Slots", ", ".join(f"{k} {v}" for k, v in slots.items())],
                             ["Agent logins", f"CODEX_HOME / CLAUDE_CONFIG_DIR under {runtime.data_dir() / 'agents'}"],
                             ["Transport", "Authenticated HTTP / 127.0.0.1 only"], ["Remote listener", "Disabled"],
                             ["Push / merge / deploy", "No runtime endpoints; results land in refs/navis/attempts/*"]]}

    # Commands

    def command(self, p):
        if not isinstance(p, dict) or not isinstance(p.get("action"), str):
            raise ControlError("Command must be an object with a text action")
        action, s = p["action"], self.store
        if action in ("pause", "resume"):
            runtime.set_paused(s, action == "pause")
            return {"ok": True}
        if action == "create_project":
            raise ControlError("Projects are TOML files in ~/.config/navis/projects/")
        if action == "create_task":
            return self.create_task(p)
        try:
            tid = int(p.get("task_id"))
        except (TypeError, ValueError):
            raise ControlError("Task not found")
        t = s.one("select * from tasks where id = ?", tid)
        if not t:
            raise ControlError("Task not found")
        last = s.one("select id from attempts where task = ? order by started desc limit 1", tid)
        aid = last["id"] if last else None
        if p.get("attempt_id") != aid:
            raise ControlError("Attempt changed. Refresh before controlling this task.")
        st = t["status"]
        ok = False
        if action in ("stop", "kill"):
            if st in DONE:
                raise ControlError("This task is already inactive")
            if action == "kill" and st != "RUNNING":
                raise ControlError("No running attempt")
            runtime.stop_task(s, tid)
            ok = True
        elif action == "retry":
            ok = runtime.retry(s, tid) if st in ("FAILED", "CANCELLED") else False
        elif action == "instruction":
            ok = runtime.instruct(s, tid, clean_text(p.get("text"), "Instruction", 2000))
        elif action in ("approve", "reject", "answer"):
            if p.get("pending_id") != f"{tid}:{aid}:{st}":
                raise ControlError("Request changed or has already been resolved")
            if action == "answer":
                ok = st == "WAITING_INPUT" and runtime.answer(s, tid, clean_text(p.get("text"), "Answer", 2000))
            elif st in ("WAITING_APPROVAL", "REVIEW"):
                ok = (runtime.approve if action == "approve" else runtime.reject)(s, tid)
        else:
            raise ControlError("Unknown command")
        if not ok:
            raise ControlError(f"{action} is not possible while the task is {st}")
        return {"ok": True}

    def create_task(self, p):
        project = p.get("project_id")
        if project not in {x["id"] for x in self.projects()}:
            raise ControlError("Unknown project")
        base, source = p.get("base") or "HEAD", None
        if p.get("source_task_id"):
            old = self.store.one("select * from tasks where id = ?", str(p["source_task_id"]).strip() if str(p["source_task_id"]).isdigit() else -1)
            last = old and self.store.one("select id from attempts where task = ? order by started desc limit 1", old["id"])
            if not old or old["project"] != project or old["status"] != "COMPLETED" or not old["head"]:
                raise ControlError("Source must be a completed task in the same project")
            if not last or p.get("source_attempt_id") != last["id"]:
                raise ControlError("Source attempt changed. Select the source again.")
            base = old["head"]
            source = {"task_id": str(old["id"]), "attempt_id": last["id"], "title": old["title"] or old["spec"][:80],
                      "artifacts": [{"name": "result commit", "hash": old["head"]}]}
        if not isinstance(base, str) or base.startswith("-") or len(base) > 200:
            raise ControlError("Invalid base")
        try:
            tid, dup = runtime.add_task(self.store, project, p.get("agent") or "fake",
                                        clean_text(p.get("spec"), "Task description"), normalize_scope(p.get("scope")),
                                        base, clean_text(p.get("title"), "Title", 120), source)
        except (ValueError, subprocess.CalledProcessError) as e:
            raise ControlError(f"Cannot queue task: {e}"[:300])
        return {"task_id": str(dup or tid), "duplicate": bool(dup)}
