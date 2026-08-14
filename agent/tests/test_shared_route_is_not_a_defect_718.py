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
