"""navis command line."""

import argparse
import json
import os
import sys
import time

from . import helper, integrate, runtime


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


def chat(project, agent, label=""):
    """Interactive claude/codex in the sandbox, kept alive in tmux; run again to re-attach.
    No MCP tools and no task: you talk to the agent directly (slash commands, questions, menus)."""
    new = runtime.chat_name(project, agent, label) not in runtime.chat_sessions()
    name = runtime.chat_start(project, agent, label)
    if new:
        print(f"started {agent} ; detach with Ctrl-b d")
    os.execvp("tmux", ["tmux", "attach", "-t", name])


def logs(store, tid, follow):
    """Readable agent output of the latest attempt; with -f, new lines as they arrive until the task leaves RUNNING."""
    done, aid = 0, None
    while True:
        a = store.one("select id from attempts where task = ? order by started desc limit 1", tid)
        if a and a["id"] != aid:
            aid, done = a["id"], 0
            print(f"--- attempt {aid}")
        path = runtime.data_dir() / "attempts" / (aid or "-") / "agent.log"
        lines = path.read_text(errors="replace").splitlines() if path.exists() else []
        for line in lines[done:]:
            text = runtime.format_log_line(line)
            if text:
                print(text, flush=True)
        done = len(lines)
        t = store.one("select status from tasks where id = ?", tid)
        if not follow or not t or t["status"] != "RUNNING":
            return
        time.sleep(0.5)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="navis", description="Run coding agents on separate, sandboxed tasks.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add", help="queue a task")
    a.add_argument("-p", "--project", required=True, help="name of ~/.config/navis/projects/<name>.toml")
    a.add_argument("-a", "--agent", required=True, choices=sorted(runtime.ADAPTERS))
    a.add_argument("-s", "--scope", action="append", default=[], help="path prefix the task may edit (repeatable)")
    a.add_argument("--base", default="HEAD", help="commit to start from")
    a.add_argument("--after", type=int, help="start only after this task is COMPLETED, from its result")
    a.add_argument("--model", default="", help="model for this task (default: the project's [agents.<agent>] model, then the CLI's)")
    a.add_argument("--effort", default="", help="reasoning effort (claude: low, medium, high, xhigh, max)")
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
    sub.add_parser("integration", help="show a project's integration branch").add_argument("project")
    sub.add_parser("promote", help="fast-forward your checked-out branch to the integration branch").add_argument("project")
    an = sub.add_parser("answer", help="answer the agent's question")
    an.add_argument("id", type=int)
    an.add_argument("text", nargs="?", help="your answer, or the number of an offered option; omit to be asked")
    lg = sub.add_parser("logs", help="what the agent said and did in the latest attempt (-f follows)")
    lg.add_argument("id", type=int)
    lg.add_argument("-f", "--follow", action="store_true")
    ch = sub.add_parser("chat", help="talk to claude/codex interactively in the sandbox (tmux; run again to re-attach)")
    ch.add_argument("project")
    ch.add_argument("-a", "--agent", required=True, choices=["claude", "codex"])
    ch.add_argument("-n", "--name", default="", help="extra chat on the same project and agent (own clone)")
    args = ap.parse_args(argv)
    if args.cmd == "chat":
        return chat(args.project, args.agent, args.name)

    store = runtime.open_store()
    if args.cmd == "add":
        spec = sys.stdin.read() if args.spec == "-" else args.spec
        try:
            tid, dup = runtime.add_task(store, args.project, args.agent, spec, args.scope, args.base, after=args.after,
                                         model=args.model, effort=args.effort)
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
    elif args.cmd == "logs":
        logs(store, args.id, args.follow)
    elif args.cmd == "answer":
        t = store.one("select status, note from tasks where id = ?", args.id)
        if not t or t["status"] != "WAITING_INPUT":
            sys.exit(f"task {args.id} is not waiting for input")
        options, text = runtime.ask_options(store, args.id), args.text
        if text is None:  # ask here, with the agent's own choices numbered
            print(t["note"])
            print(*(f"  {i}) {o}" for i, o in enumerate(options, 1)), sep="\n")
            text = input("answer" + (" (number or text): " if options else ": ")).strip()
        if options and text.isdigit() and 1 <= int(text) <= len(options):
            text = options[int(text) - 1]
        if not text or not runtime.answer(store, args.id, text):
            sys.exit(f"task {args.id} is not waiting for input" if text else "empty answer")
    elif args.cmd == "approve":
        if not runtime.approve(store, args.id):
            sys.exit(f"task {args.id} is not waiting for approval or review")
    elif args.cmd == "reject":
        if not runtime.reject(store, args.id):
            sys.exit(f"task {args.id} is not in review")


if __name__ == "__main__":
    main()
