"""Phase 1b: run one real task through the Runner with a real agent CLI (uses quota).

    python3 probes/adapter.py codex|claude ["task text"]

Needs a prior login into the isolated agent home (docs/EXECUTION_DESIGN.md §3). State lives in a
short /tmp dir (the MCP socket path must stay under 108 characters) and the agent home is
symlinked, never copied. Prints status, events and the end of agent.log as evidence."""

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

agent = sys.argv[1]
spec = sys.argv[2] if len(sys.argv) > 2 else (
    "Create the file src/hello.txt containing the word hi. Then call the run_check tool with name ok. "
    "Then call report_result with status done.")
real = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "navis" / "agents" / agent
work = Path(tempfile.mkdtemp(prefix="nv", dir="/tmp"))
(work / "home/agents").mkdir(parents=True)
(work / "cfg/projects").mkdir(parents=True)
(work / "home/agents" / agent).symlink_to(real)
proj = work / "proj"
(proj / "src").mkdir(parents=True)
(proj / "src/seed.txt").write_text("seed\n")
git = ["git", "-C", str(proj), "-c", "user.name=t", "-c", "user.email=t@t"]
subprocess.run([*git, "init", "-q"], check=True)
subprocess.run([*git, "add", "-A"], check=True)
subprocess.run([*git, "commit", "-qm", "init"], check=True)
(work / "cfg/projects/p.toml").write_text(f'path = "{proj}"\n[checks]\nok = "true"\n')
os.environ.update(NAVIS_HOME=str(work / "home"), NAVIS_CONFIG=str(work / "cfg"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from navis import runtime  # noqa: E402  (after the environment is set)

s = runtime.open_store()
tid, _ = runtime.add_task(s, "p", agent, spec, ["src"])
t0 = time.time()
runtime.Runtime(s).run_until_idle(600)
t = s.one("select * from tasks where id = ?", tid)
print(f"{agent}: {t['status']} in {time.time() - t0:.0f}s | {t['note']}")
for e in s.q("select attempt, kind, data from events where task = ? order by id", tid):
    print(" ", e["attempt"], e["kind"], e["data"][:240])
log = work / "home/attempts" / f"{tid}-1" / "agent.log"
print("--- agent.log tail\n" + (log.read_bytes()[-2500:].decode(errors="replace") if log.exists() else "(none)"))
shutil.rmtree(work, ignore_errors=True)
sys.exit(t["status"] != "COMPLETED")
