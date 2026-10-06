"""Integration branch (D-014): finished tasks are merged on refs/navis/integration/<project>, the
checks run on that exact commit, and the user fast-forwards their own branch.

The user's checkout is only touched by promote(), which refuses a dirty tree. Merges are built with
`git merge-tree` + `commit-tree`, so no working tree is needed."""

import json
import shutil
import subprocess
import threading
from collections import defaultdict

from . import runtime, sandbox

REF = "refs/navis/integration/{}"
LOCKS = defaultdict(threading.Lock)  # ponytail: per process; across processes update-ref's compare-and-set decides


class IntegrationError(Exception):
    pass


def git(path, *args, env=None):
    r = subprocess.run(["git", "-C", path, *args], capture_output=True, text=True, env=env)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def ancestor(path, a, b):
    return git(path, "merge-base", "--is-ancestor", a, b)[0] == 0


def merge(path, ours, theirs, message):
    """(commit, conflicted files). The commit only exists as an object until a ref points at it."""
    rc, out, err = git(path, "merge-tree", "--write-tree", "--name-only", ours, theirs)
    if rc == 1:
        return None, [f for f in out.split("\n\n")[0].splitlines()[1:] if f]
    if rc:
        raise IntegrationError(f"merge failed: {err}")
    rc, commit, err = git(path, *sandbox.GIT[1:], "commit-tree", out.splitlines()[0], "-p", ours, "-p", theirs, "-m", message)
    if rc:
        raise IntegrationError(f"commit failed: {err}")
    return commit, []


def run_checks(rt, t, proj, commit, tip):
    """Checks on a clone of exactly `commit`; [(name, rc, tail)]."""
    if proj["prepare"] and not t["approved"] and sandbox.inputs_changed(proj["path"], tip, commit, proj["prepare_inputs"]):
        raise IntegrationError("dependency files changed; approve this task's prepare step first")
    lim, aid = rt.cfg["limits"], f"i{t['id']}"
    repo = runtime.data_dir() / "integrations" / f"{t['project']}-{commit[:10]}" / "repo"
    shutil.rmtree(repo.parent, ignore_errors=True)
    repo.parent.mkdir(parents=True)
    sandbox.clone(proj["path"], repo, commit, f"navis/integration/{commit[:10]}")
    ro = [*proj["objects"], *proj["ro"]]
    try:
        for name, cmd in proj["prepare"].items():
            rc, tail = rt._sandboxed(f"navis-{rt.tag}-{aid}-prepare{next(rt.counter)}", repo, ro, proj["prepare_rw"], cmd,
                                     True, lim["check_memory"], lim["check_timeout"])
            if rc:
                return [(f"prepare {name}", rc, tail)]
        return [(name, *rt._check(aid, repo, proj, ro, name)) for name in proj["checks"]]
    finally:
        shutil.rmtree(repo.parent, ignore_errors=True)


def integrate(rt, tid):
    """Merge a COMPLETED task's result into the integration branch if the checks pass on the merged commit."""
    try:
        return _integrate(rt, tid)
    except IntegrationError as e:
        rt.store.log(tid, None, "integrate-error", error=str(e))
        raise


def _integrate(rt, tid):
    s = rt.store
    t = s.one("select * from tasks where id = ?", tid)
    if not t or t["status"] != "COMPLETED" or not t["head"]:
        raise IntegrationError("only a completed task with a result can be integrated")
    proj = runtime.load_project(t["project"])
    path, ref = proj["path"], REF.format(t["project"])
    with LOCKS[t["project"]]:
        head = git(path, "rev-parse", "HEAD")[1]
        old = git(path, "rev-parse", "--verify", "-q", ref)[1]
        tip = old or head
        if not ancestor(path, head, tip):  # the user's branch moved on: bring it in first
            tip, conflicts = merge(path, tip, head, "navis: sync with your branch")
            if conflicts:
                raise IntegrationError(f"your branch and the integration branch conflict in: {', '.join(conflicts)}")
        if ancestor(path, t["head"], tip):
            raise IntegrationError("this result is already in the integration branch")
        if ancestor(path, tip, t["head"]):
            new = t["head"]
        else:
            new, conflicts = merge(path, tip, t["head"], f"navis: integrate task {tid}")
            if conflicts:
                raise IntegrationError(f"conflicts with the integration branch in: {', '.join(conflicts)}")
        results = run_checks(rt, t, proj, new, tip)
        ok = all(rc == 0 for _, rc, _ in results)
        s.log(tid, None, "integrate", project=t["project"], commit=new, base=tip, ok=ok,
              checks=[{"name": n, "rc": rc, "tail": rt.redact(tail)} for n, rc, tail in results])
        if not ok:
            raise IntegrationError("checks failed on the integration commit: " + ", ".join(n for n, rc, _ in results if rc))
        rc, _, err = git(path, "update-ref", ref, new, old or "0" * len(new))
        if rc:
            raise IntegrationError(f"integration branch changed meanwhile; try again ({err})")
        return new


def evidence(store, project, commit):
    for e in store.q("select * from events where kind = 'integrate' order by id desc limit 200"):
        d = json.loads(e["data"])
        if d["project"] == project and d["commit"] == commit and d["ok"]:
            return d
    return None


def status(store, project):
    """What a promote would do now, for the CLI and the GUI."""
    path = runtime.load_project(project)["path"]
    ref, head = REF.format(project), git(path, "rev-parse", "HEAD")[1]
    tip = git(path, "rev-parse", "--verify", "-q", ref)[1]
    out = {"project": project, "commit": tip or None, "head": head, "branch": git(path, "symbolic-ref", "-q", "--short", "HEAD")[1],
           "tasks": [], "checks": [], "can_promote": False, "reason": ""}
    if not tip or ancestor(path, tip, head):
        return out | {"reason": "nothing to promote"}
    seen = []
    for e in store.q("select task, data from events where kind = 'integrate' order by id desc limit 200"):
        d = json.loads(e["data"])
        if d["project"] == project and d["ok"] and e["task"] not in seen and ancestor(path, d["commit"], tip) \
                and not ancestor(path, d["commit"], head):
            seen.append(e["task"])
    ev = evidence(store, project, tip)
    out |= {"tasks": sorted(seen), "checks": [{"name": c["name"], "rc": c["rc"]} for c in (ev or {}).get("checks", [])]}
    if not ancestor(path, head, tip):
        out["reason"] = "your branch moved; integrate a task again to bring it in"
    elif not ev:
        out["reason"] = "no passing checks recorded for this exact commit"
    elif not out["branch"]:
        out["reason"] = "HEAD is detached; check out a branch first"
    elif git(path, "status", "--porcelain", "--untracked-files=no")[1]:
        out["reason"] = "your working tree has uncommitted changes"
    else:
        out["can_promote"] = True
    return out


def promote(store, project, expected=None):
    """Fast-forward the user's checked-out branch to the integration commit. The user's action.
    `expected` binds the click to the commit the user saw."""
    st = status(store, project)
    if expected and expected != st["commit"]:
        raise IntegrationError("the integration branch changed; refresh and look again")
    if not st["can_promote"]:
        raise IntegrationError(st["reason"])
    path = runtime.load_project(project)["path"]
    # No hooks: the merged files came from an agent, and this is not the place to run repo scripts.
    rc, _, err = git(path, "-c", "core.hooksPath=/dev/null", "merge", "--ff-only", st["commit"])
    if rc:
        raise IntegrationError(f"fast-forward failed: {err}")
    store.log(None, None, "promote", project=project, commit=st["commit"], branch=st["branch"])
    return st["commit"]
