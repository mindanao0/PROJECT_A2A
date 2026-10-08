"""Phase 5 experiment: does a proposal -> critique -> implement chain beat implementing directly? (uses quota)

    python3 probes/debate.py --selftest                 # reference solutions and a do-nothing stub vs the hidden tests; no quota
    python3 probes/debate.py [--tasks a,b] [--reps 2] [--out file.json]

Conditions, all at the lowest settings (Claude haiku/low, Codex low), scored by HIDDEN tests on the final commit:
  direct   Claude implements the requirement
  debate   Claude writes notes/plan.md, Codex appends a critique, Claude implements following both
No debate system exists in Axon: the chain is three ordinary tasks joined with --after and verified per task with
--check, which is the point of the experiment: measure before building anything."""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import bench  # noqa: E402  (hidden_score, VISIBLE_HEAD)

HEAD = bench.VISIBLE_HEAD

TASKS = {
    "semver": {
        "module": "semver", "stub": "def compare(a, b):\n    return None\n",
        "spec": (
            "Create src/semver.py defining compare(a, b) -> -1, 0 or 1: SemVer 2.0.0 precedence of two version strings. "
            "A version is MAJOR.MINOR.PATCH with an optional -PRERELEASE and an optional +BUILD. Rules: (1) MAJOR, MINOR and PATCH "
            "compare numerically. (2) A version with a prerelease has LOWER precedence than the same version without one. "
            "(3) Two prereleases compare their dot-separated identifiers left to right: identifiers made only of digits compare "
            "numerically; other identifiers compare lexically in ASCII order; a numeric identifier always has lower precedence "
            "than a non-numeric one; when all shared identifiers are equal, the prerelease with more identifiers has higher precedence. "
            "(4) Build metadata is ignored. (5) One leading 'v' is accepted ('v1.2.3'). (6) ValueError for an invalid version: missing "
            "parts or extra parts, a numeric part (including a numeric prerelease identifier) with a leading zero, an empty "
            "identifier, or any character other than ASCII letters, digits and hyphen inside prerelease and build. (7) TypeError for non-str."),
        "visible": HEAD + ("from semver import compare\n\n\nclass V(unittest.TestCase):\n"
                           "    def test_basic(self):\n        self.assertEqual(compare('1.2.3', '1.2.4'), -1)\n        self.assertEqual(compare('2.0.0', '1.9.9'), 1)\n"
                           "    def test_equal(self):\n        self.assertEqual(compare('1.0.0', '1.0.0'), 0)\n"),
        "hidden": HEAD + (
            "from semver import compare\n\n\nclass H(unittest.TestCase):\n"
            "    def test_spec_chain(self):\n"
            "        chain = ['1.0.0-alpha', '1.0.0-alpha.1', '1.0.0-alpha.beta', '1.0.0-beta', '1.0.0-beta.2', '1.0.0-beta.11', '1.0.0-rc.1', '1.0.0']\n"
            "        for i in range(len(chain) - 1):\n            with self.subTest(a=chain[i], b=chain[i + 1]):\n"
            "                self.assertEqual(compare(chain[i], chain[i + 1]), -1)\n                self.assertEqual(compare(chain[i + 1], chain[i]), 1)\n"
            "    def test_numeric_not_lexical(self):\n        self.assertEqual(compare('1.0.0', '1.0.0'), 0)\n        self.assertEqual(compare('1.10.0', '1.9.0'), 1)\n        self.assertEqual(compare('1.0.0-2', '1.0.0-10'), -1)\n"
            "    def test_build_ignored(self):\n        self.assertEqual(compare('1.0.0+a', '1.0.0+b'), 0)\n        self.assertEqual(compare('1.0.0-rc.1+x', '1.0.0-rc.1'), 0)\n"
            "    def test_leading_v(self):\n        self.assertEqual(compare('v1.2.3', '1.2.3'), 0)\n        self.assertEqual(compare('v1.2.3', 'v1.2.4'), -1)\n"
            "    def test_numeric_below_alpha(self):\n        self.assertEqual(compare('1.0.0-1', '1.0.0-a'), -1)\n"
            "    def test_hyphen_inside_identifier(self):\n        self.assertEqual(compare('1.0.0-a-b', '1.0.0-a-c'), -1)\n"
            "    def test_value_errors(self):\n"
            "        for bad in ('', '1.2', '1.2.3.4', '01.2.3', '1.02.3', '1.2.03', '1.2.3-01', '1.2.3-', '1.2.3-a..b', '1.2.3-é', '1.2.3+', '1.2.-3', 'vv1.2.3', ' 1.2.3', '1.2.3-a_b'):\n"
            "            with self.subTest(bad=bad):\n                with self.assertRaises(ValueError):\n                    compare(bad, '1.0.0')\n                with self.assertRaises(ValueError):\n                    compare('1.0.0', bad)\n"
            "    def test_zero_parts_are_fine(self):\n        self.assertEqual(compare('0.0.0', '0.0.1'), -1)\n        self.assertEqual(compare('1.0.0-0', '1.0.0-0'), 0)\n"
            "    def test_types(self):\n        for bad in (None, 1, 1.0, b'1.0.0'):\n            with self.assertRaises(TypeError):\n                compare(bad, '1.0.0')\n"),
        "reference": (
            "import re\n\n_ID = r'[0-9A-Za-z-]+'\n_RE = re.compile(r'^v?(0|[1-9]\\d*)\\.(0|[1-9]\\d*)\\.(0|[1-9]\\d*)(?:-(' + _ID + r'(?:\\.' + _ID + r')*))?(?:\\+(' + _ID + r'(?:\\.' + _ID + r')*))?$')\n\n\n"
            "def _parse(v):\n    if not isinstance(v, str):\n        raise TypeError('version must be str')\n    m = _RE.match(v)\n    if not m:\n        raise ValueError(v)\n"
            "    pre = m.group(4).split('.') if m.group(4) is not None else None\n"
            "    if pre and any(p.isdigit() and len(p) > 1 and p[0] == '0' for p in pre):\n        raise ValueError(v)\n"
            "    return tuple(int(x) for x in m.groups()[:3]), pre\n\n\n"
            "def _cmp(a, b):\n    return (a > b) - (a < b)\n\n\n"
            "def compare(a, b):\n    (na, pa), (nb, pb) = _parse(a), _parse(b)\n    if na != nb:\n        return _cmp(na, nb)\n"
            "    if pa is None or pb is None:\n        return _cmp(pa is None, pb is None)\n"
            "    for x, y in zip(pa, pb):\n        if x == y:\n            continue\n        xn, yn = x.isdigit(), y.isdigit()\n"
            "        if xn and yn:\n            return _cmp(int(x), int(y))\n        if xn != yn:\n            return -1 if xn else 1\n        return _cmp(x, y)\n"
            "    return _cmp(len(pa), len(pb))\n"),
    },
    "wrap": {
        "module": "wrap", "stub": "def wrap(text, width):\n    return None\n",
        "spec": (
            "Create src/wrap.py defining wrap(text, width) -> list of lines. Rules: (1) Ignore leading and trailing whitespace of the whole text; "
            "if nothing remains return []. (2) Each newline in the text starts a new paragraph line: every input line is wrapped independently, "
            "and an empty input line produces an empty string '' in the result. (3) Within a line, runs of spaces collapse to one space and "
            "leading/trailing spaces of the line are dropped. (4) Greedy fill: put as many words on an output line as fit in width characters "
            "(words separated by exactly one space). (5) A word longer than width is cut into chunks of exactly width characters (the last chunk "
            "may be shorter); the full chunks each take their own output line, and the short remainder starts the next line, where following "
            "words may be added if they fit. (6) width < 1 raises ValueError, a bool or non-int width raises TypeError, non-str text raises TypeError."),
        "visible": HEAD + ("from wrap import wrap\n\n\nclass V(unittest.TestCase):\n"
                           "    def test_basic(self):\n        self.assertEqual(wrap('aaa bbb ccc', 7), ['aaa bbb', 'ccc'])\n"
                           "    def test_empty(self):\n        self.assertEqual(wrap('', 5), [])\n"),
        "hidden": HEAD + (
            "from wrap import wrap\n\n\nclass H(unittest.TestCase):\n"
            "    def test_greedy(self):\n        self.assertEqual(wrap('the quick brown fox jumps', 10), ['the quick', 'brown fox', 'jumps'])\n"
            "    def test_exact_fit(self):\n        self.assertEqual(wrap('abc def', 7), ['abc def'])\n        self.assertEqual(wrap('abc def', 6), ['abc', 'def'])\n"
            "    def test_long_word_split(self):\n        self.assertEqual(wrap('abcdefghij', 4), ['abcd', 'efgh', 'ij'])\n"
            "    def test_remainder_is_joined_by_following_words(self):\n        self.assertEqual(wrap('abcdefghij kl', 4), ['abcd', 'efgh', 'ij', 'kl'])\n        self.assertEqual(wrap('abcdefghij k', 4), ['abcd', 'efgh', 'ij k'])\n"
            "    def test_exact_multiple_has_no_empty_remainder(self):\n        self.assertEqual(wrap('abcdefgh', 4), ['abcd', 'efgh'])\n"
            "    def test_long_word_after_text(self):\n        self.assertEqual(wrap('hi abcdefgh', 4), ['hi', 'abcd', 'efgh'])\n"
            "    def test_spaces_collapse_and_trim(self):\n        self.assertEqual(wrap('  a    b  ', 10), ['a b'])\n        self.assertEqual(wrap('a  b\\n', 10), ['a b'])\n"
            "    def test_lines_are_independent(self):\n        self.assertEqual(wrap('aa bb\\ncc', 5), ['aa bb', 'cc'])\n        self.assertEqual(wrap('aa\\nbb', 10), ['aa', 'bb'])\n"
            "    def test_blank_line_is_kept(self):\n        self.assertEqual(wrap('a\\n\\nb', 5), ['a', '', 'b'])\n        self.assertEqual(wrap('a\\n   \\nb', 5), ['a', '', 'b'])\n"
            "    def test_whitespace_only(self):\n        self.assertEqual(wrap('   \\n  ', 5), [])\n"
            "    def test_width_one(self):\n        self.assertEqual(wrap('ab c', 1), ['a', 'b', 'c'])\n"
            "    def test_errors(self):\n        for w in (0, -3):\n            with self.assertRaises(ValueError):\n                wrap('a', w)\n"
            "        for w in (True, 2.5, '3', None):\n            with self.assertRaises(TypeError):\n                wrap('a', w)\n"
            "        for t in (None, 5, b'a'):\n            with self.assertRaises(TypeError):\n                wrap(t, 5)\n"),
        "reference": (
            "def wrap(text, width):\n    if not isinstance(text, str):\n        raise TypeError('text must be str')\n"
            "    if isinstance(width, bool) or not isinstance(width, int):\n        raise TypeError('width must be int')\n"
            "    if width < 1:\n        raise ValueError('width')\n    text = text.strip()\n    if not text:\n        return []\n"
            "    out = []\n    for raw in text.split('\\n'):\n        words = raw.split()\n        if not words:\n            out.append('')\n            continue\n"
            "        line = ''\n        for w in words:\n            while len(w) > width:\n                if line:\n                    out.append(line)\n                    line = ''\n"
            "                out.append(w[:width])\n                w = w[width:]\n"
            "            if not line:\n                line = w\n            elif len(line) + 1 + len(w) <= width:\n                line += ' ' + w\n"
            "            else:\n                out.append(line)\n                line = w\n        if line:\n            out.append(line)\n    return out\n"),
    },
    "ttlcache": {
        "module": "ttlcache", "stub": "class TTLCache:\n    def __init__(self, capacity, ttl, clock=None):\n        pass\n",
        "spec": (
            "Create src/ttlcache.py defining class TTLCache(capacity, ttl, clock=time.monotonic): an LRU cache whose entries also expire. "
            "capacity < 1 or ttl <= 0 raises ValueError. An entry set at time t is expired when clock() >= t + ttl (it expires AT exactly ttl). "
            "set(key, value): inserts or updates, restarts the entry's TTL, and makes it the most recently used; if the cache is then over "
            "capacity, first drop every expired entry, and only if it is still over capacity evict the least recently used entries. "
            "get(key, default=None): returns the value of a live entry, makes it the most recently used but does NOT restart its TTL; an "
            "expired entry is removed and default returned. 'key in cache' and len(cache) count only live entries, drop expired ones, and do "
            "not change recency. pop(key, default=None) removes and returns a live entry's value (default if missing or expired). clear() empties it. "
            "The clock is called at most once per public call and never cached between calls."),
        "visible": HEAD + ("from ttlcache import TTLCache\n\n\nclass V(unittest.TestCase):\n"
                           "    def test_set_get(self):\n        c = TTLCache(2, 10)\n        c.set('a', 1)\n        self.assertEqual(c.get('a'), 1)\n"
                           "    def test_missing(self):\n        self.assertIsNone(TTLCache(2, 10).get('x'))\n"),
        "hidden": HEAD + (
            "from ttlcache import TTLCache\n\n\nclass Clock:\n    def __init__(self):\n        self.t = 0.0\n    def __call__(self):\n        return self.t\n\n\n"
            "class H(unittest.TestCase):\n    def setUp(self):\n        self.clock = Clock()\n"
            "    def make(self, cap=2, ttl=10):\n        return TTLCache(cap, ttl, clock=self.clock)\n"
            "    def test_expires_at_exactly_ttl(self):\n        c = self.make()\n        c.set('a', 1)\n        self.clock.t = 9.99\n        self.assertEqual(c.get('a'), 1)\n"
            "        self.clock.t = 10\n        self.assertIsNone(c.get('a', None))\n        self.assertEqual(c.get('a', 'd'), 'd')\n"
            "    def test_get_does_not_restart_ttl(self):\n        c = self.make()\n        c.set('a', 1)\n        self.clock.t = 6\n        self.assertEqual(c.get('a'), 1)\n"
            "        self.clock.t = 10\n        self.assertNotIn('a', c)\n"
            "    def test_set_restarts_ttl(self):\n        c = self.make()\n        c.set('a', 1)\n        self.clock.t = 6\n        c.set('a', 2)\n        self.clock.t = 12\n        self.assertEqual(c.get('a'), 2)\n"
            "    def test_lru_eviction(self):\n        c = self.make(2)\n        c.set('a', 1)\n        c.set('b', 2)\n        c.get('a')\n        c.set('c', 3)\n"
            "        self.assertIn('a', c)\n        self.assertNotIn('b', c)\n        self.assertIn('c', c)\n"
            "    def test_contains_does_not_touch_recency(self):\n        c = self.make(2)\n        c.set('a', 1)\n        c.set('b', 2)\n        self.assertIn('a', c)\n        c.set('c', 3)\n"
            "        self.assertNotIn('a', c)\n        self.assertIn('b', c)\n"
            "    def test_expired_entries_go_before_lru_victims(self):\n        c = self.make(2, 10)\n        c.set('old', 1)\n        self.clock.t = 5\n        c.set('b', 2)\n        c.get('old')\n"
            "        self.clock.t = 10.5\n        c.set('c', 3)\n        self.assertNotIn('old', c)\n        self.assertIn('b', c)\n        self.assertIn('c', c)\n"
            "    def test_len_counts_only_live(self):\n        c = self.make(5)\n        c.set('a', 1)\n        self.clock.t = 6\n        c.set('b', 2)\n        self.assertEqual(len(c), 2)\n"
            "        self.clock.t = 10\n        self.assertEqual(len(c), 1)\n"
            "    def test_pop(self):\n        c = self.make()\n        c.set('a', 1)\n        self.assertEqual(c.pop('a'), 1)\n        self.assertIsNone(c.pop('a'))\n        c.set('b', 2)\n        self.clock.t = 10\n        self.assertEqual(c.pop('b', 'gone'), 'gone')\n"
            "    def test_clear(self):\n        c = self.make()\n        c.set('a', 1)\n        c.clear()\n        self.assertEqual(len(c), 0)\n"
            "    def test_none_value_is_a_value(self):\n        c = self.make()\n        c.set('a', None)\n        self.assertIn('a', c)\n        self.assertEqual(c.get('a', 'd'), None)\n"
            "    def test_bad_arguments(self):\n        for cap, ttl in ((0, 1), (-1, 1), (1, 0), (1, -5)):\n            with self.assertRaises(ValueError):\n                TTLCache(cap, ttl)\n"),
        "reference": (
            "import time\nfrom collections import OrderedDict\n\n\nclass TTLCache:\n    def __init__(self, capacity, ttl, clock=time.monotonic):\n"
            "        if capacity < 1 or ttl <= 0:\n            raise ValueError('capacity >= 1 and ttl > 0')\n        self.capacity, self.ttl, self.clock = capacity, ttl, clock\n        self.d = OrderedDict()\n\n"
            "    def _purge(self, now):\n        for k in [k for k, (_, t) in self.d.items() if now >= t + self.ttl]:\n            del self.d[k]\n\n"
            "    def set(self, key, value):\n        now = self.clock()\n        self.d[key] = (value, now)\n        self.d.move_to_end(key)\n"
            "        if len(self.d) > self.capacity:\n            self._purge(now)\n        while len(self.d) > self.capacity:\n            self.d.popitem(last=False)\n\n"
            "    def get(self, key, default=None):\n        now = self.clock()\n        if key not in self.d:\n            return default\n        value, t = self.d[key]\n"
            "        if now >= t + self.ttl:\n            del self.d[key]\n            return default\n        self.d.move_to_end(key)\n        return value\n\n"
            "    def __contains__(self, key):\n        now = self.clock()\n        if key not in self.d:\n            return False\n        if now >= self.d[key][1] + self.ttl:\n            del self.d[key]\n            return False\n        return True\n\n"
            "    def __len__(self):\n        self._purge(self.clock())\n        return len(self.d)\n\n"
            "    def pop(self, key, default=None):\n        now = self.clock()\n        if key not in self.d:\n            return default\n        value, t = self.d.pop(key)\n"
            "        return default if now >= t + self.ttl else value\n\n    def clear(self):\n        self.d.clear()\n"),
    },
}


def selftest():
    ok = True
    for name, task in TASKS.items():
        with tempfile.TemporaryDirectory(prefix="nvs", dir="/tmp") as d:
            proj = Path(d)
            for sub in ("src", "tests"):
                (proj / sub).mkdir()
            (proj / "tests" / "test_visible.py").write_text(task["visible"])
            git = ["git", "-C", d, "-c", "user.name=t", "-c", "user.email=t@t"]
            subprocess.run([*git, "init", "-q"], check=True)
            (proj / "src" / f"{task['module']}.py").write_text(task["reference"])
            subprocess.run([*git, "add", "-A"], check=True)
            subprocess.run([*git, "commit", "-qm", "ref"], check=True)
            vis = subprocess.run(["python3", "-m", "unittest", "discover", "-s", "tests", "-q"], cwd=d, capture_output=True, text=True)
            passed, total, bad = bench.hidden_score(proj, "HEAD", task)
            (proj / "src" / f"{task['module']}.py").write_text(task["stub"])
            subprocess.run([*git, "commit", "-qam", "stub"], check=True)
            sp, st, _ = bench.hidden_score(proj, "HEAD", task)
        good = passed == total and vis.returncode == 0 and sp < st
        print(f"{name}: reference visible {'OK' if vis.returncode == 0 else 'FAIL'}, hidden {passed}/{total} {'OK' if passed == total else 'FAIL ' + str(bad)}; do-nothing stub {sp}/{st}")
        ok = ok and good
    sys.exit(not ok)


PLAN = ("Read this requirement and write notes/plan.md: a short design plus an explicit checklist of EVERY rule and edge case you "
        "will implement and test (go rule by rule through the requirement; do not skip any). Do NOT write code under src/. "
        "Requirement:\n\n{spec}")
CRITIQUE = ("A colleague wrote notes/plan.md for the requirement below. Review it like a skeptical reviewer: append a section "
            "'## Critique' to notes/plan.md listing every rule of the requirement that the plan misses or gets wrong, and edge cases "
            "worth testing. Do NOT write code under src/. Requirement:\n\n{spec}")
IMPLEMENT = ("{spec}\n\nA design plan and a critique by a second reviewer are in notes/plan.md. Read it first and follow it; "
             "the requirement above stays authoritative. Run the visible check before you finish.")


def settle(rt, s, limit=900):
    """Run until idle, but stop at once when nothing is running and a task is waiting for a human (REVIEW, WAITING_*,
    FAILED): its dependents would wait for ever. The first full run burned 15 minutes per stalled chain on that."""
    end = time.time() + limit
    while time.time() < end:
        rt.tick()
        if not rt.busy():
            return
        states = {r["status"] for r in s.q("select status from tasks")}
        if "RUNNING" not in states and states & {"REVIEW", "WAITING_INPUT", "WAITING_APPROVAL", "FAILED"}:
            return
        time.sleep(0.2)


def run_cell(name, task, condition, rep, agents_dir):
    work = Path(tempfile.mkdtemp(prefix="nvd", dir="/tmp"))
    for sub in ("home/agents", "cfg/projects", "proj/src", "proj/tests", "proj/notes"):
        (work / sub).mkdir(parents=True)
    for a in ("codex", "claude"):
        (work / "home/agents" / a).symlink_to(agents_dir / a)
    proj = work / "proj"
    (proj / "tests/test_visible.py").write_text(task["visible"])
    (proj / "src/__init__.py").write_text("")
    (proj / "notes/.gitkeep").write_text("")
    git = ["git", "-C", str(proj), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run([*git, "init", "-q"], check=True)
    subprocess.run([*git, "add", "-A"], check=True)
    subprocess.run([*git, "commit", "-qm", "seed"], check=True)
    (work / "cfg/projects/p.toml").write_text(
        f'path = "{proj}"\n[checks]\nok = "python3 -m unittest discover -s tests -q"\nnotes = "test -s notes/plan.md"\n')
    (work / "cfg/config.toml").write_text('[agents]\nclaude_model = "claude-haiku-4-5-20251001"\nclaude_effort = "low"\ncodex_effort = "low"\n')
    os.environ.update(AXON_HOME=str(work / "home"), AXON_CONFIG=str(work / "cfg"))
    from axon import runtime, usage
    s = runtime.open_store()
    rt = runtime.Runtime(s)
    t0 = time.time()
    stages = []
    if condition == "direct":
        tid, _ = runtime.add_task(s, "p", "claude", task["spec"], ["src", "tests"], checks=["ok"])
        final = tid
    else:
        plan, _ = runtime.add_task(s, "p", "claude", PLAN.format(spec=task["spec"]), ["notes"], checks=["notes"])
        crit, _ = runtime.add_task(s, "p", "codex", CRITIQUE.format(spec=task["spec"]), ["notes"], checks=["notes"], after=plan)
        final, _ = runtime.add_task(s, "p", "claude", IMPLEMENT.format(spec=task["spec"]), ["src", "tests"], checks=["ok"], after=crit)
    settle(rt, s)
    for tid in ([final] if condition == "direct" else [plan, crit, final]):
        stages.append(s.one("select status from tasks where id = ?", tid)["status"])
    head = s.one("select head from tasks where id = ?", final)["head"] if stages[-1] == "COMPLETED" else None
    score = bench.hidden_score(proj, head, task) if head else (0, 0, ["no result"])
    plan_text = subprocess.run([*git, "show", f"{head}:notes/plan.md"], capture_output=True, text=True).stdout if head and condition == "debate" else ""
    rep_rows = usage.report(s, 0)
    total = {k: sum(r[k] for r in rep_rows.values()) for k in ("attempts", "seconds", "prompt_bytes", "input", "cached", "output", "cost_usd", "with_usage")}
    shutil.rmtree(work, ignore_errors=True)
    return {"task": name, "condition": condition, "rep": rep, "stages": stages, "hidden_pass": score[0], "hidden_total": score[1],
            "all_pass": bool(score[1]) and score[0] == score[1], "failing": score[2], "wall_s": round(time.time() - t0),
            "plan_chars": len(plan_text), **{k: (round(v, 3) if isinstance(v, float) else v) for k, v in total.items()}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--tasks", default=",".join(TASKS))
    ap.add_argument("--reps", type=int, default=2)
    ap.add_argument("--out")
    args = ap.parse_args()
    if args.selftest:
        selftest()
    agents_dir = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "axon" / "agents"
    results = []
    for rep in range(1, args.reps + 1):
        for name in args.tasks.split(","):
            for condition in ("direct", "debate"):
                r = run_cell(name, TASKS[name], condition, rep, agents_dir)
                results.append(r)
                print(f"{name:<9} {condition:<7} rep{rep} hidden {r['hidden_pass']}/{r['hidden_total']} {'ALL' if r['all_pass'] else '   '} | {' '.join(r['stages'])} "
                      f"| {r['wall_s']}s | in {r['input']} out {r['output']} ${r['cost_usd']}" + (f" | FAIL {r['failing'][:3]}" if r["failing"] else ""), flush=True)
                if args.out:
                    Path(args.out).write_text(json.dumps(results, indent=1))


if __name__ == "__main__":
    main()
