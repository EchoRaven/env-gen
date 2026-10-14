r"""#1201 ratchet: a guard that can switch a mechanism off must not be added silently.

The dominant defect class this session was a mechanism wired and never reached, and the thing
that made all three instances invisible was the same: `try: from .x import mechanism_NNN ...
except Exception: pass`. The import is guarded because it can genuinely fail — a circular
import, a hub that is not there — and when it does, the mechanism is simply absent for the
whole run while the log stays clean. #1200's leak signal was one `except` away from exactly
that.

The fourteen that exist are NOT converted here, and the reason had to be earned rather than
asserted. The first version of this docstring said "their markers all appear in the corpus, so
they are running" — which was not evidence: none of these mechanisms logs from inside its own
body, so the corpus hits were the CALLING comment's text, not proof that anything ran. Checked
properly instead, by importing each guarded symbol the way the run does: all ten distinct
imports resolve under the run's PYTHONPATH (`note_finish_637` needs `agent/` on the path as a
real run has it; it resolves there). The guards protect against an import that does not
currently fail, so the mechanisms behind them run, and rewriting fourteen live call sites to
prove a point is not worth the risk.

What this pins is the direction: a NEW one has to say so, via `warn_once_1201`, one line.

Detected by shape, not by name: a `try:` whose body imports a symbol ending in a ticket number
and whose handler body is exactly `pass`. A guard that reports (contains `warn_once_1201`) is
not counted, which is the whole point — the ratchet is satisfied by fixing, not by hiding.
"""

import re
import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
ROOT = THIS_DIR.parent / "env_generator" / "llm_generator"
sys.path.insert(0, str(ROOT))

# Measured 2026-09-01. Lower it when one is converted; never raise it.
_BASELINE_1201 = 14


def _silent_mechanism_guards(root=None):
    # #1203js: `root` exists so the scanner can be pointed at a fixture. Without it the
    # only way to show it SEES a shape is to leave a real violation in the tree, and the
    # 80-line cap went unnoticed for exactly that reason -- removing it changes no count
    # today, so nothing but a positive control can keep it removed.
    found = []
    for p in sorted((root or ROOT).rglob("*.py")):
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        for i, line in enumerate(lines):
            if line.strip() != "try:":
                continue
            indent = len(line) - len(line.lstrip())
            body, silent = [], False
            # Landmark, not a byte window (#943): the block ends at the first line that
            # dedents back to the `try`.
            #
            # #1203js: the landmark used to be capped at `min(i + 80, ...)`, so a `try` longer
            # than 80 lines never reached its own dedent, `silent` stayed False, and the block
            # was skipped as though clean. Eight blocks hit that cap; one was a real violation
            # -- a 105-line body in `repair_dead_nav_links` whose handler was a bare `pass`.
            #
            # This is the hazard #943 exists for and NOT a case #943 catches: its detector wants
            # a subscript `src[i:i + N]` with N >= 100, and a cap of 80 inside `range(...)` is
            # neither. So the comment above claimed a landmark while the code kept a window, and
            # nothing in the suite was going to disagree.
            for j in range(i + 1, len(lines)):
                cur = lines[j]
                if cur.strip() and len(cur) - len(cur.lstrip()) <= indent:
                    silent = (cur.strip().startswith("except")
                              and j + 1 < len(lines) and lines[j + 1].strip() == "pass")
                    break
                body.append(cur)
            if not silent:
                continue
            blob = "\n".join(body)
            if "warn_once_1201" in blob:
                continue                      # it reports — that is the fix, not a violation
            m = re.search(r"from\s+\.[\w.]*\s+import\s+(\w*_\d{3,4})\b", blob)
            if m:
                found.append(f"{p.relative_to(root or ROOT)}:{i + 1} {m.group(1)}")
    return found


def test_the_count_does_not_grow():
    found = _silent_mechanism_guards()
    assert len(found) <= _BASELINE_1201, (
        "a new mechanism import is guarded by a silent `pass` — when that import fails the "
        "mechanism is OFF for the whole run and nothing says so. Add "
        "`warn_once_1201(site, what, exc)` to the handler.\n  "
        + "\n  ".join(sorted(k for k, n in _by_site_1203js().items()
                             if n > _KNOWN_BY_SITE_1203js.get(k, 0))))


# The fourteen as measured. #1203js: that sentence used to end "so a swap (one converted, one
# added) cannot pass unnoticed", and it was false for as long as it stood. The list was read
# ONLY inside the failure message of `test_the_count_does_not_grow`, which is evaluated only
# once the count has already grown -- so nothing ever compared the scan against it, and a `<=`
# on a total cannot see a swap by construction.
#
# One had already happened. `backend_skeleton _structurally_private_resource_633` was converted
# -- it announces through `warn_once_1201("backend_skeleton.structurally_private_633", ...)`
# now -- and `deliverability.py _swallowed_790` arrived, holding the total at 14. The ratchet
# lost a win it should have recorded and gained a violation it should have named, silently:
# its own subject, in the test that pins it.
#
# Keyed by FILE and SYMBOL, not by line. Every one of the fourteen had drifted hundreds of
# lines (`scaffolder.py register_mandated_ui_components_1090`: 467 -> 1532), so a line-anchored
# list is stale the day after it is written, which is why it was never asserted. Dropping the
# line is what makes the assertion survivable, and the multiset still catches a swap: a
# conversion and an addition cancel only inside the same file AND the same symbol.
_KNOWN_BY_SITE_1203js = {
    "multi_agent/agents/runtime/tooling.py note_finish_637": 1,
    "multi_agent/orchestrator.py record_stage_894": 2,
    "multi_agent/runtime/completeness_audit.py _gate_absent_792": 1,
    "multi_agent/runtime/database_scaffold.py require_stage_output_891": 1,
    "multi_agent/runtime/deliverability.py _swallowed_790": 1,
    "multi_agent/runtime/deliverability.py crossed_page_endpoints_728": 1,
    "multi_agent/runtime/frontend_audit.py _swallowed_790": 1,
    "multi_agent/runtime/heal_pipeline.py identical_projected_bodies_1156": 1,
    "multi_agent/runtime/remediation_dispatcher.py _swallowed_790": 1,
    "multi_agent/runtime/scaffolder.py register_mandated_ui_components_1090": 1,
    "multi_agent/runtime/scaffolder.py require_stage_input_891": 1,
    "multi_agent/runtime/visual_fidelity.py _screen_is_player_449": 1,
    "multi_agent/runtime/visual_fidelity.py require_stage_input_891": 1,
}


def _by_site_1203js():
    """The scan keyed by file and symbol, so the frozen set outlives a line-number drift."""
    import collections
    out = collections.Counter()
    for entry in _silent_mechanism_guards():
        path, rest = entry.split(":", 1)
        _line, symbol = rest.split(" ", 1)
        out["%s %s" % (path, symbol)] += 1
    return out


def _swap_1203js(got, want):
    """What arrived and what left, as two separate answers.

    A pure function because the `gone` half has no input in the live tree -- nothing is
    pending conversion today -- so asserting it there is unfalsifiable, and a mutation that
    deletes `and not gone` survives. The two directions mean opposite things (one is a
    regression, one is a win to record) and both have to be observable.
    """
    added = {k: got[k] - want.get(k, 0) for k in got if got[k] > want.get(k, 0)}
    gone = {k: want[k] - got.get(k, 0) for k in want if want[k] > got.get(k, 0)}
    return added, gone


def test_an_arriving_guard_is_reported_1203js():
    added, gone = _swap_1203js({"a.py x_111": 1, "b.py y_222": 1}, {"a.py x_111": 1})
    assert added == {"b.py y_222": 1} and gone == {}, (added, gone)


def test_a_converted_guard_is_reported_1203js():
    """The half the live tree cannot exercise: one left, so _KNOWN and the baseline owe a drop."""
    added, gone = _swap_1203js({"a.py x_111": 1}, {"a.py x_111": 1, "b.py y_222": 1})
    assert gone == {"b.py y_222": 1} and added == {}, (added, gone)


def test_a_swap_does_not_cancel_1203js():
    """The shape a `<=` on the total cannot see: one out, one in, same count."""
    added, gone = _swap_1203js({"a.py x_111": 1, "c.py z_333": 1},
                               {"a.py x_111": 1, "b.py y_222": 1})
    assert added == {"c.py z_333": 1} and gone == {"b.py y_222": 1}, (added, gone)


def test_a_second_site_in_one_file_is_counted_1203js():
    """orchestrator.py holds two `record_stage_894` guards, so this is a multiset, not a set."""
    added, gone = _swap_1203js({"o.py record_stage_894": 2}, {"o.py record_stage_894": 1})
    assert added == {"o.py record_stage_894": 1} and gone == {}, (added, gone)


def test_no_guard_is_swapped_for_another_1203js():
    """The claim the old list was written to make, now actually made.

    A swap is the LIKELY shape here, not a remote one: this ratchet invites conversions, so one
    leaving is the expected event and one arriving is the regression, and a total hides both.
    Asserting the multiset catches each direction and fails with names instead of a number.

    It also makes the ceiling non-vacuous for free: if the scanner breaks and finds nothing,
    `<= 14` passes and this does not.
    """
    added, gone = _swap_1203js(_by_site_1203js(), _KNOWN_BY_SITE_1203js)
    assert not added and not gone, (
        "the set of silently-guarded mechanisms CHANGED.\n"
        "  new (a mechanism can switch itself off with nothing said): %r\n"
        "  gone (converted? drop it here and lower _BASELINE_1201): %r" % (added, gone))


def test_this_sessions_own_guards_report():
    """The four added this session are the reason the ratchet exists; none may be in the
    silent set."""
    silent = " ".join(_silent_mechanism_guards())
    for name in ("_lane_owner_scoped_read_tables_1200",
                 "reconcile_ui_page_apis_1199"):
        assert name not in silent, name


def _fixture_1203js(tmp_path, body_lines):
    """A module with one `try:` of `body_lines` lines that imports a mechanism, handler `pass`."""
    filler = "\n".join("            x%d = %d" % (i, i) for i in range(body_lines))
    src = ("def f():\n"
           "    if True:\n"
           "        try:\n"
           "            from .thing import do_something_1234\n"
           + filler + "\n"
           "        except Exception:\n"
           "            pass\n")
    d = tmp_path / "pkg"
    d.mkdir()
    (d / "m.py").write_text(src, encoding="utf-8")
    return d


def test_the_scanner_sees_a_short_silent_block_1203js(tmp_path):
    """Positive control, the easy half: the shape it always caught."""
    found = _silent_mechanism_guards(_fixture_1203js(tmp_path, 10))
    assert any("do_something_1234" in f for f in found), found


def test_the_scanner_sees_a_block_longer_than_eighty_lines_1203js(tmp_path):
    """Positive control, the half that was blind.

    With `min(i + 80, ...)` in place this returns nothing: the loop ends before the dedent, so
    `silent` is never set and the block is dropped as clean. That is how a 105-line body in
    `repair_dead_nav_links` stayed off a list of fourteen for as long as the list existed.
    """
    found = _silent_mechanism_guards(_fixture_1203js(tmp_path, 200))
    assert any("do_something_1234" in f for f in found), (
        "a silent guard inside a 200-line `try` is invisible to the scanner: %r" % (found,))
