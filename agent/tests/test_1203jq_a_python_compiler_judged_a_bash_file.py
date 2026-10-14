"""#1203jq: mutate.py judged every target with py_compile, including shell targets.

`scripts/mutate.py` exists so a harness failure never looks like a finding: it invented the
BROKEN verdict for "the mutant does not compile" so that a syntax-broken mutant could not be
reported MISSED. The first shell target it was ever pointed at (`scripts/reclaim_generated.sh`,
#1203jp) came back as four BROKEN lines reading "the mutant does not compile" — and all four
mutants were valid bash. It told the truth about nothing-was-tested while naming a cause that
was false, which in this tool is the near-miss of the exact failure it was built to prevent.

The fix dispatches on language and returns None when there is no checker, because True would
let a broken mutant run and come back MISSED (#1202qm: no fallback that masks a failure).
"""
import importlib.util
import json
import os
import re
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
MUTATE = os.path.join(REPO, "scripts", "mutate.py")
PYBIN = os.environ.get("SUITE_PYTHON") or "python3"


def _mod():
    spec = importlib.util.spec_from_file_location("_mut_1203jq", MUTATE)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_the_checker_follows_the_language(tmp_path):
    m = _mod()
    sh = os.path.join(str(tmp_path), "a.sh")
    py = os.path.join(str(tmp_path), "a.py")
    dat = os.path.join(str(tmp_path), "a.conf")
    hash_py = os.path.join(str(tmp_path), "runme")
    hash_sh = os.path.join(str(tmp_path), "runme2")
    open(sh, "w").write("echo hi\n")
    open(py, "w").write("x = 1\n")
    open(dat, "w").write("key = value\n")
    open(hash_py, "w").write("#!/usr/bin/env python3\nx = 1\n")
    open(hash_sh, "w").write("#!/bin/bash\necho hi\n")

    assert m._syntax_checker(sh) is m._sh_ok
    assert m._syntax_checker(py) is m._py_ok
    assert m._syntax_checker(hash_py) is m._py_ok
    assert m._syntax_checker(hash_sh) is m._sh_ok
    assert m._syntax_checker(dat) is None, (
        "an unknown language got a checker; a broken mutant would run and report MISSED"
    )


def test_bash_syntax_is_judged_by_bash(tmp_path):
    m = _mod()
    good = os.path.join(str(tmp_path), "good.sh")
    bad = os.path.join(str(tmp_path), "bad.sh")
    open(good, "w").write("if true; then echo hi; fi\n")
    open(bad, "w").write("if true; then echo hi\n")          # no `fi`
    assert m._sh_ok(good) is True
    assert m._sh_ok(bad) is False
    # The regression itself: py_compile calls BOTH of them broken, which is how four valid
    # bash mutants came back as "the mutant does not compile".
    assert m._py_ok(good) is False and m._py_ok(bad) is False


def _spec(tmp_path, target, test_file, find, replace):
    s = {"file": os.path.relpath(target, REPO), "test": os.path.relpath(test_file, os.path.join(REPO, "agent")),
         "mutations": [{"label": "m", "find": find, "replace": replace}]}
    p = os.path.join(str(tmp_path), "spec.json")
    open(p, "w").write(json.dumps(s))
    return p


def _fixture_shell_target(tmp_path):
    """A shell script under the repo plus a test that asserts on its output."""
    tgt = os.path.join(REPO, "scripts", "_tmp_1203jq_target.sh")
    tst = os.path.join(REPO, "agent", "tests", "_tmp_1203jq_check.py")
    open(tgt, "w").write("#!/usr/bin/env bash\necho MARKER_OK\n")
    open(tst, "w").write(
        "import os, subprocess\n"
        "def test_marker():\n"
        "    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',\n"
        "                     'scripts', '_tmp_1203jq_target.sh')\n"
        "    out = subprocess.run(['bash', p], capture_output=True, text=True).stdout\n"
        "    assert 'MARKER_OK' in out, out\n"
    )
    return tgt, tst


def _run(spec):
    p = subprocess.run([PYBIN, MUTATE, spec], capture_output=True, text=True,
                       cwd=REPO, timeout=600)
    return p.returncode, p.stdout + p.stderr


def test_a_valid_bash_mutation_is_caught_not_broken(tmp_path):
    tgt, tst = _fixture_shell_target(tmp_path)
    try:
        rc, out = _run(_spec(tmp_path, tgt, tst, "echo MARKER_OK", "echo SOMETHING_ELSE"))
        assert "CAUGHT" in out, out
        assert "does not compile" not in out, (
            "a valid bash mutant was still judged by a Python compiler:\n%s" % out
        )
        assert rc == 0, (rc, out)
    finally:
        for f in (tgt, tst):
            os.path.exists(f) and os.remove(f)


def test_a_broken_bash_mutation_is_reported_broken(tmp_path):
    tgt, tst = _fixture_shell_target(tmp_path)
    try:
        rc, out = _run(_spec(tmp_path, tgt, tst, "echo MARKER_OK", 'if true; then echo x'))
        assert "BROKEN" in out, out
        assert "MISSED" not in out, (
            "a bash mutant that cannot parse was reported as a surviving mutation:\n%s" % out
        )
        assert rc != 0, (rc, out)
    finally:
        for f in (tgt, tst):
            os.path.exists(f) and os.remove(f)


def test_an_unknown_language_is_refused_before_anything_runs(tmp_path):
    tgt = os.path.join(REPO, "scripts", "_tmp_1203jq_target.conf")
    tst = os.path.join(REPO, "agent", "tests", "_tmp_1203jq_check.py")
    open(tgt, "w").write("marker = ok\n")
    open(tst, "w").write("def test_nothing():\n    assert True\n")
    try:
        rc, out = _run(_spec(tmp_path, tgt, tst, "marker = ok", "marker = changed"))
        assert rc == 2, (rc, out)
        assert "refusing to mutate" in out, out
        # Anchored on the VERDICT COLUMN, not on the words: the refusal sentence itself says
        # "would run and report MISSED", and a substring test for "MISSED" is satisfied by my
        # own prose. Same shape as #1203ji/#1203jj -- an assertion a comment can pass.
        verdict_lines = [l for l in out.splitlines()
                         if re.match(r"^  (CAUGHT|MISSED|NOT APPLIED|BROKEN) ", l)]
        assert verdict_lines == [], verdict_lines
        assert open(tgt).read() == "marker = ok\n", "the refused target was modified anyway"
    finally:
        for f in (tgt, tst):
            os.path.exists(f) and os.remove(f)
