"""UI-independent, durable control model for simulated attempts only.

No command, provider, repository edit, or model inference is executed here.
This is a GUI contract fixture, not the production sandbox/Agent Runner.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
import uuid
from pathlib import PurePosixPath

TERMINAL = {"COMPLETED", "FAILED", "CANCELLED"}
ACTIVE = {"RUNNING", "WAITING_INPUT", "WAITING_APPROVAL", "REVIEW", "VERIFY", "CANCELLING"}
SCENARIOS = {"success", "input", "approval", "quota", "failure", "hang", "verify_failure"}


class ControlError(ValueError):
    pass


def identifier(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def clean_text(value, name, limit=4000):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ControlError(f"{name} must be non-empty text (up to {limit} characters)")
    return value.strip()


def normalize_scope(value):
    value = clean_text(value, "Scope", 500)
    scopes = []
    for item in value.split(","):
        item = item.strip().removesuffix("/")
        path = PurePosixPath(item)
        if not item or path.is_absolute() or ".." in path.parts or "\\" in item:
            raise ControlError("Use relative path prefixes, separated by commas; no '..'")
        scopes.append(str(path))
    return sorted(set(scopes))


def overlap(left, right):
    return any(a == "." or b == "." or a == b or a.startswith(b + "/") or b.startswith(a + "/")
               for a in left for b in right)


class Runtime:
    def __init__(self, database, clock=time.time):
        self.clock = clock
        self.lock = threading.RLock()
        self.db = sqlite3.connect(database, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK(id=1), body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY AUTOINCREMENT, body TEXT NOT NULL);
        """)
        row = self.db.execute("SELECT body FROM state WHERE id=1").fetchone()
        self.state = json.loads(row[0]) if row else {
            "projects": [{"id": "project-vela", "name": "PROJECT_VELA", "path": "Not connected", "description": "First planned project · simulation only"}],
            "tasks": [], "paused": False, "mode": "simulation", "schema_version": 1,
        }
        with self.lock, self.db:
            if row:
                # Never resume or replay an old attempt's actions on restart.
                for task in self.state["tasks"]:
                    if task["state"] in ACTIVE or task["state"] == "WAITING_QUOTA":
                        task["pending"] = None
                        self.transition(task, "BLOCKED", "Runtime restarted. Previous attempt revoked; retry explicitly.")
                        self.event("RECOVERY", task, task["activity"])
            self.save()

    def close(self):
        with self.lock:
            self.db.close()

    def save(self):
        self.db.execute("INSERT OR REPLACE INTO state VALUES (1, ?)", (json.dumps(self.state),))

    def event(self, kind, task, message):
        event = {"schema_version": 1, "event_id": identifier("evt"), "type": kind,
                 "project_id": task.get("project_id") if task else None,
                 "task_id": task.get("id") if task else None,
                 "attempt_id": task.get("attempt_id") if task else None,
                 "time": self.clock(), "message": message, "producer": "runtime.simulation"}
        self.db.execute("INSERT INTO events(body) VALUES (?)", (json.dumps(event),))

    def snapshot(self, cursor=0):
        with self.lock:
            last = self.db.execute("SELECT COALESCE(MAX(seq),0) FROM events").fetchone()[0]
            rows = self.db.execute("SELECT seq,body FROM events WHERE seq>? ORDER BY seq LIMIT 300", (cursor,)).fetchall()
            result = json.loads(json.dumps(self.state))
            active = [t for t in result["tasks"] if t["state"] in ACTIVE]
            for task in result["tasks"]:
                reasons = []
                if task["state"] == "QUEUED":
                    if result["paused"]:
                        reasons.append({"code": "paused", "message": "Dispatch is paused"})
                    conflicts = [t for t in active if t["project_id"] == task["project_id"] and overlap(t["scope"], task["scope"])]
                    for other in conflicts:
                        reasons.append({"code": "scope", "task_id": other["id"], "message": f"Scope held by {other['title']}"})
                    if active:
                        reasons.append({"code": "slot", "message": "Fake-agent slot occupied (1/1)"})
                    if not reasons:
                        reasons.append({"code": "ready", "message": "Ready for the next dispatch tick"})
                elif task["state"] == "WAITING_QUOTA":
                    reasons.append({"code": "cooldown", "until": task["due"], "message": "Simulated cooldown"})
                task["queue_reasons"] = reasons
            result["resources"] = {"slots": [{"backend": "fake-agent", "used": len(active), "limit": 1}],
                                   "memory_available": False, "mode": "simulation"}
            # Keep the polling response small. Artifact bodies and full event output are
            # fetched only for the task the user opens in the detail dialog.
            for task in result["tasks"]:
                for artifact in task.get("artifacts", []):
                    artifact.pop("content", None)
                if task.get("source"):
                    for artifact in task["source"].get("artifacts", []):
                        artifact.pop("content", None)
            event_rows = []
            for seq, body in rows:
                event = dict(json.loads(body), seq=seq)
                event.pop("output", None)
                event_rows.append(event)
            result.update(events=event_rows,
                          cursor=rows[-1][0] if rows else cursor, latest_cursor=last,
                          capabilities={"fake": "simulated", "codex": "not tested", "claude": "not tested", "local": "not connected"})
            return result

    def task_detail(self, task_id):
        """Return full evidence for one task, separately from the lightweight poll."""
        with self.lock:
            task = json.loads(json.dumps(self.task(task_id)))
            summary = next(t for t in self.snapshot()["tasks"] if t["id"] == task_id)
            task["queue_reasons"] = summary.get("queue_reasons", [])
            rows = self.db.execute("SELECT seq,body FROM events ORDER BY seq").fetchall()
            events = [dict(json.loads(body), seq=seq) for seq, body in rows
                      if json.loads(body).get("task_id") == task_id]
            return {"task": task, "events": events}

    def task(self, task_id):
        for task in self.state["tasks"]:
            if task["id"] == task_id:
                return task
        raise ControlError("Task not found")

    def transition(self, task, state, activity):
        task.update(state=state, activity=activity, updated_at=self.clock())
        if task.get("attempt_id"):
            for attempt in task["attempts"]:
                if attempt["id"] == task["attempt_id"]:
                    attempt["state"] = state
                    if state in TERMINAL or state in {"BLOCKED", "WAITING_QUOTA"}:
                        attempt["ended_at"] = self.clock()
        self.event("STATE", task, f"{state}: {activity}")

    def command(self, payload):
        if not isinstance(payload, dict):
            raise ControlError("Command must be an object")
        with self.lock:
            # Roll back both memory and database if command validation fails.
            previous = json.loads(json.dumps(self.state))
            try:
                with self.db:
                    result = self._command(payload)
                    self.save()
                return result
            except Exception:
                self.state = previous
                raise

    def _command(self, p):
        action = p.get("action")
        if not isinstance(action, str):
            raise ControlError("Action must be text")
        now = self.clock()
        if action in {"pause", "resume"}:
            self.state["paused"] = action == "pause"
            self.event("CONTROL", None, "Dispatch paused; active simulation continues" if action == "pause" else "Dispatch resumed")
            return {"ok": True}
        if action == "create_project":
            if len(self.state["projects"]) >= 20:
                raise ControlError("Project limit reached")
            project = {"id": identifier("project"), "name": clean_text(p.get("name"), "Name", 80),
                       "path": "Not connected", "description": "Simulation project · no repository access"}
            self.state["projects"].append(project)
            self.event("PROJECT", None, f"Project added: {project['name']}")
            return project
        if action == "create_task":
            project_id = p.get("project_id")
            if project_id not in {x["id"] for x in self.state["projects"]}:
                raise ControlError("Unknown project")
            title = clean_text(p.get("title"), "Title", 120)
            spec = clean_text(p.get("spec"), "Task description")
            scope = normalize_scope(p.get("scope"))
            scenario = p.get("scenario", "success")
            if not isinstance(scenario, str) or scenario not in SCENARIOS:
                raise ControlError("Unsupported scenario")
            source = None
            source_id = p.get("source_task_id")
            if source_id:
                old = self.task(source_id)
                if old["project_id"] != project_id or old["state"] != "COMPLETED":
                    raise ControlError("Source must be a completed task in the same project")
                if p.get("source_attempt_id") != old["attempt_id"]:
                    raise ControlError("Source attempt changed. Select the source again.")
                source = {"task_id": old["id"], "attempt_id": old["attempt_id"], "title": old["title"],
                          "artifacts": [dict(a) for a in old["artifacts"] if a["attempt_id"] == old["attempt_id"]]}
            key_data = [project_id, " ".join(spec.split()).casefold(), scope]
            if source:
                key_data.append([source["task_id"], source["attempt_id"], [a["hash"] for a in source["artifacts"]]])
            key = hashlib.sha256(json.dumps(key_data).encode()).hexdigest()
            for old in self.state["tasks"]:
                if old["key"] == key and old["state"] not in {"FAILED", "CANCELLED"}:
                    return {"task_id": old["id"], "duplicate": True}
            if len(self.state["tasks"]) >= 200:
                raise ControlError("Task limit reached (200)")
            task = {"id": identifier("task"), "project_id": project_id, "title": title, "spec": spec,
                    "scope": scope, "key": key, "scenario": scenario, "state": "QUEUED", "backend": "fake-agent",
                    "attempt_id": None, "attempts": [], "instructions": [], "artifacts": [], "pending": None,
                    "created_at": now, "updated_at": now, "activity": "Waiting for the simulated agent slot", "stage": 0,
                    "source": source}
            self.state["tasks"].append(task)
            self.event("TASK_CREATED", task, title)
            return {"task_id": task["id"], "duplicate": False}
        task = self.task(p.get("task_id"))
        # Every task control is bound to the attempt the UI observed.
        if p.get("attempt_id") != task["attempt_id"]:
            raise ControlError("Attempt changed. Refresh before controlling this task.")
        state = task["state"]
        if action == "stop":
            if state in TERMINAL or state == "BLOCKED":
                raise ControlError("This task is already inactive")
            task["pending"] = None
            if state in {"QUEUED", "WAITING_QUOTA"}:
                self.transition(task, "CANCELLED", "Cancelled before dispatch; no simulated worker active")
            else:
                task["due"] = now + 1
                self.transition(task, "CANCELLING", "Interrupt requested; waiting for simulation acknowledgement")
        elif action == "kill":
            if state not in ACTIVE:
                raise ControlError("No active simulated attempt")
            task["pending"] = None
            self.transition(task, "CANCELLED", "Simulated attempt revoked (no OS process was launched)")
        elif action == "retry":
            if state not in {"FAILED", "CANCELLED", "BLOCKED"}:
                raise ControlError("Retry requires an inactive task")
            task.update(stage=0, pending=None, attempt_id=None, gate_resolved=False)
            self.transition(task, "QUEUED", "Explicit retry queued; a new attempt will be created")
        elif action == "instruction":
            if state in TERMINAL or state in {"BLOCKED", "CANCELLING"}:
                raise ControlError("Task cannot accept an instruction now")
            text = clean_text(p.get("text"), "Instruction", 2000)
            task["instructions"].append({"version": len(task["instructions"]) + 1, "text": text, "time": now})
            self.event("INSTRUCTION", task, "Instruction version saved for the next simulated step")
        elif action in {"approve", "reject", "answer"}:
            pending = task.get("pending")
            if not pending or p.get("pending_id") != pending["id"]:
                raise ControlError("Request changed or has already been resolved")
            if now >= pending["expires"]:
                task["pending"] = None
                self.transition(task, "BLOCKED", "User request expired; retry explicitly")
                return {"ok": False, "expired": True}
            if action in {"approve", "reject"} and state != "WAITING_APPROVAL":
                raise ControlError("Task is not waiting for approval")
            if action == "answer" and state != "WAITING_INPUT":
                raise ControlError("Task is not waiting for input")
            if action == "answer":
                self.event("USER_INPUT", task, clean_text(p.get("text"), "Answer", 2000))
            task.update(pending=None, gate_resolved=True, due=now + 2)
            if action == "reject":
                self.transition(task, "BLOCKED", "Simulated action rejected; no side effect performed")
            else:
                self.transition(task, "RUNNING", "User response accepted for this simulated attempt")
        else:
            raise ControlError("Unknown command")
        return {"ok": True}

    def tick(self):
        with self.lock, self.db:
            now = self.clock()
            for task in self.state["tasks"]:
                state = task["state"]
                if state == "WAITING_QUOTA" and now >= task["due"]:
                    task["stage"] = 1
                    self.transition(task, "QUEUED", "Simulated cooldown ended; waiting for dispatch")
                elif state in {"WAITING_INPUT", "WAITING_APPROVAL"} and now >= task["pending"]["expires"]:
                    task["pending"] = None
                    self.transition(task, "BLOCKED", "User request expired; retry explicitly")
                elif state == "CANCELLING" and now >= task["due"]:
                    self.transition(task, "CANCELLED", "Simulation acknowledged interruption; attempt inactive")
                elif state in {"RUNNING", "VERIFY"} and now >= task["due"]:
                    self.advance(task, now)
            if not self.state["paused"]:
                active = [t for t in self.state["tasks"] if t["state"] in ACTIVE]
                # One fake slot; use scope guard explicitly so the contract extends to more slots.
                for task in self.state["tasks"]:
                    if task["state"] != "QUEUED":
                        continue
                    conflict = any(t["project_id"] == task["project_id"] and overlap(t["scope"], task["scope"]) for t in active)
                    if active or conflict:
                        task["activity"] = "Waiting for scope release" if conflict else "Waiting for fake-agent slot (1/1 busy)"
                        continue
                    task["attempt_id"] = identifier("attempt")
                    task["attempts"].append({"id": task["attempt_id"], "started_at": now, "backend": "fake-agent"})
                    task["due"] = now + 3
                    self.transition(task, "RUNNING", "Simulating a structured task; no workspace writes")
                    active.append(task)
            self.save()

    def advance(self, task, now):
        scenario = task["scenario"]
        if task["state"] == "VERIFY":
            passed = scenario != "verify_failure"
            evidence = {"id": identifier("artifact"), "kind": "verification", "name": "Simulation verification",
                        "content": f"Fake verifier: {'PASS' if passed else 'FAIL'}\nAttempt: {task['attempt_id']}\nNo coding tests were executed.",
                        "simulated": True, "attempt_id": task["attempt_id"], "exit_code": 0 if passed else 1}
            evidence["hash"] = hashlib.sha256(evidence["content"].encode()).hexdigest()
            task["artifacts"].append(evidence)
            self.transition(task, "COMPLETED" if passed else "FAILED", "Simulated verifier passed" if passed else "Simulated verifier failed; inspect evidence")
            return
        if scenario == "hang":
            task["due"] = now + 3
            return
        if scenario == "failure":
            self.transition(task, "FAILED", "Fake agent reported a deterministic failure")
            return
        if scenario == "quota" and task["stage"] == 0:
            task.update(stage=1, due=now + 15)
            self.transition(task, "WAITING_QUOTA", "Simulated quota cooldown: 15 seconds; no provider quota used")
            return
        if scenario in {"input", "approval"} and not task.get("gate_resolved"):
            message = "Which acceptance criterion should the simulation use?" if scenario == "input" else "Allow the fake agent to produce a simulated result? No files will be changed."
            task["pending"] = {"id": identifier("request"), "message": message, "expires": now + 600,
                               "payload_hash": hashlib.sha256(message.encode()).hexdigest(), "attempt_id": task["attempt_id"]}
            self.transition(task, "WAITING_INPUT" if scenario == "input" else "WAITING_APPROVAL", message)
            return
        artifact = {"id": identifier("artifact"), "kind": "result", "name": "Simulated result", "simulated": True,
                    "attempt_id": task["attempt_id"], "content": f"Simulation result for: {task['title']}\nScope: {', '.join(task['scope'])}\nInstruction version: {len(task['instructions'])}\nNo repository was read or modified. Real CLI adapters remain disabled."}
        artifact["hash"] = hashlib.sha256(artifact["content"].encode()).hexdigest()
        task["artifacts"].append(artifact)
        task["due"] = now + 3
        self.transition(task, "VERIFY", "Checking simulated result; real verifier is not connected")
