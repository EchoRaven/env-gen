r"""#718: #713 called the corpus's commonest sharing a routing failure. It is one page.

#713 detects screens whose captures are byte-identical and says "their routes did not resolve and
the browser fell through to a common page". For the group that dominates the corpus that sentence
is false, and the route data needed to tell them apart was already in hand.

Four reference screens map to ONE route:

    browse_home   browse_home_rows   card_hover_preview   account_menu   ->  /browse

so an identical capture is EXPECTED — it is the same page. The sharing rate says as much:
browse_home_rows shares in 53 of 53 runs, card_hover_preview 53 of 57, account_menu 19 of 23.
They are INTERACTION STATES — a scrolled view, a hovered card, an opened menu — reachable only by
acting on /browse, and the capture only navigates.

So the gate photographs the base page and scores it against a reference showing the overlay.
`card_hover_preview`'s median similarity is 0.300 and its MAXIMUM across 54 appearances is 0.55:
it has never reached the 0.65 bar and structurally cannot. Dropping the three from the average is
worth +0.0208 on the mean run and +0.1785 at the extreme.

#595 already demotes reference frames holding TWO OR MORE open overlays ("not a state the app can
be in"). A single overlay is below that threshold, which is why these were never caught.

Nothing is demoted here. An overlay screen is real product and dropping it loses coverage — the
same trade #713 declined. What changes is that the expected case stops being reported as a defect
in the same words as the real one.
"""
import inspect
import json
import pathlib
import tempfile

import pytest

from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf


def _block() -> str:
    src = inspect.getsource(vf)
    i = src.index("#718: SPLIT THE EXPECTED SHARING FROM THE DEFECT")
    return src[i:src.index("Their similarity scores measure that page", i)]


def _msg() -> str:
    import re
    return re.sub(r'"\s*\n\s*"', "", _block())


# --- the split is made on route identity ------------------------------------------------------

def test_it_reads_the_route_off_the_results():
    b = _block()
    assert '_r713 or {}).get("route")' in b


def test_one_shared_route_takes_the_expected_branch():
    b = _block()
    assert "len(_rs713) == 1" in b
    assert "#713b" in b


def test_an_empty_route_does_not_count_as_agreement():
    """Two screens with no route recorded must NOT be excused as 'one page'."""
    assert "and next(iter(_rs713))" in _block()


def test_differing_routes_still_get_the_defect_message():
    b = _block()
    # Search for the WARNING after the #713b branch: the comment above quotes #713's sentence
    # verbatim while explaining why it is wrong, so a plain .index() finds the quotation first.
    i = b.index("#713b")
    assert "their routes did not resolve" in b[i:], "the defect message must still be reachable"


def test_the_expected_branch_skips_the_defect_warning():
    assert "continue" in _block()


# --- the two messages say different things ------------------------------------------------------

def test_the_expected_message_calls_it_expected():
    m = _msg()
    assert "This is expected" in m
    assert "interaction states of a single page" in m


def test_it_names_the_shared_route():
    assert "share ONE route (%s)" in _msg()


def test_it_says_whose_limitation_a_low_score_is():
    m = _msg()
    assert "GATE's limitation, not the app's" in m


def test_the_defect_message_is_unchanged():
    assert "Distinct screens cannot render identically" in _msg()


# --- provenance -----------------------------------------------------------------------------------

def test_the_four_screens_and_their_route_are_recorded():
    b = " ".join(_block().replace("#", " ").split())
    for n in ("browse_home_rows", "card_hover_preview", "account_menu"):
        assert n in b
    assert "-> /browse" in b


def test_the_sharing_rates_are_recorded():
    b = " ".join(_block().replace("#", " ").split())
    assert "53 of 53" in b and "53 of 57" in b and "19 of 23" in b


def test_the_structural_impossibility_is_recorded():
    b = " ".join(_block().replace("#", " ").split())
    assert "MAXIMUM across 54 appearances is 0.55" in b
    assert "structurally cannot" in b


def test_the_cost_is_quantified():
    b = " ".join(_block().replace("#", " ").split())
    assert "+0.0208" in b and "+0.1785" in b


def test_why_595_missed_them_is_recorded():
    b = " ".join(_block().replace("#", " ").split())
    assert "TWO OR MORE open overlays" in b
    assert "single overlay falls under that threshold" in b


def test_the_blocking_measurement_is_recorded():
    """The screen that cannot be photographed was gating releases."""
    b = " ".join(_block().replace("#", " ").split())
    assert "BLOCKING screen in 36 of its 54 appearances" in b
    assert "clears the 0.65 bar exactly ZERO times" in b


def test_the_reframing_of_711_and_712_is_recorded():
    b = " ".join(_block().replace("#", " ").split())
    # `.replace("#", " ")` then a split/join collapses the gap, so it reads "711 and 712".
    assert "reframes 711 and 712" in b
    assert "could never release on the gate's own terms" in b


def test_the_refusal_to_demote_is_recorded():
    b = " ".join(_block().replace("#", " ").split())
    assert "dropping it loses coverage" in b


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))


# --- #1203pg: the branch, DRIVEN -----------------------------------------------------------------
#
# Every assertion above reads the SOURCE, and two mutations walked straight through:
#
#   * deleting the `continue` that ends the expected branch -- so a group that legitimately
#     shares one route ALSO gets #713's defect warning and is recorded in
#     `identical_captures_713`. The block still contains the word `continue` (the
#     `len(_names713) < 2` guard uses one), so `assert "continue" in _block()` held.
#   * `len(_names713) < 2` -> `< 3`, so a PAIR of byte-identical captures is never examined at
#     all. No string any test asserts on changes.
#
# `_persist_verdict` is a module-level function with keyword arguments, and the grouping hashes
# real PNG bytes, so the whole decision runs against a temp directory.
#
# Checked before writing these: the shared-route screens are NOT left blocking. #542a's
# `_demote_duplicate_route_screens` groups by resolved route, keeps one canonical screen and
# marks the rest advisory, which is the same case from the other side.


def _verdict_for(routes, blob=b"IDENTICAL-BYTES"):
    """Run `_persist_verdict` over screens whose captures are byte-identical.

    `routes` maps screen name -> route. Every screen gets the SAME png bytes, which is what
    puts them in one `_by713` group.
    """
    d = pathlib.Path(tempfile.mkdtemp())
    vdir = d / "design" / "visual_gate"
    vdir.mkdir(parents=True)
    for name in routes:
        (vdir / ("%s.png" % name)).write_bytes(blob)
    results = [{"name": n, "route": r, "similarity": 0.4, "dimensions": {}}
               for n, r in routes.items()]
    vf._persist_verdict(d, passed=False, min_similarity=0.65, summary="s",
                        coverage={}, results=results)
    out = vdir / "verdict.json"
    return json.loads(out.read_text(encoding="utf-8")) if out.is_file() else {}


def test_differing_routes_are_still_recorded_as_a_defect():
    """Non-vacuity first: without this, the suppression test below would pass against a
    detector that records nothing at all."""
    v = _verdict_for({"a": "/one", "b": "/two"})
    rec = v.get("identical_captures_713") or []
    assert rec, "a real fall-through was not recorded"
    assert sorted(rec[0]["screens"]) == ["a", "b"]


def test_a_shared_route_group_is_NOT_recorded_as_a_defect():
    """#718's whole subject: the corpus's commonest sharing is one page, not a routing failure.

    browse_home and card_hover_preview both resolve to /browse in 53 of 53 runs.
    """
    v = _verdict_for({"browse_home": "/browse", "card_hover_preview": "/browse"})
    assert not (v.get("identical_captures_713") or []), (
        "expected sharing was recorded as a routing defect")


def test_a_PAIR_is_examined_not_only_a_larger_group():
    """`len(_names713) < 2` is the floor. At `< 3` a pair of identical captures is invisible,
    and a pair is the commonest shape there is."""
    v = _verdict_for({"a": "/one", "b": "/two"})
    assert len(((v.get("identical_captures_713") or [{}])[0]).get("screens") or []) == 2


def test_a_group_with_NO_resolved_route_is_still_a_defect():
    """An empty route is not agreement -- a missing route is exactly why the browser falls
    through to a common page, so this must take the defect branch."""
    v = _verdict_for({"a": "", "b": ""})
    assert (v.get("identical_captures_713") or []), (
        "two screens with no route agreed with each other and were excused"
    )


def test_distinct_captures_are_not_grouped_at_all():
    """The other side of the floor: different bytes must not be reported as sharing."""
    d = pathlib.Path(tempfile.mkdtemp())
    vdir = d / "design" / "visual_gate"
    vdir.mkdir(parents=True)
    (vdir / "a.png").write_bytes(b"ONE")
    (vdir / "b.png").write_bytes(b"TWO")
    vf._persist_verdict(
        d, passed=False, min_similarity=0.65, summary="s", coverage={},
        results=[{"name": "a", "route": "/one", "similarity": 0.4, "dimensions": {}},
                 {"name": "b", "route": "/two", "similarity": 0.4, "dimensions": {}}])
    v = json.loads((vdir / "verdict.json").read_text(encoding="utf-8"))
    assert not (v.get("identical_captures_713") or [])
