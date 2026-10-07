"""What an attempt cost (OD-012): context bytes, time, and the tokens/cost a CLI chooses to expose.

Subscription CLIs report usage in their own event streams; a field a CLI does not expose stays None
instead of being guessed. A context fingerprint is not a provider cache hit, so only the CLI's own
cached-token counts are reported as cache use."""

import json
import time
import urllib.request
from collections import defaultdict
from datetime import datetime
from pathlib import Path

TAIL = 400_000  # ponytail: only the log's tail is read, so a very long Codex run undercounts early turns
CLAUDE_USAGE = "https://api.anthropic.com/api/oauth/usage"  # what Claude Code's /usage reads; not a published API
WINDOWS = {300: "5h", 10080: "week"}


def parse(agent, text):
    """{input, cached, output, turns, cost_usd} from an agent log; None when the CLI exposed nothing."""
    tot = {"input": 0, "cached": 0, "output": 0, "turns": 0, "cost_usd": None}
    seen = False
    for line in text.splitlines():
        if not line.startswith("{"):
            continue
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if agent == "codex" and e.get("type") == "turn.completed" and e.get("usage"):
            u, seen = e["usage"], True
            tot["input"] += u.get("input_tokens", 0)  # Codex counts cached tokens inside input_tokens
            tot["cached"] += u.get("cached_input_tokens", 0)
            tot["output"] += u.get("output_tokens", 0) + u.get("reasoning_output_tokens", 0)
            tot["turns"] += 1
        elif agent == "local" and e.get("type") == "usage":
            seen = True
            tot.update(input=e.get("input", 0), output=e.get("output", 0), turns=e.get("turns", 0))
        elif agent == "claude" and e.get("type") == "result" and e.get("usage"):
            u, seen = e["usage"], True
            tot["input"] = u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0) + u.get("cache_read_input_tokens", 0)
            tot["cached"] = u.get("cache_read_input_tokens", 0)
            tot["output"] = u.get("output_tokens", 0)
            tot["turns"] = e.get("num_turns", 0)
            tot["cost_usd"] = e.get("total_cost_usd")
    return tot if seen else None


def report(store, since=0.0, project=None):
    """Rows per (agent, kind): attempts, outcomes, wall seconds, prompt bytes and the usage the CLIs exposed."""
    rows = defaultdict(lambda: {"attempts": 0, "outcomes": defaultdict(int), "seconds": 0.0, "prompt_bytes": 0,
                                "input": 0, "cached": 0, "output": 0, "cost_usd": 0.0, "with_usage": 0, "settings": set()})
    for a in store.q("select a.*, t.agent, t.kind, t.project from attempts a join tasks t on t.id = a.task"
                     " where a.started >= ? and a.status = 'ended'", since):
        if project and a["project"] != project:
            continue
        r = rows[(a["agent"], a["kind"] or "implement")]
        r["attempts"] += 1
        r["outcomes"][a["outcome"] or "?"] += 1
        r["seconds"] += (a["ended"] or a["started"]) - a["started"]
        r["prompt_bytes"] += a["prompt_bytes"] or 0
        r["settings"].add(f"{a['model'] or 'default'}/{a['effort'] or 'default'}")
        u = json.loads(a["usage"]) if a["usage"] else None
        if u:
            r["with_usage"] += 1
            for k in ("input", "cached", "output"):
                r[k] += u[k]
            r["cost_usd"] += u["cost_usd"] or 0.0
    return {k: v | {"outcomes": dict(v["outcomes"]), "settings": sorted(v["settings"])} for k, v in sorted(rows.items())}


# Subscription windows: how much of the 5-hour and weekly limits is used, as the providers report it (percent, not tokens).

def window(minutes, used, resets_at):
    return {"window": WINDOWS.get(minutes, f"{minutes // 60}h"), "used": float(used), "resets_at": resets_at}


def ts(iso):
    return datetime.fromisoformat(iso).timestamp() if iso else None


def codex_limits(home):
    """{windows, as_of} as of Codex's last turn under `home`: its session files record the limits after each turn."""
    for f in sorted(Path(home, "sessions").glob("*/*/*/rollout-*.jsonl"), reverse=True)[:20]:
        with open(f, "rb") as fh:
            fh.seek(max(0, fh.seek(0, 2) - 262_144))
            lines = fh.read().decode(errors="replace").splitlines()
        for line in reversed(lines):
            if '"rate_limits"' not in line:
                continue
            try:
                d = json.loads(line)
                rl = d["payload"]["rate_limits"]
                return {"windows": [window(w["window_minutes"], w["used_percent"], w["resets_at"])
                                    for w in (rl["primary"], rl["secondary"]) if w], "as_of": ts(d["timestamp"])}
            except (ValueError, KeyError, TypeError):
                continue
    return None


def claude_limits(home, cache):
    """{windows, as_of} from the endpoint Claude Code's /usage reads, while Claude's own login token is valid (Claude
    renews it whenever it starts; Navis never rewrites the login). Otherwise the last answer, kept in `cache`."""
    try:
        o = json.loads(Path(home, ".credentials.json").read_text())["claudeAiOauth"]
        if o["expiresAt"] / 1000 > time.time() + 60:
            req = urllib.request.Request(CLAUDE_USAGE, headers={"Authorization": "Bearer " + o["accessToken"],
                                                                "anthropic-beta": "oauth-2025-04-20", "User-Agent": "navis"})
            with urllib.request.urlopen(req, timeout=10) as r:
                d = json.load(r)
            out = {"windows": [window(m, d[k]["utilization"], ts(d[k].get("resets_at")))
                               for k, m in (("five_hour", 300), ("seven_day", 10080)) if d.get(k)], "as_of": time.time()}
            Path(cache).write_text(json.dumps(out))
            return out
    except (OSError, ValueError, KeyError, TypeError):
        pass  # no login, an expired token, offline, or the endpoint changed: fall back to the last answer
    try:
        return json.loads(Path(cache).read_text())
    except (OSError, ValueError):
        return None
