"""Scripted stand-in for an agent CLI (docs/EXECUTION_DESIGN.md §6).

Reads a TOML scenario from the prompt, after the '--- task ---' line:

    [[step]]
    do = "edit"          # edit, prompt, mcp, shell, sleep, hang, orphan, rate_limit, crash, garbage
    path = "src/x.py"
    attempt = 1          # optional: only run this step on that attempt number
"""

import json
import os
import subprocess
import sys
import time
import tomllib
from pathlib import Path

from .mcpclient import Mcp


def emit(**event):
    print(json.dumps(event), flush=True)


def main(prompt):
    scenario = tomllib.loads(prompt.split("--- task ---\n", 1)[1])
    n = int(os.environ.get("NAVIS_ATTEMPT", "1"))
    mcp = None
    emit(type="start", attempt=n)
    for step in scenario.get("step", []):
        if step.get("attempt", n) != n:
            continue
        do = step["do"]
        if do in ("edit", "prompt"):
            p = Path(step["path"])
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open("a") as f:
                f.write(prompt if do == "prompt" else step.get("text", "x\n"))
        elif do == "mcp":
            mcp = mcp or Mcp(json.loads(os.environ["NAVIS_MCP"]))
            emit(type="tool", tool=step["tool"], result=mcp.call(step["tool"], step.get("args", {})))
        elif do == "shell":
            r = subprocess.run(step["cmd"], shell=True, capture_output=True, text=True)
            emit(type="shell", rc=r.returncode, out=r.stdout + r.stderr)
        elif do == "sleep":
            time.sleep(step.get("s", 1))
        elif do == "hang":
            time.sleep(10**6)
        elif do == "orphan":
            # Escapes the agent's session; only the cgroup/pid namespace can still reach it.
            subprocess.Popen(["setsid", "sh", "-c",
                              f"while :; do date +%s%N >> '{step['path']}'; sleep 0.1; done"])
        elif do == "rate_limit":
            print("Error: rate limit reached, try again later", flush=True)
            sys.exit(1)
        elif do == "crash":
            sys.exit(step.get("code", 1))
        elif do == "garbage":
            print("{not json", flush=True)
    emit(type="end")


if __name__ == "__main__":
    main(sys.argv[1])
