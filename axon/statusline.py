"""Claude Code's status line command, set per attempt by Axon (claude_cmd): Claude hands it a JSON of the session on
stdin, with the subscription's 5h/week usage once it has had an answer. Written to a file in Claude's own config dir
for the Agent fleet; nothing is printed, so no status bar is drawn."""

import json
import os
import sys
import time
from pathlib import Path

from . import usage


def main():
    try:
        rl = json.load(sys.stdin)["rate_limits"]
        out = {"windows": [usage.window(m, rl[k]["used_percentage"], rl[k]["resets_at"])
                           for k, m in (("five_hour", 300), ("seven_day", 10080)) if rl.get(k)], "as_of": time.time()}
        f = Path(os.environ["CLAUDE_CONFIG_DIR"], "axon-limits.json")
        f.with_suffix(".tmp").write_text(json.dumps(out))
        f.with_suffix(".tmp").replace(f)  # a reader never sees half a file
    except (ValueError, KeyError, TypeError, OSError):
        pass  # no subscription limits in this session (or the format changed): nothing to record


if __name__ == "__main__":
    main()
