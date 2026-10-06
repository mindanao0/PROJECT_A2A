"""What an attempt cost (OD-012): context bytes, time, and the tokens/cost a CLI chooses to expose.

Subscription CLIs report usage in their own event streams; a field a CLI does not expose stays None
instead of being guessed. A context fingerprint is not a provider cache hit, so only the CLI's own
cached-token counts are reported as cache use."""

import json
from collections import defaultdict

TAIL = 400_000  # ponytail: only the log's tail is read, so a very long Codex run undercounts early turns


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
                                "input": 0, "cached": 0, "output": 0, "cost_usd": 0.0, "with_usage": 0})
    for a in store.q("select a.*, t.agent, t.kind, t.project from attempts a join tasks t on t.id = a.task"
                     " where a.started >= ? and a.status = 'ended'", since):
        if project and a["project"] != project:
            continue
        r = rows[(a["agent"], a["kind"] or "implement")]
        r["attempts"] += 1
        r["outcomes"][a["outcome"] or "?"] += 1
        r["seconds"] += (a["ended"] or a["started"]) - a["started"]
        r["prompt_bytes"] += a["prompt_bytes"] or 0
        u = json.loads(a["usage"]) if a["usage"] else None
        if u:
            r["with_usage"] += 1
            for k in ("input", "cached", "output"):
                r[k] += u[k]
            r["cost_usd"] += u["cost_usd"] or 0.0
    return {k: v | {"outcomes": dict(v["outcomes"])} for k, v in sorted(rows.items())}
