"""#1203gc -- every test root in this repo must be inside the gate that approves patches.

`scripts/suite.sh` is the gate: a patch lands when it is green. Its default was `tests/` alone,
which from `agent/` means `agent/tests/`. Two other roots exist and neither was ever run by it:

    env_generator/llm_generator/multi_agent/tests/    78 tests, 1.9s
    ../tests/                                         41 tests, 1.7s

119 tests on live product modules -- lifecycle, database_scaffold, oauth_scaffold, mcp_scaffold,
dockerfile_lint, codehub.service, the approval endpoints, multitenant auth -- all passing, all
outside the gate since 2026-06-18 (3b71e337 made them local-only; `agent/tests` is local-only
too and IS run, so untracked was never the reason). `lifecycle.py` is the canonical
endpoint-kind predicate module, and #1203fy changed its callers while only agent/tests ran.

The failure mode is silence: a root nobody passes to pytest reports nothing, exactly like a test
that asserts nothing. This pins the gate's reach so a new `tests/` directory cannot slip out of
it, and requires any deliberate exclusion to be DECLARED (pyproject's norecursedirs) rather than
simply not mentioned anywhere.
"""

from __future__ import annotations

import re
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]
REPO = AGENT_DIR.parent
SUITE_SH = REPO / "scripts" / "suite.sh"
PYPROJECT = REPO / "pyproject.toml"

_SKIP_PARTS = {"generated", "node_modules", "__pycache__", ".git", "worktrees", "venv", ".venv"}


def _discover_test_roots():
    """Directories literally named `tests` that hold at least one `test_*.py`.

    Only `tests`-named directories: `multi_agent/runtime/` holds `test_user_runner.py` and
    friends, which are the test-USER squad -- product modules whose names happen to start with
    `test_`, not tests.
    """
    found = []
    for d in REPO.rglob("tests"):
        if not d.is_dir():
            continue
        if _SKIP_PARTS & set(d.relative_to(REPO).parts):
            continue
        if any(d.glob("test_*.py")) or any(d.rglob("test_*.py")):
            found.append(d)
    return sorted(found)


def _suite_default_roots():
    """The roots suite.sh passes to pytest when invoked with no arguments, resolved absolutely.

    suite.sh runs pytest from `agent/`, so its entries are relative to that.
    """
    src = SUITE_SH.read_text(encoding="utf-8")
    m = re.search(r"for _root in ([^;\n]+); do", src)
    assert m, "suite.sh no longer builds its default roots in a `for _root in ...` loop"
    return [(AGENT_DIR / tok).resolve() for tok in m.group(1).split()]


def _declared_exclusions():
    src = PYPROJECT.read_text(encoding="utf-8")
    m = re.search(r"norecursedirs\s*=\s*\[([^\]]*)\]", src)
    if not m:
        return []
    return [(REPO / p.strip().strip("'\"")).resolve()
            for p in m.group(1).split(",") if p.strip()]


def test_every_test_root_is_either_in_the_gate_or_declared_excluded():
    covered = _suite_default_roots()
    excluded = _declared_exclusions()
    missing = []
    for root in _discover_test_roots():
        r = root.resolve()
        if any(r == c or c in r.parents for c in covered):
            continue
        if any(r == e or e in r.parents for e in excluded):
            continue
        missing.append(str(r.relative_to(REPO)))
    assert not missing, (
        "These test roots run in no gate. Add them to the `for _root in ...` list in "
        "scripts/suite.sh, or declare the exclusion in pyproject's norecursedirs:\n  "
        + "\n  ".join(missing))


def test_the_gate_really_names_the_two_roots_that_were_missing():
    """A counter-test: the assertion above passes trivially if suite.sh lists everything by
    accident. These two are the ones that were outside it, named explicitly."""
    covered = {str(p) for p in _suite_default_roots()}
    for rel in ("tests", "env_generator/llm_generator/multi_agent/tests"):
        assert str((AGENT_DIR / rel).resolve()) in covered, rel
    assert str((REPO / "tests").resolve()) in covered


def test_bundled_tests_are_excluded_on_purpose_not_by_omission():
    """`bundled_tests/` ships INTO generated apps; it must stay out, but by declaration."""
    bundled = (AGENT_DIR / "env_generator" / "llm_generator" / "multi_agent"
               / "bundled_tests").resolve()
    if not bundled.is_dir():
        return
    assert any(bundled == e or e in bundled.parents for e in _declared_exclusions()), (
        "bundled_tests is no longer in pyproject's norecursedirs")


def test_no_two_roots_share_a_test_file_basename():
    """pytest imports test modules by basename when there is no package `__init__.py`, so one
    name in two roots is a hard collection error for the whole session -- not a skip, not a
    failure in that file: `Interrupted: 1 error during collection`, nothing runs.

    #1203gc hit exactly this: `test_fallback_audit_gaming.py` existed in both `agent/tests/` and
    `tests/`, and the two files had nothing in common (the root one tested #228's convergence
    grace and was simply misnamed). It only surfaced when the gate began running both roots,
    which is also the moment it could take the entire suite down.
    """
    import collections
    seen = collections.defaultdict(list)
    for root in _suite_default_roots():
        if not root.is_dir():
            continue
        for path in root.rglob("test_*.py"):
            seen[path.name].append(str(path.relative_to(REPO)))
    clashes = {n: v for n, v in seen.items() if len(v) > 1}
    assert not clashes, (
        "One basename in two roots stops pytest collecting ANY test. Rename one:\n  "
        + "\n  ".join("%s -> %s" % (n, v) for n, v in sorted(clashes.items())))

