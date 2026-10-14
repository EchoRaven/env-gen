r"""#1202ar: a detector that returns [] on crash must never be wired into a gate verdict.

#1202ah pinned the count of silent empty-returns inside the two gate modules. This asks the
question one layer out, across the whole framework, and asks it by CONSEQUENCE rather than by
location: of every function that swallows an exception and returns [], which ones have their
result poured into a blocker/finding list?

That combination is the one that ships broken work. `[]` from such a detector means "found no
problems", so a crash inside it reads as a clean verdict and the gate opens. Every other silent
`[]` in the tree is a helper answering "nothing", which is fine — this is why the audit is
scoped to the consumer, not to the shape.

Measured 2026-09-02 across llm_generator/: 288 functions swallow an exception and return an
empty value, 50 of them specifically `[]`, and 15 callsites pour a function's result into an
aggregation. The intersection is EMPTY, and this keeps it empty.

Validated in the direction that matters: the aggregation scan finds all 15 real callsites,
including `_auth_override_blockers_1202s`, so an empty intersection is a real result and not a
regex that matches nothing.

#1203jr: both sides are now validated. Only the aggregation side was, and an intersection is
empty for two reasons -- nothing qualifies, or one operand died. The silent side is pinned by
a measured floor (67 across 31 files today; the biggest single module supplies 8).
"""

import ast
import re
import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
_ROOT = THIS_DIR.parent / "env_generator" / "llm_generator"
sys.path.insert(0, str(_ROOT))

_ANNOUNCES = re.compile(
    r"warn_once_1201|_gate_absent_792|_swallowed_79\d|_not_measured_\d+|degraded"
    r"|logger\.(warning|error)|_logger\.(warning|error)")

# `blockers.extend(f(...))` and friends — the shapes that turn a return value into a verdict.
_AGGREGATION = re.compile(
    r"(blockers|findings|problems|violations|issues)\s*(\.extend|\+=)\s*\(?\s*"
    r"([A-Za-z_][A-Za-z0-9_]*)\s*\(")


_CACHE_1202AR = {}


def _sources():
    for f in _ROOT.rglob("*.py"):
        if "/tests/" in str(f) or "bundled_tests" in str(f):
            continue
        try:
            yield f, f.read_text(encoding="utf-8")
        except Exception:
            continue


def _silently_returns_empty_list():
    """Functions that swallow an exception and return [] with no announcement.

    Cached: both scans walk and parse every module in the package, and two tests ask for
    them. The repeat cost ~35s of suite time for a byte-identical answer."""
    if "silent" in _CACHE_1202AR:
        return _CACHE_1202AR["silent"]
    found = {}
    for path, src in _sources():
        try:
            tree = ast.parse(src)
        except Exception:
            continue
        # #1202zg: split the file ONCE and slice by line number. `ast.get_source_segment`
        # re-splits the whole source on every call (30 ms on a 4,700-line file), and this loop
        # calls it once per function across the entire tree -- 95s each for the two corpus
        # scanners, 190s of a 1,215s suite. The slice keeps the first line's indentation, which
        # `_ANNOUNCES.search` does not look at.
        _lines_1202zg = src.splitlines(keepends=True)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            seg = "".join(_lines_1202zg[node.lineno - 1:
                                        getattr(node, "end_lineno", node.lineno)])
            if _ANNOUNCES.search(seg):
                continue
            for handler in [h for h in ast.walk(node) if isinstance(h, ast.ExceptHandler)]:
                for stmt in handler.body:
                    if (isinstance(stmt, ast.Return)
                            and isinstance(stmt.value, (ast.List, ast.Set))
                            and not getattr(stmt.value, "elts", None)):
                        found[node.name] = str(path)
                        break
    _CACHE_1202AR["silent"] = found
    return found


def _feeds_a_verdict():
    """Function names whose return value is poured into a blocker/finding list."""
    if "feeds" in _CACHE_1202AR:
        return _CACHE_1202AR["feeds"]
    out = {}
    for path, src in _sources():
        for m in _AGGREGATION.finditer(src):
            out.setdefault(m.group(3), str(path))
    _CACHE_1202AR["feeds"] = out
    return out


def test_the_aggregation_scan_is_live():
    """Guard the guard: an empty answer below must mean 'none', not 'scan found nothing'."""
    feeds = _feeds_a_verdict()
    assert len(feeds) >= 10, f"aggregation scan matched only {len(feeds)} callsites; it broke"
    assert "_auth_override_blockers_1202s" in feeds, (
        "the aggregation scan no longer sees a callsite known to exist "
        "(deliverability.py wires _auth_override_blockers_1202s into blockers)")


def test_the_silent_scan_is_live_1203jr():
    """Guard the OTHER guard: `both == []` is the whole claim, and it has two operands.

    #1202ar validated the aggregation side in both directions -- a floor and a callsite known
    to exist -- and left the silent side with no assertion at all. The emptiness of an
    INTERSECTION is evidence only while both sides are alive: let
    `_silently_returns_empty_list` collapse to {} (the announcement regex broadens to match
    every function, the handler walk stops seeing `except`, someone else writes the shared
    cache key) and `test_no_silent_detector_decides_a_gate` passes having looked at nothing.
    That is this file's own subject -- a check that cannot tell "found none" from "did not
    run" -- one level up, in the test that pins it.

    The floors are measured, not picked. Today: 67 functions across 31 files (the docstring's
    50 was 2026-09-02, so this class grows). The largest single module supplies 8, so 20
    cannot be reached by one module's worth of hits, and 10 distinct files cannot be reached
    by one module at all. Both are far under the real count, because this ratchet INVITES
    bringing functions under an announcement and a floor that bites on progress gets raised
    by whoever is in a hurry.
    """
    silent = _silently_returns_empty_list()
    assert len(silent) >= 20, (
        "the silent-return scan found only %d functions; the largest single module supplies 8, "
        "so this is a broken scan rather than a cleaned-up tree -- and it makes "
        "test_no_silent_detector_decides_a_gate pass vacuously" % len(silent))
    files = {p for p in silent.values()}
    assert len(files) >= 10, (
        "the scan reached only %d file(s), so rglob or the source filter is broken: %s"
        % (len(files), sorted(files)[:5]))


def test_no_silent_detector_decides_a_gate():
    silent = _silently_returns_empty_list()
    feeds = _feeds_a_verdict()
    both = sorted(set(silent) & set(feeds))
    assert both == [], (
        "these functions return [] when they crash AND their result becomes a gate verdict, "
        "so a crashed check now reads as 'no problems found' and the gate opens: "
        + "; ".join(f"{n} (defined {silent[n]}, consumed {feeds[n]})" for n in both)
        + ". Announce the failure (warn_once_1201) or return a degraded marker the caller "
          "can distinguish from a clean result.")
