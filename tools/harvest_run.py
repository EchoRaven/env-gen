#!/usr/bin/env python3
"""Harvest one run's log into defect classes — the 收割 step, done the same way twice.

The supervision loop is: 监督 → 收割 → 甄别 → 修复 → 记录 → 重启. The harvest was being
done by hand each round, which made it inconsistent: r157's `syntax error at or near "?"`
was nearly missed because that pass happened to grep for `nullable` rather than the class.
This does the same sweep every time, in one command.

It deliberately does NOT triage. Deciding whether a finding is a framework defect, a
consequence of an upstream failure, correct behaviour, or unlocalizable is the judgement
step and it needs a human reading real code — every automated attempt at it this session
would have been wrong at least once (three consecutive hypotheses about the visual-coverage
gap were all plausible and all false).

    python3 tools/harvest_run.py netflix-web-r158
    python3 tools/harvest_run.py netflix-web-r158 --against netflix-web-r157
    python3 tools/harvest_run.py --selftest
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Signatures of defects already fixed. A non-zero count here is a REGRESSION, which is why
# they are named rather than folded into the generic sweeps.
KNOWN_FIXED = {
    "#969 nullable in DDL": r'syntax error at or near "nullable"',
    "#970 duplicate icon import": r"has already been declared",
    "#971 missing worktree skills": r"not found: \.agents/skills",
    "#973 DDL ? placeholder (now diagnosable, not yet fixed)": r'at or near "\?"',
    "#974 FK ambiguity refused": r"repair DECLINED \(ambiguous owner\)",
}

# NOT defects — activity that is healthy at low volume and pathological in bulk. r158 fired
# the icon heal ONCE with zero duplicate-declaration errors, which is the fix working: a
# genuinely missing icon got imported. r157 fired it 20 times because the heal and the lane
# were overwriting each other. Counting it as a regression turned correct behaviour into a
# FAIL, so it reports as a rate with its baseline instead of a pass/fail.
ACTIVITY = {
    "icon heal fired": (r"imported via lucide-react", "1-2 normal; r157 hit 20 while thrashing"),
    "FK actor narrowed": (r"NARROWED \(#974\)", "a refinement was deduced; r158 refused 90x instead"),
}

# Known and deliberately unfixed — see EXPERIMENTS item 360. Listed so they do not read as
# new findings every round.
KNOWN_UNFIXED = {
    "messagebus target (no loss measured)": r"Target agent not found: messagebus",
    "default_now (one occurrence)": r'syntax error at or near "default_now"',
}

_TS = re.compile(r"^(\d{2}):(\d{2}):(\d{2})")
_HASH = re.compile(r"[0-9a-f]{12,}")
_LINECOL = re.compile(r":\d+:\d+:")
_NUM = re.compile(r"\d+")


def _norm(s: str) -> str:
    """Collapse the parts that differ per occurrence so the CLASS is countable."""
    return _NUM.sub("N", _LINECOL.sub(":L:C:", _HASH.sub("<hash>", s))).strip()


def _log_path(run: str) -> Path:
    p = REPO / f"gm_{run}.log"
    if not p.exists():
        raise SystemExit(f"no log for {run} at {p}")
    return p


def max_log_gap(lines):
    """Largest silence between timestamped lines. A run that is WORKING still writes; the
    r155 lesson is that a big gap means look for a child process, not that it is dead."""
    prev = None
    worst = (0, "")
    for ln in lines:
        m = _TS.match(ln)
        if not m:
            continue
        sec = int(m[1]) * 3600 + int(m[2]) * 60 + int(m[3])
        if prev is not None and sec >= prev and sec - prev > worst[0]:
            worst = (sec - prev, m.group(0))
        prev = sec
    return worst


def harvest(run: str) -> dict:
    lines = _log_path(run).read_text(encoding="utf-8", errors="replace").splitlines()
    blob = "\n".join(lines)

    def _count(pattern):
        return len(re.findall(pattern, blob))

    def _classes(pattern, limit=10):
        return Counter(_norm(m) for m in re.findall(pattern, blob)).most_common(limit)

    gap, gap_at = max_log_gap(lines)
    return {
        "run": run,
        "lines": len(lines),
        "max_gap_s": gap,
        "max_gap_at": gap_at,
        "regressions": {k: _count(v) for k, v in KNOWN_FIXED.items()},
        "activity": {k: (_count(p), note) for k, (p, note) in ACTIVITY.items()},
        "known_unfixed": {k: _count(v) for k, v in KNOWN_UNFIXED.items()},
        "docker_up": _classes(r"docker_up:[^|'\n]{0,120}"),
        "tool_failures": _classes(r"❌ [a-z_]+"),
        "warnings": _classes(r"\[W\] [A-Za-z.]+: [A-Za-z#][^:,(]{0,45}"),
        "exceptions": _classes(r"(?:[A-Za-z]+Error|Exception): [^|\n]{0,70}"),
        "ended": _classes(r"NO-CONVERGENCE|PROJECT DELIVERED|Generation failed|budget_exceeded", 5),
    }


def _print(h: dict, against: dict | None = None) -> None:
    print(f"== {h['run']} — {h['lines']} lines, max silence {h['max_gap_s']}s at {h['max_gap_at']}")

    print("\n-- REGRESSIONS (must be 0)")
    for k, n in h["regressions"].items():
        base = f"   (was {against['regressions'][k]})" if against else ""
        print(f"   {'FAIL' if n else 'ok  '}  {n:5d}  {k}{base}")

    print("\n-- known, deliberately unfixed")
    for k, n in h["known_unfixed"].items():
        print(f"         {n:5d}  {k}")

    print("\n-- activity (a rate, not a verdict)")
    for k, (n, note) in h["activity"].items():
        base = f"   (was {against['activity'][k][0]})" if against else ""
        print(f"         {n:5d}  {k}{base}  — {note}")

    for title, key in (("docker_up failure causes", "docker_up"),
                       ("tool failures", "tool_failures"),
                       ("warning classes", "warnings"),
                       ("exceptions", "exceptions"),
                       ("end signals", "ended")):
        rows = h[key]
        print(f"\n-- {title}" + ("" if rows else "  (none)"))
        for text, n in rows:
            print(f"   {n:5d}  {text[:110]}")

    print("\n-- triage is NOT automated. For each finding above decide: framework defect /"
          "\n   consequence of an upstream failure / correct behaviour / unlocalizable."
          "\n   Only the first gets fixed; record the rest with the reason.")


def selftest() -> int:
    tmp = REPO / f"gm_selftest-harvest.log"
    tmp.write_text(
        "10:00:00 [I] start\n"
        '10:00:05 [W] x: docker_up:9b542e0bae5f ERROR: syntax error at or near "nullable"\n'
        '10:00:06 [W] x: docker_up:aa11bb22cc33 ERROR: syntax error at or near "nullable"\n'
        "10:02:30 [I] ❌ read\n"
        "10:02:31 [I] Target agent not found: messagebus\n"
        "10:02:32 [E] RuntimeError: STUCK — aborted\n",
        encoding="utf-8")
    try:
        h = harvest("selftest-harvest")
        assert h["regressions"]["#969 nullable in DDL"] == 2, h["regressions"]
        assert h["known_unfixed"]["messagebus target (no loss measured)"] == 1
        # activity must NOT be graded pass/fail — a healthy single firing once read as a
        # regression, which is the whole reason this section exists
        assert "icon heal fired" in h["activity"]
        # the two docker_up lines differ only by container hash — they must collapse to ONE
        # class, or every occurrence reads as a separate finding
        assert len(h["docker_up"]) == 1, h["docker_up"]
        assert h["docker_up"][0][1] == 2
        assert h["max_gap_s"] == 144, h["max_gap_s"]
        assert any("RuntimeError" in t for t, _ in h["exceptions"]), h["exceptions"]
        print("selftest OK")
        return 0
    finally:
        tmp.unlink(missing_ok=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run", nargs="?", help="run name, e.g. netflix-web-r158")
    ap.add_argument("--against", help="baseline run to compare regression counts against")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not a.run:
        ap.error("give a run name or --selftest")
    _print(harvest(a.run), harvest(a.against) if a.against else None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
