"""Phase 3 benchmark: single agent vs implement -> review -> revise, scored by HIDDEN tests (uses quota).

    python3 probes/bench.py --selftest                      # reference solutions vs hidden tests; no quota
    python3 probes/bench.py [--tasks a,b] [--configs claude,codex,pipeline]

Each (task, config) runs in a fresh project and a fresh Axon state under a short /tmp dir. The agent sees
the requirement and a few visible tests (its `ok` check); the harness then runs hidden tests, in a
sandbox without network, on the final result commit. Configs:
  claude / codex   one agent implements (Runner retries once if the visible check fails)
  pipeline         codex implements, claude reviews (read-only), codex revises once if the review asks for changes
  local            the local model implements (needs Ollama; [local] coding is switched on for the run)
  local+review     local implements, claude reviews, local revises once if the review asks for changes
Prints per-cell results and per-config totals; raw numbers also go to the file given by --out."""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from axon import sandbox  # noqa: E402

VISIBLE_HEAD = "import sys\nimport unittest\n\nsys.path.insert(0, 'src')\n"

TASKS = {
    "slugify": {
        "module": "slugify",
        "spec": (
            "Create src/slugify.py defining slugify(text, max_len=None) -> str.\n"
            "Rules: (1) convert accented Latin letters to their ASCII base letter (é->e, ñ->n, ü->u); (2) lowercase; "
            "(3) every run of characters that are not ASCII letters or digits becomes a single '-'; (4) no leading or "
            "trailing '-'; (5) if max_len is given, truncate to at most max_len characters and then remove any trailing "
            "'-' so a cut never leaves one; max_len < 1 raises ValueError; (6) non-str input raises TypeError."),
        "visible": VISIBLE_HEAD + (
            "from slugify import slugify\n\n\nclass V(unittest.TestCase):\n"
            "    def test_basic(self):\n        self.assertEqual(slugify('Hello World'), 'hello-world')\n"
            "    def test_runs(self):\n        self.assertEqual(slugify('a  b'), 'a-b')\n"),
        "hidden": VISIBLE_HEAD + (
            "from slugify import slugify\n\n\nclass H(unittest.TestCase):\n"
            "    def test_punct(self):\n        self.assertEqual(slugify('Hello, World!'), 'hello-world')\n"
            "    def test_accents(self):\n        self.assertEqual(slugify('  Crème Brûlée  '), 'creme-brulee')\n"
            "    def test_runs(self):\n        self.assertEqual(slugify('a---b___c'), 'a-b-c')\n"
            "    def test_only_symbols(self):\n        self.assertEqual(slugify('!!!'), '')\n        self.assertEqual(slugify(''), '')\n"
            "    def test_cut_strips_dash(self):\n        self.assertEqual(slugify('Hello World', max_len=6), 'hello')\n"
            "    def test_cut_exact(self):\n        self.assertEqual(slugify('abc def ghi', max_len=7), 'abc-def')\n"
            "    def test_cut_after_dash(self):\n        self.assertEqual(slugify('abc def ghi', max_len=8), 'abc-def')\n"
            "    def test_max_len_one(self):\n        self.assertEqual(slugify('x', max_len=1), 'x')\n"
            "    def test_bad_max_len(self):\n        for bad in (0, -1):\n            with self.assertRaises(ValueError):\n                slugify('a', max_len=bad)\n"
            "    def test_types(self):\n        for bad in (123, None, b'x'):\n            with self.assertRaises(TypeError):\n                slugify(bad)\n"
            "    def test_upper_accents(self):\n        self.assertEqual(slugify('ÀÉÎÕÜ'), 'aeiou')\n"
            "    def test_digits(self):\n        self.assertEqual(slugify('100% sure'), '100-sure')\n"),
        "reference": (
            "import re\nimport unicodedata\n\n\ndef slugify(text, max_len=None):\n"
            "    if not isinstance(text, str):\n        raise TypeError('text must be str')\n"
            "    if max_len is not None and max_len < 1:\n        raise ValueError('max_len')\n"
            "    t = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode().lower()\n"
            "    t = re.sub(r'[^a-z0-9]+', '-', t).strip('-')\n"
            "    return t if max_len is None else t[:max_len].rstrip('-')\n"),
    },
    "duration": {
        "module": "duration",
        "spec": (
            "Create src/duration.py defining parse_duration(s) -> int, the total number of seconds. Format: one or more "
            "components '<integer><unit>' with units d (86400), h (3600), m (60), s (1). Components must appear in that "
            "descending order (d, h, m, s) and each unit at most once. Whitespace is allowed around the string and between "
            "components, but not between a number and its unit. Integers are digits only (no sign, no decimals; leading "
            "zeros are fine). Anything else raises ValueError: empty or blank string, unknown unit, repeated or "
            "out-of-order units, a number without a unit, a unit without a number. Non-str input raises TypeError. "
            "Examples: '1h30m' -> 5400, '2d' -> 172800, '45s' -> 45, '0s' -> 0."),
        "visible": VISIBLE_HEAD + (
            "from duration import parse_duration\n\n\nclass V(unittest.TestCase):\n"
            "    def test_basic(self):\n        self.assertEqual(parse_duration('1h30m'), 5400)\n        self.assertEqual(parse_duration('45s'), 45)\n"),
        "hidden": VISIBLE_HEAD + (
            "from duration import parse_duration\n\n\nclass H(unittest.TestCase):\n"
            "    def test_all_units(self):\n        self.assertEqual(parse_duration('1d 2h 3m 4s'), 93784)\n"
            "    def test_full(self):\n        self.assertEqual(parse_duration('1h30m15s'), 5415)\n"
            "    def test_padding(self):\n        self.assertEqual(parse_duration('  90s  '), 90)\n"
            "    def test_zero(self):\n        self.assertEqual(parse_duration('0s'), 0)\n"
            "    def test_leading_zeros(self):\n        self.assertEqual(parse_duration('007m'), 420)\n"
            "    def test_value_errors(self):\n        for bad in ('', '   ', '1x', '1h1h', '30m1h', '1.5h', '-5s', 'h', '5', '1 h', '1h-3m', 's1', '1h 1h'):\n"
            "            with self.subTest(bad=bad):\n                with self.assertRaises(ValueError):\n                    parse_duration(bad)\n"
            "    def test_types(self):\n        for bad in (None, 5, 1.5, b'1s'):\n            with self.assertRaises(TypeError):\n                parse_duration(bad)\n"),
        "reference": (
            "import re\n\n_U = {'d': 86400, 'h': 3600, 'm': 60, 's': 1}\n\n\ndef parse_duration(s):\n"
            "    if not isinstance(s, str):\n        raise TypeError('s must be str')\n"
            "    if not re.fullmatch(r'\\s*(?:\\d+[dhms]\\s*)+', s):\n        raise ValueError(s)\n"
            "    parts = re.findall(r'(\\d+)([dhms])', s)\n    order = ['dhms'.index(u) for _, u in parts]\n"
            "    if order != sorted(set(order)):\n        raise ValueError(s)\n"
            "    return sum(int(n) * _U[u] for n, u in parts)\n"),
    },
    "intervals": {
        "module": "intervals",
        "spec": (
            "Create src/intervals.py defining merge_intervals(intervals) -> list of (start, end) tuples. Each interval is "
            "a pair of integers, inclusive on both ends, given as a tuple or a list. Merge intervals that overlap or are "
            "adjacent (e.g. (1,3) and (4,6) merge to (1,6) because 3+1 == 4). Return a NEW list of tuples sorted by start. "
            "Never modify the input or its elements. An interval with start > end raises ValueError; an element that is "
            "not a pair of ints raises TypeError (bool does not count as int, floats are rejected). Empty input returns []."),
        "visible": VISIBLE_HEAD + (
            "from intervals import merge_intervals\n\n\nclass V(unittest.TestCase):\n"
            "    def test_basic(self):\n        self.assertEqual(merge_intervals([(1, 3), (2, 6)]), [(1, 6)])\n"
            "    def test_empty(self):\n        self.assertEqual(merge_intervals([]), [])\n"),
        "hidden": VISIBLE_HEAD + (
            "from intervals import merge_intervals\n\n\nclass H(unittest.TestCase):\n"
            "    def test_classic(self):\n        self.assertEqual(merge_intervals([(1, 3), (2, 6), (8, 10), (15, 18)]), [(1, 6), (8, 10), (15, 18)])\n"
            "    def test_adjacent(self):\n        self.assertEqual(merge_intervals([(1, 3), (4, 6)]), [(1, 6)])\n"
            "    def test_gap(self):\n        self.assertEqual(merge_intervals([(1, 3), (5, 6)]), [(1, 3), (5, 6)])\n"
            "    def test_unsorted(self):\n        self.assertEqual(merge_intervals([(8, 10), (1, 3), (2, 6)]), [(1, 6), (8, 10)])\n"
            "    def test_nested(self):\n        self.assertEqual(merge_intervals([(1, 10), (2, 3)]), [(1, 10)])\n"
            "    def test_lists(self):\n        self.assertEqual(merge_intervals([[1, 2], [2, 3]]), [(1, 3)])\n"
            "    def test_single(self):\n        self.assertEqual(merge_intervals([(5, 5)]), [(5, 5)])\n"
            "    def test_returns_tuples(self):\n        self.assertTrue(all(type(x) is tuple for x in merge_intervals([[1, 2]])))\n"
            "    def test_no_mutation(self):\n        data = [[3, 4], [1, 2]]\n        merge_intervals(data)\n        self.assertEqual(data, [[3, 4], [1, 2]])\n"
            "    def test_value_error(self):\n        with self.assertRaises(ValueError):\n            merge_intervals([(3, 1)])\n"
            "    def test_type_errors(self):\n        for bad in ([(1,)], [(1, 'a')], [(True, 2)], [('a', 'b')], [(1.5, 2)], [5], [(1, 2, 3)]):\n"
            "            with self.subTest(bad=bad):\n                with self.assertRaises(TypeError):\n                    merge_intervals(bad)\n"),
        "reference": (
            "def merge_intervals(intervals):\n    items = []\n    for iv in intervals:\n"
            "        if not isinstance(iv, (tuple, list)) or len(iv) != 2 or any(type(x) is not int for x in iv):\n"
            "            raise TypeError('interval must be a pair of ints')\n"
            "        a, b = iv\n        if a > b:\n            raise ValueError('start > end')\n        items.append((a, b))\n"
            "    items.sort()\n    out = []\n    for a, b in items:\n"
            "        if out and a <= out[-1][1] + 1:\n            out[-1] = (out[-1][0], max(out[-1][1], b))\n"
            "        else:\n            out.append((a, b))\n    return out\n"),
    },
}


# config -> (implementer, reviewer or None); a review that asks for changes triggers one revision by the implementer
CONFIGS = {"claude": ("claude", None), "codex": ("codex", None), "pipeline": ("codex", "claude"),
           "local": ("local", None), "local+review": ("local", "claude")}


def hidden_score(proj, ref, task):
    """(passed, total, failing test names) of the hidden tests on commit `ref`, run in a sandbox without network."""
    with tempfile.TemporaryDirectory(prefix="nvh", dir="/tmp") as d:
        tar = subprocess.run(["git", "-C", str(proj), "archive", ref], capture_output=True, check=True).stdout
        subprocess.run(["tar", "-x", "-C", d], input=tar, check=True)
        Path(d, "tests").mkdir(exist_ok=True)
        Path(d, "tests", "test_hidden.py").write_text(task["hidden"])
        box = sandbox.bwrap(d, rw=[d], net=False, env={"PYTHONDONTWRITEBYTECODE": "1"})
        r = subprocess.run(box + ["python3", "-m", "unittest", "tests.test_hidden", "-v"], capture_output=True, text=True, timeout=120)
    lines = (r.stderr + r.stdout).splitlines()
    ran = [l for l in lines if " ... " in l]
    bad = [l.split(" ")[0] for l in ran if not l.rstrip().endswith("ok")]
    return len(ran) - len(bad), len(ran), bad


def selftest():
    ok = True
    for name, task in TASKS.items():
        with tempfile.TemporaryDirectory(prefix="nvs", dir="/tmp") as d:
            proj = Path(d)
            (proj / "src").mkdir()
            (proj / "src" / f"{task['module']}.py").write_text(task["reference"])
            (proj / "tests").mkdir()
            (proj / "tests" / "test_visible.py").write_text(task["visible"])
            git = ["git", "-C", d, "-c", "user.name=t", "-c", "user.email=t@t"]
            subprocess.run([*git, "init", "-q"], check=True)
            subprocess.run([*git, "add", "-A"], check=True)
            subprocess.run([*git, "commit", "-qm", "ref"], check=True)
            passed, total, bad = hidden_score(proj, "HEAD", task)
            # and a stub that does nothing must fail: the hidden tests have to discriminate
            (proj / "src" / f"{task['module']}.py").write_text(f"def {'slugify' if name == 'slugify' else 'parse_duration' if name == 'duration' else 'merge_intervals'}(*a, **k):\n    return None\n")
            subprocess.run([*git, "commit", "-qam", "stub"], check=True)
            sp, st, _ = hidden_score(proj, "HEAD", task)
        print(f"{name}: reference {passed}/{total} {'OK' if passed == total else 'FAIL ' + str(bad)}; do-nothing stub {sp}/{st}")
        ok = ok and passed == total and sp < st
    sys.exit(not ok)


def run_cell(name, task, config, agents_dir):
    work = Path(tempfile.mkdtemp(prefix="nvb", dir="/tmp"))
    (work / "home/agents").mkdir(parents=True)
    (work / "cfg/projects").mkdir(parents=True)
    for a in ("codex", "claude"):
        if (agents_dir / a).exists():
            (work / "home/agents" / a).symlink_to(agents_dir / a)
    proj = work / "proj"
    (proj / "src").mkdir(parents=True)
    (proj / "tests").mkdir()
    (proj / "tests" / "test_visible.py").write_text(task["visible"])
    (proj / "src" / "__init__.py").write_text("")
    git = ["git", "-C", str(proj), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run([*git, "init", "-q"], check=True)
    subprocess.run([*git, "add", "-A"], check=True)
    subprocess.run([*git, "commit", "-qm", "seed"], check=True)
    (work / "cfg/projects/p.toml").write_text(
        f'path = "{proj}"\n[checks]\nok = "python3 -m unittest discover -s tests -q"\n')
    (work / "cfg/config.toml").write_text("[local]\ncoding = true\nmax_turns = 25\nnum_gpu = 99\n")
    os.environ.update(AXON_HOME=str(work / "home"), AXON_CONFIG=str(work / "cfg"))
    from axon import runtime, usage
    s = runtime.open_store()
    rt = runtime.Runtime(s)
    scope = ["src", "tests"]
    t0 = time.time()
    stages, final = [], None

    def stage(label, tid):
        row = s.one("select status, note from tasks where id = ?", tid)
        stages.append(f"{label}:{row['status']}")
        return row["status"]

    implementer, reviewer = CONFIGS[config]
    tid, _ = runtime.add_task(s, "p", implementer, task["spec"], scope)
    rt.run_until_idle(900)
    if stage("impl", tid) == "COMPLETED":
        final = tid
        if reviewer:
            runtime.request_review(s, tid, reviewer)
            rt.run_until_idle(900)
            verdict = runtime.reviews(s, tid)[0]["verdict"] if runtime.reviews(s, tid) else "none"
            stages.append(f"review:{verdict}")
            if verdict == "changes":
                rid, _ = runtime.revise(s, tid, implementer)
                rt.run_until_idle(900)
                if stage("revise", rid) == "COMPLETED":
                    final = rid
    elapsed = time.time() - t0
    head = s.one("select head from tasks where id = ?", final)["head"] if final else None
    score = hidden_score(proj, head, task) if head else (0, sum(1 for _ in range(1)), ["no result"])
    rep = usage.report(s, 0)
    total = {k: sum(r[k] for r in rep.values()) for k in ("attempts", "seconds", "prompt_bytes", "input", "cached", "output", "cost_usd", "with_usage")}
    shutil.rmtree(work, ignore_errors=True)
    return {"task": name, "config": config, "stages": stages, "hidden_pass": score[0], "hidden_total": score[1], "hidden_fail": score[2],
            "wall_s": round(elapsed), **{k: (round(v, 3) if isinstance(v, float) else v) for k, v in total.items()}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--tasks", default=",".join(TASKS))
    ap.add_argument("--configs", default="claude,codex,pipeline", help=",".join(CONFIGS))
    ap.add_argument("--out")
    args = ap.parse_args()
    if args.selftest:
        selftest()
    agents_dir = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "axon" / "agents"
    results = []
    for name in args.tasks.split(","):
        for config in args.configs.split(","):
            r = run_cell(name, TASKS[name], config, agents_dir)
            results.append(r)
            print(f"{name:<10} {config:<9} hidden {r['hidden_pass']}/{r['hidden_total']} | {' '.join(r['stages'])} | attempts {r['attempts']} "
                  f"| {r['wall_s']}s wall | prompt {r['prompt_bytes']}B | in {r['input']} (cached {r['cached']}) out {r['output']} | ${r['cost_usd']}"
                  + (f" | FAIL {r['hidden_fail'][:3]}" if r["hidden_fail"] else ""), flush=True)
    if args.out:
        Path(args.out).write_text(json.dumps(results, indent=1))


if __name__ == "__main__":
    main()
