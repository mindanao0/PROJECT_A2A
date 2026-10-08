"""Quota-aware routing (Phase 5). A task created with agent "auto" goes to the first agent in the pool that can
start it right now; if that agent later hits its quota the task is routed again instead of waiting.

Opt-in per task: a task with an explicit agent is never moved. Nothing here guesses at quality: the pool order
is the user's preference, and the only inputs are facts the Runtime already has (login, cooldown, free slot)."""

import tomllib
from pathlib import Path

LOGIN_FILE = {"codex": "auth.json", "claude": ".credentials.json"}
ROUTABLE = ("claude", "codex", "fake")  # local coding is a role the user switches on, never picked automatically


def logged_in(cfg, data_dir, name):
    if name == "local":  # no login: a role the user switches on in config.toml
        return bool(cfg["local"]["coding"])
    f = LOGIN_FILE.get(name)
    return not f or (Path(data_dir) / "agents" / name / f).exists()


def pool(cfg):
    return [a for a in cfg["routing"]["pool"] if a in ROUTABLE]


def candidates(cfg, implementer=None):
    """Pool order, but for a review the implementer's own agent goes last: a second opinion is the point."""
    order = pool(cfg)
    return [a for a in order if a != implementer] + [a for a in order if a == implementer]


def choose(task, cfg, running, cooling, now, data_dir, implementer=None):
    """(agent or None, {agent: why it was skipped}). Pure: reads facts, changes nothing."""
    skipped = {}
    for agent in candidates(cfg, implementer):
        if not logged_in(cfg, data_dir, agent):
            skipped[agent] = "not logged in"
        elif cooling.get(agent, 0) > now:
            skipped[agent] = "cooling down after a quota limit"
        elif sum(r["agent"] == agent for r in running) >= cfg["slots"].get(agent, 1):
            skipped[agent] = "slots full"
        else:
            return agent, skipped
    return None, skipped


def save_first(config_file, first):
    """Persist the preferred agent: the pool becomes [first, the other one]."""
    from .agent_options import dump
    if first not in ("claude", "codex"):
        raise ValueError("the first choice must be claude or codex")
    pool_ = [first, "codex" if first == "claude" else "claude"]
    f = Path(config_file)
    cfg = tomllib.loads(f.read_text()) if f.exists() else {}
    cfg.setdefault("routing", {})["pool"] = pool_
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(dump(cfg))
    tmp.replace(f)
    return pool_
