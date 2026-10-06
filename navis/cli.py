"""navis command line."""

import argparse
import json
import sys
import time

from . import helper, integrate, retention, runtime, usage


def show_tasks(store):
    rows = store.q("select * from tasks order by id")
    print(f"{'ID':>4}  {'STATUS':<16} {'AGENT':<7} {'PROJECT':<10} {'SCOPE':<20} NOTE")
    for t in rows:
        scope = ",".join(json.loads(t["scope"]))
        note = t["note"].splitlines()[0][:60] if t["note"] else ""
        print(f"{t['id']:>4}  {t['status']:<16} {t['agent']:<7} {t['project']:<10} {scope[:20]:<20} {note}")


def show_task(store, tid):
    t = store.one("select * from tasks where id = ?", tid)
    if not t:
        sys.exit(f"no task {tid}")
    for k in ("id", "status", "project", "agent", "scope", "base", "head", "attempts", "note"):
        print(f"{k:>9}: {t[k]}")
    print(f"{'spec':>9}: {t['spec']}")
    print("\nevents:")
    for e in store.q("select * from events where task = ? order by id", tid):
        at = time.strftime("%H:%M:%S", time.localtime(e["at"]))
        print(f"  {at} {e['attempt'] or '-':<6} {e['kind']:<12} {e['data'][:200]}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="navis", description="Run coding agents on separate, sandboxed tasks.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add", help="queue a task")
    a.add_argument("-p", "--project", required=True, help="name of ~/.config/navis/projects/<name>.toml")
    a.add_argument("-a", "--agent", required=True, choices=sorted(runtime.ADAPTERS))
    a.add_argument("-s", "--scope", action="append", default=[], help="path prefix the task may edit (repeatable)")
    a.add_argument("--base", default="HEAD", help="commit to start from")
    a.add_argument("--after", type=int, help="start only after this task is COMPLETED, from its result")
    a.add_argument("--check", action="append", dest="checks", metavar="NAME",
                   help="verify this task with only these project checks (repeatable); integration still runs all")
    a.add_argument("spec", help="task text, or - to read it from stdin")
    sub.add_parser("ls", help="list tasks")
    sub.add_parser("run", help="run the scheduler (one per machine)")
    for name, help_ in [("show", "task details and events"), ("stop", "stop or cancel a task"),
                        ("approve", "approve a task waiting for approval or in review"),
                        ("reject", "reject a task in review")]:
        sub.add_parser(name, help=help_).add_argument("id", type=int)
    sub.add_parser("summarize", help="summarize a task with the local model (sources cited)").add_argument("id", type=int)
    sub.add_parser("integrate", help="merge a completed task into the integration branch (checks run on the result)").add_argument("id", type=int)
    rv = sub.add_parser("review", help="queue a read-only review of a completed task's exact result")
    rv.add_argument("id", type=int)
    rv.add_argument("-a", "--agent", required=True, choices=sorted(runtime.ADAPTERS))
    rv2 = sub.add_parser("revise", help="queue a bounded follow-up round that addresses a review's findings")
    rv2.add_argument("id", type=int)
    rv2.add_argument("-a", "--agent", choices=sorted(runtime.ADAPTERS), help="default: the original agent")
    ri = sub.add_parser("review-integration", help="queue a read-only review of the merged integration commit")
    ri.add_argument("project")
    ri.add_argument("-a", "--agent", required=True, choices=sorted(runtime.ADAPTERS))
    sub.add_parser("discard", help="roll back: drop a project's integration branch").add_argument("project")
    u = sub.add_parser("usage", help="what attempts cost: time, context bytes and the tokens the CLIs exposed")
    u.add_argument("-p", "--project")
    u.add_argument("--hours", type=float, default=24 * 7)
    g = sub.add_parser("gc", help="delete old attempt directories of finished tasks")
    g.add_argument("--days", type=int, help="default: [limits] retention_days (30)")
    g.add_argument("--dry-run", action="store_true")
    sub.add_parser("verify-integration", help="run every check on a project's integration commit").add_argument("project")
    sub.add_parser("integration", help="show a project's integration branch").add_argument("project")
    sub.add_parser("promote", help="fast-forward your checked-out branch to the integration branch").add_argument("project")
    an = sub.add_parser("answer", help="answer the agent's question")
    an.add_argument("id", type=int)
    an.add_argument("text")
    args = ap.parse_args(argv)

    store = runtime.open_store()
    if args.cmd == "add":
        spec = sys.stdin.read() if args.spec == "-" else args.spec
        try:
            tid, dup = runtime.add_task(store, args.project, args.agent, spec, args.scope, args.base, after=args.after,
                                          checks=args.checks)
        except ValueError as e:
            sys.exit(str(e))
        if dup:
            sys.exit(f"duplicate of task {dup}; not queued")
        print(tid)
    elif args.cmd == "ls":
        show_tasks(store)
    elif args.cmd == "show":
        show_task(store, args.id)
    elif args.cmd == "run":
        runtime.Runtime(store).run_forever()
    elif args.cmd == "summarize":
        try:
            r = helper.summarize(store, args.id)
        except (ValueError, OSError) as e:
            sys.exit(f"summarize failed: {e}")
        print(r["text"], f"\ncited: {', '.join(r['cited']) or 'none'}",
              *([f"unverified refs: {', '.join(r['unknown_refs'])}"] if r["unknown_refs"] else []), sep="\n")
    elif args.cmd == "integrate":
        rt = runtime.Runtime(store)
        try:
            commit = integrate.integrate(rt, args.id)
        except integrate.IntegrationError as e:
            sys.exit(f"not integrated: {e}")
        print(f"integrated at {commit[:10]}; checks passed")
    elif args.cmd == "review":
        try:
            rid, dup = runtime.request_review(store, args.id, args.agent)
        except ValueError as e:
            sys.exit(str(e))
        if dup:
            sys.exit(f"duplicate of review task {dup}; not queued")
        print(rid)
    elif args.cmd == "revise":
        try:
            rid, dup = runtime.revise(store, args.id, args.agent)
        except ValueError as e:
            sys.exit(str(e))
        print(f"duplicate of task {dup}; not queued" if dup else rid)
    elif args.cmd == "review-integration":
        try:
            rid, dup = runtime.request_integration_review(store, args.project, args.agent)
        except ValueError as e:
            sys.exit(str(e))
        print(f"duplicate of review task {dup}; not queued" if dup else rid)
    elif args.cmd == "discard":
        try:
            print(f"discarded integration branch at {integrate.discard(store, args.project)[:10]}")
        except integrate.IntegrationError as e:
            sys.exit(str(e))
    elif args.cmd == "usage":
        rep = usage.report(store, time.time() - args.hours * 3600, args.project)
        print(f"last {args.hours:g} h{' / ' + args.project if args.project else ''}")
        print(f"{'AGENT':<7} {'KIND':<10} {'ATT':>3} {'OUTCOMES':<30} {'SECS':>6} {'PROMPT KB':>9} {'IN TOK':>9} {'CACHED':>9} {'OUT TOK':>8} {'COST $':>7}")
        for (agent, kind), r in rep.items():
            outcomes = ",".join(f"{k}:{v}" for k, v in sorted(r["outcomes"].items()))
            tokens = (f"{r['input']:>9} {r['cached']:>9} {r['output']:>8} {r['cost_usd']:>7.3f}" if r["with_usage"]
                      else f"{'-':>9} {'-':>9} {'-':>8} {'-':>7}")
            print(f"{agent:<7} {kind:<10} {r['attempts']:>3} {outcomes:<30} {r['seconds']:>6.0f} {r['prompt_bytes'] / 1024:>9.1f} {tokens}")
        if not rep:
            print("no finished attempts in this window")
    elif args.cmd == "gc":
        r = retention.gc(store, args.days, args.dry_run)
        print(f"{'would remove' if r['dry_run'] else 'removed'} {r['attempt_dirs']} attempt directories "
              f"({r['bytes'] / 1e6:.1f} MB) older than {r['days']} days")
    elif args.cmd == "verify-integration":
        try:
            print(f"all checks passed at {integrate.verify(runtime.Runtime(store), args.project)[:10]}")
        except integrate.IntegrationError as e:
            sys.exit(f"not verified: {e}")
    elif args.cmd == "integration":
        st = integrate.status(store, args.project)
        print(f"branch {st['branch'] or '(detached)'} @ {st['head'][:10]}; integration @ {(st['commit'] or 'none')[:10]}")
        print(f"tasks: {', '.join(map(str, st['tasks'])) or 'none'}; checks: " +
              (", ".join(f"{c['name']} {'ok' if not c['rc'] else 'FAILED'}" for c in st["checks"]) or "none"))
        print("can promote" if st["can_promote"] else f"cannot promote: {st['reason']}")
    elif args.cmd == "promote":
        try:
            commit = integrate.promote(store, args.project)
        except integrate.IntegrationError as e:
            sys.exit(f"not promoted: {e}")
        print(f"fast-forwarded to {commit[:10]}")
    elif args.cmd == "stop":
        print(runtime.stop_task(store, args.id))
    elif args.cmd == "answer":
        if not runtime.answer(store, args.id, args.text):
            sys.exit(f"task {args.id} is not waiting for input")
    elif args.cmd == "approve":
        if not runtime.approve(store, args.id):
            sys.exit(f"task {args.id} is not waiting for approval or review")
    elif args.cmd == "reject":
        if not runtime.reject(store, args.id):
            sys.exit(f"task {args.id} is not in review")


if __name__ == "__main__":
    main()
