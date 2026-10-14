#!/usr/bin/env python3
"""Run falsification mutations against a test file, and never blur a harness error with a
result.

Written because the hand-rolled version of this failed TWICE in one session (2026-10-14,
#1203ji) and both times the failure looked like a finding:

  * a `sed` whose quoting never matched applied NOTHING and the harness printed
    `MISSED  <- M4 the original relative-URL advice lost`. I read that as "my test is too
    weak", went to tighten the test, and only noticed because I re-applied the same
    mutation in python with a count assertion and it CAUGHT.
  * a mutation that replaced `try:` with `if False:` left an orphan `except`, so pytest
    could not COLLECT the module. The harness printed `MISSED` again — a syntax error in
    the mutant reported as a surviving mutation.

That is the exact shape `verify_shipped_fixes.py` beside this file exists to prevent: a
check that cannot tell "looked and found nothing" from "never looked" reports a silence as
a pass. #826's own header says it too — "a check that lives in a habit is not a check" —
and mutation discipline has lived in a habit here for every patch so far.

Four verdicts, never blurred:

    CAUGHT       the mutant made the test fail. The test has falsifying power here.
    MISSED       the mutant compiled, ran, and the test still PASSED. A real gap.
    NOT APPLIED  the anchor did not appear EXACTLY once. Nothing was tested.
    BROKEN       the mutant does not compile, or the test module cannot be collected.
                 Nothing was tested either, and this is NOT evidence about the test.

Exit code is 0 only when every mutation is CAUGHT. MISSED, NOT APPLIED and BROKEN all
exit non-zero, and the summary says which is which.

It also refuses to start unless the BASELINE is green: against a red test file every
mutation would read CAUGHT, which is the same false comfort one level up.

Usage:
    scripts/mutate.py spec.json
    cat spec.json | scripts/mutate.py -

    {"file": "agent/env_generator/.../orchestrator.py",
     "test": "tests/test_1203jh_....py",
     "mutations": [{"label": "the clause is never built",
                    "find": "if _tags1203jh:", "replace": "if False:"}]}

`file` is relative to the repo root; `test` is relative to `agent/` (the suite's own cwd,
so a path copied from `scripts/suite.sh` output works unchanged).
"""
import hashlib
import json
import os
import py_compile
import shutil
import subprocess
import sys
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PY = os.environ.get("SUITE_PYTHON", "/home/haibotong/miniconda3/envs/dt/bin/python")

CAUGHT, MISSED, NOT_APPLIED, BROKEN = "CAUGHT", "MISSED", "NOT APPLIED", "BROKEN"


def _sha(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def _run_test(test_rel):
    """(passed, tail) for one pytest run; `passed is None` means pytest could not run it.

    ★ CLASSIFIED BY EXIT CODE, NOT BY SUBSTRING. The first version looked for "error
    during collection" in the output, and this tool's own test suite broke it: a test that
    feeds the harness the string "error during collection" as DATA put that substring into
    pytest's failure report, so a genuinely CAUGHT mutation came back BROKEN. The predicate
    was matching the payload instead of the status — found by mutating this file with this
    file (#1203ji's M3). pytest's codes are the mechanical answer: 0 passed, 1 tests
    failed, 2/3/4 interrupted or internal, 5 nothing collected.
    """
    p = subprocess.run([_PY, "-m", "pytest", test_rel, "-q", "--no-header"],
                       cwd=os.path.join(_ROOT, "agent"),
                       capture_output=True, text=True, timeout=900)
    out = (p.stdout or "") + (p.stderr or "")
    tail = " ".join(out.strip().splitlines()[-2:])[:200]
    if p.returncode == 0:
        return True, tail
    if p.returncode == 1:
        return False, tail                     # tests ran and failed: real evidence
    return None, tail                          # could not run them: no evidence at all


def _py_ok(path):
    try:
        py_compile.compile(path, cfile=os.path.join(tempfile.gettempdir(), "_mut.pyc"),
                           doraise=True)
        return True
    except Exception:
        return False


def _sh_ok(path):
    return subprocess.run(["bash", "-n", path], capture_output=True).returncode == 0


def _syntax_checker(path):
    """The syntax checker for THIS target, or None when there is no checker for its language.

    #1203jq: the first version hard-wired py_compile, so the first shell target it was ever
    pointed at (`scripts/reclaim_generated.sh`) reported all four mutations BROKEN — "the
    mutant does not compile" — when every mutant was valid bash. A Python compiler's verdict
    on a bash file is not evidence about the mutant, and BROKEN is the verdict this tool
    invented precisely so a harness failure would stop looking like a finding. It told the
    truth (nothing was tested) while naming the wrong cause, which is the next best thing to
    a lie in a tool whose whole job is keeping those two apart.

    Returning None rather than True for an unknown language is the point: `True` would let a
    syntactically broken mutant run and come back MISSED, i.e. a harness failure reported as
    a gap in the test — the one outcome this file exists to make impossible. #1202qm/#1202qn:
    a fallback that masks a failure is worse than no fallback, so main() refuses to start.
    """
    ext = os.path.splitext(path)[1].lower()
    if ext == ".py":
        return _py_ok
    if ext in (".sh", ".bash"):
        return _sh_ok
    try:
        with open(path, encoding="utf-8", errors="ignore") as fh:
            first = fh.readline()
    except Exception:
        return None
    if first.startswith("#!"):
        if "python" in first:
            return _py_ok
        if "bash" in first or "sh" in first:
            return _sh_ok
    return None


def main(argv):
    if len(argv) != 2:
        print(__doc__)
        return 2
    spec = json.load(sys.stdin) if argv[1] == "-" else json.load(open(argv[1]))
    target = os.path.join(_ROOT, spec["file"])
    test_rel = spec["test"]
    muts = spec["mutations"] or []
    if not os.path.exists(target):
        print("NOT APPLIED: %s does not exist" % spec["file"])
        return 2
    syntax_ok = _syntax_checker(target)
    if syntax_ok is None:
        print("refusing to mutate %s: no syntax checker for this language, so a broken "
              "mutant would run and report MISSED (#1203jq)." % spec["file"])
        return 2

    before = _sha(target)
    print("baseline:", end=" ", flush=True)
    ok, tail = _run_test(test_rel)
    if ok is None:
        print("BROKEN — the test module cannot be collected: %s" % tail)
        return 2
    if not ok:
        print("RED — %s" % tail)
        print("\nrefusing to mutate: against a red baseline every mutation reads CAUGHT.")
        return 2
    print("green (%s)" % tail)

    backup = tempfile.NamedTemporaryFile(delete=False, suffix=".bak").name
    shutil.copy2(target, backup)
    results = []
    try:
        for m in muts:
            label = str(m.get("label") or m.get("find", "")[:40])
            with open(target, encoding="utf-8") as fh:
                src = fh.read()
            n = src.count(m["find"])
            if n != 1:
                results.append((NOT_APPLIED, label, "anchor appears %d time(s), need 1" % n))
                continue
            with open(target, "w", encoding="utf-8") as fh:
                fh.write(src.replace(m["find"], m["replace"]))
            try:
                if not syntax_ok(target):
                    results.append((BROKEN, label, "the mutant does not compile"))
                    continue
                ok, tail = _run_test(test_rel)
                if ok is None:
                    results.append((BROKEN, label, "collection failed: %s" % tail))
                elif ok:
                    results.append((MISSED, label, tail))
                else:
                    results.append((CAUGHT, label, tail))
            finally:
                shutil.copy2(backup, target)
    finally:
        shutil.copy2(backup, target)
        os.unlink(backup)

    after = _sha(target)
    print()
    for verdict, label, note in results:
        print("  %-11s  %s" % (verdict, label))
        if verdict != CAUGHT:
            print("               %s" % note)
    bad = [r for r in results if r[0] != CAUGHT]
    print("\n%d mutation(s): %d caught, %d not" % (len(results), len(results) - len(bad),
                                                   len(bad)))
    if after != before:
        print("!! the target file was NOT restored (%s -> %s)" % (before[:12], after[:12]))
        return 3
    print("target restored (sha256 %s)" % after[:12])
    return 0 if (results and not bad) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
