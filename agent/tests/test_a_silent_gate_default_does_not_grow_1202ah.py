r"""#1202ah: a ratchet, because "the check did not run" reading as "the check passed" is the
single most repeated defect in this repository.

Found seven times, and I wrote three of them myself inside two days:

    #1039   live seed row count -> fell back to a filter that examines 0 tables
    #1201   best-effort mechanisms failing with no line at all
    #1202q  seed audit given no project_dir, so its live path could not start
    #1202ae auth-override gate / route scan / asset scan -> [] on crash   (mine)
    #1202af unscoped owner-read scan, invented-field scan -> [] on crash
    #1202ag _coverage_summary -> {"is_clean": True} on crash, in the gate module itself
    #1202z  a wakeup "scheduled" onto a queue with no consumer

Chasing the eighth instance is not the fix; the repo already knows that — #943 pins source
windows and #1034 pins count-beside-truncated-list for exactly this reason. So: count the
silent empty-returns in the two gate modules and refuse to let the number grow.

It is a CEILING, not a list. Bringing one of the twelve under an announcement is expected and
lowers the number; adding a thirteenth fails here with the name of the offender. Some of the
twelve are legitimately fine — `_bug_reference_time_1023` returning None is answering "no
timestamp", not measuring — which is why this pins the count instead of demanding zero.

Announcement means any of: warn_once_1201, _gate_absent_792, _swallowed_79x,
_not_measured_NNNN, a degraded marker, or a logger warning/error in the function.
"""

import ast
import re
import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

_RUNTIME = (THIS_DIR.parent
            / "env_generator/llm_generator/multi_agent/runtime")
_GATE_MODULES = ("deliverability.py", "delivery_gate.py")

_ANNOUNCES = re.compile(
    r"warn_once_1201|_gate_absent_792|_swallowed_79\d|_not_measured_\d+|degraded"
    r"|logger\.(warning|error)|_logger\.(warning|error)")

# Measured 2026-09-02, after #1202ae/#1202af/#1202ag/#1202am. Lower it when you fix one.
#
# The ten that remain were each traced to what consumes them, not left on a name:
#
#   SAFE — the empty value is the conservative answer, so a crash blocks rather than passes
#     _has_passing_ui_evidence -> False   "no passing UI evidence"
#     _endpoint_validated      -> False   "not validated"
#
#   ANSWERING, not measuring — the empty value is a legitimate result
#     _bug_reference_time_1023 -> 0.0     "no timestamp"
#     _co_failure_note_1202k   -> ""      a note, cosmetic
#     _content_moved_since_1114-> None    "unknown"
#     _filters_708b            -> {}      "cannot derive filters" — #780 documents the
#                                         log-only fallback this feeds
#
# The four REPORT-ONLY scans that used to sit here — _imageless_spec_screens_unreachable_823,
# _unstaged_asset_classes_842, _unseeded_entity_kinds_844, never_matching_filters_1139 — were
# brought under warn_once_1201 by #1202aq, which is the move this ratchet exists to invite.
# Report-only still meant a crashed scan returned [] with no line anywhere, so "did not run"
# and "found nothing" were indistinguishable in the log. 10 -> 6.
_CEILING = 6


def _silent_empty_returns():
    out = []
    for fname in _GATE_MODULES:
        src = (_RUNTIME / fname).read_text(encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            seg = ast.get_source_segment(src, node) or ""
            if _ANNOUNCES.search(seg):
                continue
            for handler in [h for h in ast.walk(node) if isinstance(h, ast.ExceptHandler)]:
                for stmt in handler.body:
                    if not isinstance(stmt, ast.Return):
                        continue
                    v = stmt.value
                    empty = (
                        (isinstance(v, (ast.List, ast.Dict, ast.Set))
                         and not (getattr(v, "elts", None) or getattr(v, "keys", None)))
                        or (isinstance(v, ast.Constant) and v.value in (False, None, 0, "")))
                    if empty:
                        out.append("%s:%s (line %s)" % (fname, node.name,
                                                        getattr(stmt, "lineno", "?")))
    return out


def test_the_count_does_not_grow():
    found = _silent_empty_returns()
    assert len(found) <= _CEILING, (
        "a gate function swallows an exception and returns an empty value with no "
        "announcement, so a crashed check now reads as a passed one. Announce it "
        "(warn_once_1201 / _gate_absent_792 / a degraded marker) or lower _CEILING if you "
        "removed one instead:\n  " + "\n  ".join(sorted(found)))


def test_the_ceiling_is_not_stale():
    """If the real count drops, the ceiling must follow — otherwise the ratchet stops biting."""
    found = _silent_empty_returns()
    assert len(found) >= _CEILING - 2, (
        "the count has dropped to %d; lower _CEILING to match so a regression is caught."
        % len(found))


def test_the_announcement_vocabulary_covers_what_the_repo_uses():
    """Four mechanisms exist, and missing one is how my first audit produced a wrong number:
    it called business_chain_blockers an offender when it announces via _swallowed_790."""
    src = (_RUNTIME / "delivery_gate.py").read_text(encoding="utf-8")
    assert "_swallowed_790(" in src
    assert _ANNOUNCES.search("_swallowed_790(")
    assert _ANNOUNCES.search("warn_once_1201(")
    assert _ANNOUNCES.search("_gate_absent_792(")


def test_the_fixed_ones_stay_fixed():
    """The three from #1202ae/#1202af/#1202ag must never reappear in the silent set."""
    found = " ".join(_silent_empty_returns())
    for name in ("_coverage_summary", "unscoped_owner_read_findings",
                 "invented_field_fallback_blockers"):
        assert name not in found, name
