r"""#1203ix: the fill+submit loop ran up to three times and recorded none of it.

"submit sent NO /auth request" is the corpus's commonest ui_flow failure — 93 of 270 — and
the loop that produces it exists because a MULTI-STEP auth form advances without calling the
API. Measured over the 173 runs with an auth page:

    auth source calls setMode( / setStep( / setStage( :  49 of 89 runs emit it  (55%)
    it does not                                       :  24 of 84 runs emit it  (29%)

Nearly twice the rate, and the predicate is the strict one — the looser version of the same
question (`step|single|stage` anywhere) says 69% against 28%, so the signal is not an artifact
of how hard I looked.

It is a correlate without a mechanism, and two candidates died against the corpus before this
landed: email-first forms with no password field at all (41% against 42% — no signal) and
pages whose first button is a dismiss control, which `_click_primary` would click instead of
the submit (n=6, 50% against 42%). Telling the remaining stories apart needs to know what the
loop SAW, and nothing recorded it:

    a form that reveals its password on round two reads   1, 2
    one that never advances reads                         1, 1, 1
    one whose primary control could not be clicked reads  a single entry

RECORD-ONLY ON PURPOSE. #1203iw has just settled what this note says, and #612, #1203a6,
#1203b6 and #1203g1 all locate that branch by its wording; these counts are for the next
investigation, not for the lane, so they go where #1203a6 put the requests — beside the
verdict, in the record.
"""
import ast
import inspect

import pytest

from env_generator.llm_generator.multi_agent.runtime import test_user_validation as tuv

SRC = inspect.getsource(tuv)


def _flow():
    for n in ast.walk(ast.parse(SRC)):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "_ui_auth_flow":
            return n
    raise AssertionError("_ui_auth_flow is gone")


def _filler():
    for n in ast.walk(_flow()):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "_fill_visible_inputs":
            return n
    raise AssertionError("_fill_visible_inputs is gone")


def _round_loop():
    for n in ast.walk(_flow()):
        if isinstance(n, (ast.For, ast.AsyncFor)) and ast.unparse(n.iter).startswith("range(3"):
            return n
    raise AssertionError("the three-round loop is gone")


# --- the count itself ---------------------------------------------------------------------------

def test_the_filler_returns_a_count():
    fn = _filler()
    returns = [n for n in ast.walk(fn) if isinstance(n, ast.Return) and n.value is not None]
    assert returns, "the filler returns nothing — the rounds would all read the same"
    assert any("_filled_1203ix" in ast.unparse(r.value) for r in returns), \
        [ast.unparse(r.value) for r in returns]


def test_every_fill_is_counted():
    """A fill that does not increment under-reports exactly the branch it belongs to, which
    is the one thing these numbers exist to tell apart."""
    body = ast.unparse(_filler())
    fills = body.count("inp.fill(")
    counts = body.count("_filled_1203ix += 1")
    assert fills > 0, "no fill call found — the filler changed shape"
    assert counts == fills, "%d fill calls, %d increments" % (fills, counts)


def test_the_counter_starts_at_zero_each_call():
    fn = _filler()
    inits = [n for n in ast.walk(fn) if isinstance(n, ast.Assign)
             and any(getattr(t, "id", "") == "_filled_1203ix" for t in n.targets)]
    assert len(inits) == 1, len(inits)
    assert ast.unparse(inits[0].value) == "0", ast.unparse(inits[0].value)


# --- one entry per round that ran ----------------------------------------------------------------

def test_each_round_appends_what_it_filled():
    loop = ast.unparse(_round_loop())
    assert "_fill_rounds_1203ix.append(await _fill_visible_inputs())" in loop, loop[:200]


def test_the_list_is_bound_inside_the_route_loop():
    """Same invariant #1203iu pins for the page errors: the route loop reuses one page, so a
    list hoisted out of it would report `/signup`'s rounds against `/login`."""
    route_loop = None
    for n in ast.walk(_flow()):
        if isinstance(n, (ast.For, ast.AsyncFor)):
            consts = {c.value for c in ast.walk(n.iter)
                      if isinstance(c, ast.Constant) and isinstance(c.value, str)}
            if "/signup" in consts and "/login" in consts:
                route_loop = n
    assert route_loop is not None, "the signup+login loop is gone"
    names = set()
    for n in ast.walk(route_loop):
        tgts = (n.targets if isinstance(n, ast.Assign)
                else [n.target] if isinstance(n, ast.AnnAssign) else [])
        names |= {t.id for t in tgts if isinstance(t, ast.Name)}
    assert "_fill_rounds_1203ix" in names, sorted(n for n in names if "round" in n)


def test_the_record_carries_the_rounds():
    body = ast.unparse(_flow())
    assert "'fill_rounds'" in body or '"fill_rounds"' in body


def test_a_short_list_is_itself_the_signal():
    """The loop breaks on a token, a navigation, or a click it could not make, so the LENGTH
    carries as much as the values. Nothing may cap or pad it."""
    loop = ast.unparse(_round_loop())
    assert "_fill_rounds_1203ix[:" not in loop, loop[:200]
    body = ast.unparse(_flow())
    assert "'fill_rounds': _fill_rounds_1203ix," in body or \
           '"fill_rounds": _fill_rounds_1203ix,' in body, "the record slices or renames it"


# --- the promise this ticket made ----------------------------------------------------------------

def _unwired_note():
    """#1203iw's note, read off the AST.

    Not off the source text: the note is an implicit concatenation across six lines, so
    "the form is not wired to the API at all" is never contiguous in the file. Python joins
    adjacent literals at parse time, which is why the AST has the whole sentence and a
    `in SRC` check does not — the first version of this test asserted the latter and failed
    on a string that was perfectly intact.
    """
    for node in ast.walk(_flow()):
        if not (isinstance(node, ast.Assign)
                and any(getattr(t, "id", "") == "_note" for t in node.targets)):
            continue
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str) \
                and "not wired to the API" in node.value.value:
            return node.value.value
    raise AssertionError("the unwired note is gone")


def test_this_ticket_did_not_touch_the_note():
    """Record-only. #1203iw settled the wording an hour earlier and four tickets' tests
    locate that branch by it; re-opening it here would be a second edit on one sentence."""
    note = _unwired_note()
    assert "the form is not wired to the API at all" in note, note
    assert "was the submit disabled" in note, note
    assert "button has no handler" not in SRC


def test_the_note_does_not_read_the_counts():
    """If the note used them, this ticket would be changing what the lane is told, and the
    docstring's "record-only" would be false."""
    for node in ast.walk(_flow()):
        if (isinstance(node, ast.Assign)
                and any(getattr(t, "id", "") == "_note" for t in node.targets)):
            assert "_fill_rounds_1203ix" not in ast.unparse(node.value), ast.unparse(node.value)


# --- provenance -----------------------------------------------------------------------------------

def test_the_measurement_is_recorded():
    flat = " ".join(SRC.replace("#", " ").split())
    assert "49 of 89" in flat and "24 of 84" in flat


def test_the_two_dead_candidates_are_recorded():
    """So the next reader does not spend the corpus on them again."""
    flat = " ".join(SRC.replace("#", " ").split())
    assert "41% against 42%" in flat
    assert "dismiss control" in flat


def test_why_it_is_record_only_is_recorded():
    flat = " ".join(SRC.replace("#", " ").split())
    assert "Record-only on purpose" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
