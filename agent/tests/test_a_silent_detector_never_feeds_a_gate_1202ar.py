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
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            seg = ast.get_source_segment(src, node) or ""
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
