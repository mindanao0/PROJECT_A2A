"""Retention: old attempt directories (logs, prompts, bundles) of finished tasks.

Never touched: attempts of tasks that are not finished, `refs/navis/attempts/*` (they keep result commits
reachable for retry, continue and integrate; delete one with `git update-ref -d` if you really want it
gone), and the events table (check results and verdicts stay queryable)."""

import shutil
import time

from . import runtime

FINISHED = ("COMPLETED", "FAILED", "CANCELLED")


def size(path):
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file() and not f.is_symlink())


def gc(store, days=None, dry_run=False):
    days = runtime.load_config()["limits"]["retention_days"] if days is None else days
    cutoff = time.time() - days * 86400
    out = {"attempt_dirs": 0, "bytes": 0, "days": days, "dry_run": dry_run}
    for a in store.q("select a.id from attempts a join tasks t on t.id = a.task where a.status = 'ended'"
                     " and a.ended < ? and t.status in ('COMPLETED', 'FAILED', 'CANCELLED')", cutoff):
        d = runtime.data_dir() / "attempts" / a["id"]
        if d.is_dir():
            out["attempt_dirs"] += 1
            out["bytes"] += size(d)
            if not dry_run:
                shutil.rmtree(d, ignore_errors=True)
    leftovers = runtime.data_dir() / "integrations"  # clones of a crashed integrate; normally removed at once
    if leftovers.is_dir():
        for d in leftovers.iterdir():
            if d.stat().st_mtime < cutoff:
                out["bytes"] += size(d)
                if not dry_run:
                    shutil.rmtree(d, ignore_errors=True)
    return out
