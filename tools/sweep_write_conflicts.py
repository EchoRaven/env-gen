#!/usr/bin/env python3
"""Find files the FRAMEWORK and a LANE both write — the tug-of-war class.

#1010's root cause was invisible until someone read `git log --format=%an` on one file:
`LoginPage.jsx` had 95 commits in a single run, 49 by the frontend lane and 46 by the
framework's GitOps Bot, alternating a 12-line componentised page against a 72-line inline one.
The lane's work was deleted 46 times, and the "Restore six registered UI pages" repair tasks
were the visible symptom of an invisible cause.

That was found by accident, on one file, in one run. There are 164 generated projects on disk
and every one is a git repository, so the class can be enumerated instead of stumbled upon.

A file is CONTESTED when both sides commit to it. It is THRASHING when they alternate — the
framework writes, the lane rewrites, repeat — which is the shape that destroys work rather than
merely sharing a file. Alternation is counted as author changes along the commit sequence, so
a file both sides touched once ranks far below one they traded 46 times.

    python3 tools/sweep_write_conflicts.py               # recent runs
    python3 tools/sweep_write_conflicts.py --all         # every generated project
    python3 tools/sweep_write_conflicts.py --selftest
"""
from __future__ import annotations

import argparse
import collections
import pathlib
import subprocess
import sys
from typing import Dict, List, Tuple

REPO = pathlib.Path(__file__).resolve().parents[1]
GEN = REPO / "agent" / "generated"

# The framework commits under these identities; everything else is a lane or a person.
FRAMEWORK_AUTHORS = {"gitops bot", "framework", "envgen", "orchestrator"}


def _git(repo: pathlib.Path, *args: str) -> str:
    try:
        r = subprocess.run(["git", "-C", str(repo), *args],
                           capture_output=True, text=True, timeout=60)
        return r.stdout if r.returncode == 0 else ""
    except Exception:
        return ""


def _is_framework(author: str) -> bool:
    return author.strip().lower() in FRAMEWORK_AUTHORS


def contested_files(repo: pathlib.Path, min_alternations: int = 3
                    ) -> List[Tuple[str, int, int, int]]:
    """[(path, framework_commits, lane_commits, alternations)] sorted by alternations."""
    out: List[Tuple[str, int, int, int]] = []
    names = [n for n in _git(repo, "log", "--all", "--name-only", "--format=").split("\n")
             if n.strip()]
    for path, _ in collections.Counter(names).most_common(400):
        log = _git(repo, "log", "--all", "--format=%an", "--", path)
        authors = [a for a in log.split("\n") if a.strip()]
        if len(authors) < 4:
            continue
        fw = sum(1 for a in authors if _is_framework(a))
        lane = len(authors) - fw
        if fw == 0 or lane == 0:
            continue
        alt = sum(1 for i in range(1, len(authors))
                  if _is_framework(authors[i]) != _is_framework(authors[i - 1]))
        if alt >= min_alternations:
            out.append((path, fw, lane, alt))
    return sorted(out, key=lambda x: -x[3])


def selftest() -> int:
    import tempfile
    d = pathlib.Path(tempfile.mkdtemp())
    _git(d, "init", "-q")
    subprocess.run(["git", "-C", str(d), "config", "user.email", "t@t"], capture_output=True)
    f = d / "page.jsx"
    for i in range(6):
        who = "GitOps Bot" if i % 2 == 0 else "frontend"
        f.write_text(f"v{i}\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(d), "add", "-A"], capture_output=True)
        subprocess.run(["git", "-C", str(d), "-c", f"user.name={who}",
                        "commit", "-q", "-m", f"c{i}"], capture_output=True)
    got = contested_files(d)
    assert got, "an alternating file must be reported"
    path, fw, lane, alt = got[0]
    assert path == "page.jsx" and fw == 3 and lane == 3 and alt == 5, got
    # a file only the framework touches must NOT be reported
    g = d / "solo.txt"
    for i in range(4):
        g.write_text(f"v{i}\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(d), "add", "-A"], capture_output=True)
        subprocess.run(["git", "-C", str(d), "-c", "user.name=GitOps Bot",
                        "commit", "-q", "-m", f"s{i}"], capture_output=True)
    assert not [x for x in contested_files(d) if x[0] == "solo.txt"], "single-author file leaked"
    print("selftest OK")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--all", action="store_true", help="every generated project, not just recent")
    ap.add_argument("--min", type=int, default=3, help="minimum alternations to report")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()

    repos = sorted(p for p in GEN.iterdir() if (p / ".git").is_dir())
    if not a.all:
        repos = repos[-12:]
    print(f"scanning {len(repos)} generated project(s) for framework/lane write conflicts\n")
    if not repos:
        print("  no git-backed projects found — nothing was scanned (not 'nothing found')")
        return 1

    totals: Dict[str, List[int]] = collections.defaultdict(lambda: [0, 0, 0, 0])
    for repo in repos:
        for path, fw, lane, alt in contested_files(repo, a.min):
            t = totals[path]
            t[0] += fw
            t[1] += lane
            t[2] += alt
            t[3] += 1

    if not totals:
        print(f"  no contested files at >={a.min} alternations across {len(repos)} projects")
        return 0
    print(f"  {'file':52s} {'fw':>5} {'lane':>5} {'alt':>5} {'runs':>5}")
    for path, (fw, lane, alt, runs) in sorted(totals.items(), key=lambda x: -x[1][2])[:25]:
        print(f"  {path[:52]:52s} {fw:5d} {lane:5d} {alt:5d} {runs:5d}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
