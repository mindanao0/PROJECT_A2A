"""Lets the GUI (navis.server) drive the real runtime.

Same two methods as the simulated navis.core.Runtime: snapshot(cursor) and command(payload).
"""

import hashlib
import json
import subprocess
import time

from . import runtime
from .core import ControlError, clean_text, normalize_scope

ACTIVE = ("RUNNING", "WAITING_INPUT", "WAITING_APPROVAL", "REVIEW")
DONE = ("COMPLETED", "FAILED", "CANCELLED")
LOGIN_FILE = {"codex": "auth.json", "claude": ".credentials.json"}
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

    def agents(self, busy):
        slots, out = self.rt.cfg["slots"], []
        for name, desc in (("fake", "Scripted test agent · sandboxed, no quota"),
                           ("codex", "Codex CLI · adapter not yet verified"),
                           ("claude", "Claude Code CLI · adapter not yet verified")):
            login = LOGIN_FILE.get(name)
            ok = not login or (runtime.data_dir() / "agents" / name / login).exists()
            n = busy.get(name, 0)
            out.append({"name": name, "desc": desc, "ok": ok,
                        "status": "Not logged in" if not ok else "Busy" if n else "Ready",
                        "sub": f"{n} / {slots.get(name, 1)} slots" if ok else f"login: see Runtime settings"})
        return out

    def diff(self, project, base, head):
        key = (project, base, head)
        if key not in self.diffs:
            r = subprocess.run(["git", "-C", runtime.load_project(project)["path"], "diff", "--stat",
                                "--no-ext-diff", base, head], capture_output=True, text=True)
            self.diffs[key] = r.stdout.strip() or "(no changes)"
        return self.diffs[key]

    def snapshot(self, cursor=0):
        s = self.store
        latest = {}
        attempts = {}
        for a in s.q("select * from attempts order by started"):
            attempts.setdefault(a["task"], []).append(a)
            latest[a["task"]] = a["id"]
        evs = s.q("select * from events where task is not null and kind in ('check', 'prepare') order by id")
        tasks, busy = [], {}
        for t in s.q("select * from tasks order by id"):
            tid, state = t["id"], t["status"]
            if state == "RUNNING":
                busy[t["agent"]] = busy.get(t["agent"], 0) + 1
                if t["cancel"]:
                    state = "CANCELLING"
            aid = latest.get(tid)
            arts = []
            for e in evs:
                if e["task"] == tid:
                    d = json.loads(e["data"])
                    body = f"exit {d['rc']}\n{d.get('tail', '')}"
                    arts.append({"id": f"ev{e['id']}", "kind": "verification", "name": f"{e['kind']} {d['name']}",
                                 "content": body, "attempt_id": e["attempt"], "exit_code": d["rc"],
                                 "hash": hashlib.sha256(body.encode()).hexdigest(), "simulated": False})
            if t["head"] and t["head"] != t["base"]:
                arts.append({"id": f"diff{tid}", "kind": "result", "name": "Changes (git diff --stat)", "attempt_id": aid,
                             "content": self.diff(t["project"], t["base"], t["head"]), "hash": t["head"], "simulated": False})
            pending = None
            if state in ("WAITING_INPUT", "WAITING_APPROVAL", "REVIEW"):
                pending = {"id": f"{tid}:{aid}:{state}", "message": t["note"] or state, "attempt_id": aid,
                           "expires": t["updated"] + 86400, "payload_hash": ""}
            tasks.append({
                "id": str(tid), "project_id": t["project"], "title": t["title"] or t["spec"][:80], "spec": t["spec"],
                "scope": json.loads(t["scope"]), "scenario": "real", "state": state, "backend": t["agent"],
                "attempt_id": aid, "pending": pending, "artifacts": arts, "activity": t["note"] or state.replace("_", " ").title(),
                "attempts": [{"id": a["id"], "started_at": a["started"], "ended_at": a["ended"], "backend": t["agent"],
                              "state": (a["outcome"] or "RUNNING") if a["status"] != "running" else "RUNNING"}
                             for a in attempts.get(tid, [])],
                "instructions": [{"version": i + 1, "text": json.loads(e["data"])["text"], "time": e["at"]}
                                 for i, e in enumerate(s.q("select * from events where task = ? and kind = 'instruction' order by id", tid))],
                "created_at": t["created"], "updated_at": t["updated"], "head": t["head"],
            })
        ids = {str(r["id"]): r["project"] for r in s.q("select id, project from tasks")}
        rows = s.q("select * from events where id > ? order by id limit 300", cursor)
        events = [{"schema_version": 1, "seq": r["id"], "type": KINDS.get(r["kind"], r["kind"].upper()),
                   "task_id": str(r["task"]) if r["task"] else None, "project_id": ids.get(str(r["task"])),
                   "attempt_id": r["attempt"], "time": r["at"], "producer": "runtime",
                   "message": message(r["kind"], json.loads(r["data"]))} for r in rows]
        last = s.one("select coalesce(max(id), 0) m from events")["m"]
        slots = self.rt.cfg["slots"]
        return {"schema_version": 1, "mode": "real", "paused": runtime.is_paused(s), "projects": self.projects(),
                "tasks": tasks, "events": events, "cursor": rows[-1]["id"] if rows else cursor, "latest_cursor": last,
                "agents": self.agents(busy), "slot_total": sum(slots.get(a, 1) for a in ("fake", "codex", "claude")),
                "capabilities": {"fake": "scripted, sandboxed", "codex": "unverified", "claude": "unverified", "local": "not connected"},
                "settings": [["Mode", "Real runtime · each attempt runs in bwrap + cgroup"],
                             ["State", str(runtime.data_dir())], ["Projects", str(runtime.config_dir() / "projects")],
                             ["Slots", ", ".join(f"{k} {v}" for k, v in slots.items())],
                             ["Agent logins", f"CODEX_HOME / CLAUDE_CONFIG_DIR under {runtime.data_dir() / 'agents'}"],
                             ["Transport", "Authenticated HTTP · 127.0.0.1 only"], ["Remote listener", "Disabled"],
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
        base = p.get("base") or "HEAD"
        if not isinstance(base, str) or base.startswith("-") or len(base) > 200:
            raise ControlError("Invalid base")
        try:
            tid, dup = runtime.add_task(self.store, project, p.get("agent") or "fake",
                                        clean_text(p.get("spec"), "Task description"), normalize_scope(p.get("scope")),
                                        base, clean_text(p.get("title"), "Title", 120))
        except (ValueError, subprocess.CalledProcessError) as e:
            raise ControlError(f"Cannot queue task: {e}"[:300])
        return {"task_id": str(dup or tid), "duplicate": bool(dup)}
