"""#1202wx: the task a lane is dispatched on must carry what the gate's own line carries.

A broken chain step is formatted TWICE for two different readers:
  * `chain_executor.execute_chain._fmt` -> `broken`, which the delivery gate reports;
  * `remediation_dispatcher._chain_broken_detail_798` -> the body of the remediation task,
    "THE BROKEN STEP(S), from the chain registry's own last_result -- fix THESE".
The second is the one a lane acts on, and it was the poorer of the two in two ways.

1. #1052's warning was a closure inside `execute_chain`, so only `_fmt` could say it. MEASURED
   over all 150 chain hubs: of 1617 steps the dispatcher turns into lane work, 69 across 12
   runs -- including r137, the most recent -- are 404s where the route RAN. Their tasks read
   "returned 404, expected 200" and nothing more, which is exactly the reading #1052 exists to
   prevent: it "sends the backend lane to implement an endpoint it already wrote". Hoisted to
   `chain_executor.route_ran_note_1052` and called by both, one definition (#1032).

2. The note was cut at 160 characters, silently. 106 steps across 25 runs carry a longer one,
   and in 40 of them the cut removed the backend's own `{"detail": "..."}` -- the most
   actionable fragment -- because the framework's reading of the step spends the budget first.
   The median position of that detail is character 160, exactly the cliff. #1202vx's rule from
   a second direction, and #1034's at the same time.

   A plain head/tail cut recovered 33 of the 40. The 7 it still lost were the RICHEST notes
   (472-671 chars), where the detail and the diagnosis of it both sit mid-string. Anchoring the
   window on the evidence recovers 40 of 40, at a median emitted length of 215 characters.
"""
import ast
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

from multi_agent.runtime.chain_executor import route_ran_note_1052  # noqa: E402
from multi_agent.runtime.remediation_dispatcher import (  # noqa: E402
    _note_keeping_the_evidence_1202wx,
    _route_ran_note_1052_1202wx,
)

_DISPATCH = os.path.join(_AGENT, "env_generator", "llm_generator", "multi_agent", "runtime",
                         "remediation_dispatcher.py")
_CHAIN = os.path.join(_AGENT, "env_generator", "llm_generator", "multi_agent", "runtime",
                      "chain_executor.py")

# The shape #1051 recognises: the backend's own marker for "the handler ran and the id it was
# given does not resolve".
_ROUTE_RAN = {"status": 404,
              "note": 'referenced resource not found {"detail":"parent resource not found"}'}


def _read(path):
    with open(path, encoding="utf-8") as fh:      # #1202eu
        return fh.read()


# --- 1. one definition, both readers -----------------------------------------------------

def test_the_1052_warning_is_module_level_now():
    fn = next((n for n in ast.walk(ast.parse(_read(_CHAIN)))
               if isinstance(n, ast.FunctionDef) and n.name == "route_ran_note_1052"), None)
    assert fn is not None, "the note is not reachable outside execute_chain"
    assert fn.col_offset == 0, "still nested, so the dispatcher cannot call it"


def test_the_gate_line_still_says_it():
    """★ Hoisting must not cost the reader that already had it."""
    tree = ast.parse(_read(_CHAIN))
    outer = next(n for n in ast.walk(tree)
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                 and n.name == "execute_chain")
    fmt = next(n for n in ast.walk(outer)
               if isinstance(n, ast.FunctionDef) and n.name == "_fmt")
    called = {getattr(n.func, "id", "") for n in ast.walk(fmt) if isinstance(n, ast.Call)}
    assert "_route_ran_note_1052" in called, "_fmt no longer attaches the warning"


def test_the_dispatcher_says_it_too():
    assert route_ran_note_1052(_ROUTE_RAN), "the fixture no longer trips #1051"
    assert _route_ran_note_1052_1202wx(_ROUTE_RAN) == route_ran_note_1052(_ROUTE_RAN), (
        "the two readers no longer say the same thing")


def test_the_task_BUILDER_calls_both_helpers():
    """★ Caught by mutation: every other test here passed with the call site removed.

    A helper the task builder does not call is #1202wm's dead mechanism, and it is the exact
    state this ticket found -- the note existed and the line that reaches the lane did not
    carry it."""
    fn = next((n for n in ast.walk(ast.parse(_read(_DISPATCH)))
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
               and n.name == "_chain_broken_detail_798"), None)
    assert fn is not None, "_chain_broken_detail_798 is gone"
    called = {getattr(n.func, "id", "") for n in ast.walk(fn) if isinstance(n, ast.Call)}
    for helper in ("_route_ran_note_1052_1202wx", "_note_keeping_the_evidence_1202wx"):
        assert helper in called, (
            "%s is never called by the function that builds the lane's task" % helper)


def test_the_builder_no_longer_slices_the_note_itself():
    """A second, blind cut beside the careful one would undo it (#1032)."""
    fn = next(n for n in ast.walk(ast.parse(_read(_DISPATCH)))
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
              and n.name == "_chain_broken_detail_798")
    src = ast.unparse(fn)
    assert "note[:160]" not in src and "note[:_NOTE_CAP_1202WX]" not in src, (
        "the raw note is still being sliced in the builder: %s" % src[:200])


def test_the_dispatcher_restates_nothing():
    """#1032: two copies of one rule drift. The text must live in exactly one file."""
    assert "the route RAN" not in _read(_DISPATCH), (
        "#1052's wording was copied into the dispatcher instead of imported")


def test_a_non_404_and_a_plain_404_stay_quiet():
    assert route_ran_note_1052({"status": 200, "note": _ROUTE_RAN["note"]}) == ""
    assert route_ran_note_1052({"status": 404, "note": "no such route"}) == ""


def test_an_import_failure_costs_an_annotation_not_the_task():
    """The remediation task must survive a note it cannot build."""
    assert _route_ran_note_1052_1202wx(None) == ""
    assert _route_ran_note_1052_1202wx({"status": "not a number"}) == ""


# --- 2. the cut keeps the app's own words ------------------------------------------------

def _long_note(detail_at):
    lead = "framework reading of this step. " * 20
    return lead[:detail_at] + '{"detail":"parent resource not found"} — you sent place_id=143'


def test_a_short_note_is_untouched():
    assert _note_keeping_the_evidence_1202wx("short") == "short"


def test_the_apps_own_words_survive_a_long_note():
    """★ The defect: 40 of 40 measured losses were this."""
    out = _note_keeping_the_evidence_1202wx(_long_note(300))
    assert '"detail":"parent resource not found"' in out, out


def test_the_detail_survives_even_when_it_sits_mid_string():
    """★ The 7 richest notes a head/tail cut still lost."""
    note = _long_note(300) + (" trailing framework prose. " * 20)
    out = _note_keeping_the_evidence_1202wx(note)
    assert '"detail":"parent resource not found"' in out, out
    assert "place_id=143" in out, "the diagnosis beside the detail went with it"


def test_evidence_straddling_the_head_boundary_is_not_chopped_in_half():
    """★ Found by replaying the corpus, not by reasoning about it.

    tiktok-r102's note puts the detail at character 174 with a head of 180, so slicing at the
    boundary emitted `{"deta` and then searched for a marker AFTER 180, found none, and fell
    back to the tail -- losing the one thing the window exists to keep. The window now extends
    to cover evidence that straddles the boundary."""
    note = ("x" * 174) + '{"detail":"actor_id does not belong to the caller"} — you sent '
    note += "actor_id=1; video_id=1, and this caller does not own it. " + ("y" * 200)
    out = _note_keeping_the_evidence_1202wx(note)
    assert '{"detail":"actor_id does not belong to the caller"}' in out, out


def test_the_marker_is_searched_from_the_START_of_the_note():
    """★ The r102 bug: the search began at the head boundary, so evidence that began just
    BEFORE it was invisible -- the head emitted `{"deta` and the fallback took the tail."""
    src = ast.unparse(next(
        n for n in ast.walk(ast.parse(_read(_DISPATCH)))
        if isinstance(n, ast.FunctionDef) and n.name == "_note_keeping_the_evidence_1202wx"))
    assert "text.find(mark)" in src, (
        "the evidence search is offset again, so evidence straddling the head is missed: %s"
        % src)


def test_the_head_never_ends_on_half_an_evidence_marker():
    """★ The visible half of the r102 bug: the head ended on `{"deta`.

    Dropping the straddle branch still keeps the detail (the else branch re-slices from the
    marker) but leaves that fragment dangling in front of the cut, so the reader sees the
    evidence start, then a cut, then the evidence start again."""
    from multi_agent.runtime import remediation_dispatcher as rd
    note = ("x" * 174) + '{"detail":"nope"} tail words here. ' + ("y" * 300)
    head_part = _note_keeping_the_evidence_1202wx(note).split(" …[")[0]
    partial = [m[:k] for m in rd._NOTE_EVIDENCE_MARKS_1202WX for k in range(2, len(m))]
    assert not any(head_part.endswith(p) for p in partial), (
        "the head stops inside an evidence marker: %r" % head_part[-20:])


def test_a_straddling_window_is_not_emitted_twice():
    note = ("x" * 174) + '{"detail":"nope"} tail words here. ' + ("y" * 300)
    out = _note_keeping_the_evidence_1202wx(note)
    assert out.count('{"detail":"nope"}') == 1, out


def test_the_cap_is_at_least_as_wide_as_the_window_it_reconstructs():
    """★ A relation, not a magic number (#647's numbers are justified in their own comments).

    If the head+evidence window could exceed the cap, a cut note would be LONGER than a whole
    note of the same content -- the cut would be costing the reader instead of saving them."""
    from multi_agent.runtime import remediation_dispatcher as rd
    assert rd._NOTE_CAP_1202WX >= rd._NOTE_HEAD_1202WX + rd._NOTE_EVIDENCE_KEEP_1202WX, (
        "cap %d < head %d + evidence %d" % (rd._NOTE_CAP_1202WX, rd._NOTE_HEAD_1202WX,
                                            rd._NOTE_EVIDENCE_KEEP_1202WX))
    assert rd._NOTE_CAP_1202WX >= rd._NOTE_HEAD_1202WX + rd._NOTE_TAIL_1202WX


def test_evidence_already_inside_the_head_is_not_repeated():
    note = 'lead. {"detail":"nope"} ' + ("z" * 500)
    out = _note_keeping_the_evidence_1202wx(note)
    assert out.count('{"detail":"nope"}') == 1, out
    assert "chars cut" in out


def test_the_framework_reading_is_not_thrown_away_either():
    """Both halves, not a swap of which one is lost."""
    out = _note_keeping_the_evidence_1202wx(_long_note(300))
    assert out.startswith("framework reading of this step."), out


def test_the_cut_says_how_much_it_cut():
    """#1034: no silent truncation -- a count, so the reader knows to open the record."""
    out = _note_keeping_the_evidence_1202wx(_long_note(300))
    assert "chars cut" in out, out
    n = int(out.split("…[")[1].split(" chars")[0])
    assert n > 0 and n < len(_long_note(300)), out


def test_a_note_with_no_evidence_marker_keeps_its_tail():
    note = "framework prose. " * 40
    out = _note_keeping_the_evidence_1202wx(note)
    assert out.endswith(note[-40:]), out
    assert "chars cut" in out


def test_a_malformed_note_is_not_fatal():
    for bad in (None, 7, object()):
        assert isinstance(_note_keeping_the_evidence_1202wx(bad), str)
