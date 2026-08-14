r"""#727: the lane can now say how to reach a state the capture cannot navigate to.

Measured on r148: of 20 reference screens, **8 have no page at all** — account_menu,
browse_home_rows, card_hover_preview, card_preview, player_controls, rate_dialog,
shows_genres_menu, title_episodes. Every one is an INTERACTION state (an opened menu, a scroll, a
hover, a modal, player chrome), reachable only by ACTING on a page, while the visual capture only
navigates. So the gate photographs the base page, scores it against a reference showing the
overlay, and the screen can never pass — `card_hover_preview` BLOCKS in 36 of 54 appearances with
a maximum of 0.40 against a 0.65 bar (item 40).

The agent that built the page knows how to reach the state. This lets it say so.

**It does not hand over the standard, which is what makes it safe.** The gate scores against the
orchestrator-side reference ORIGINAL, outside the lane's workspace — `design/references/` is only
a lane-visible copy. A wrong `reach` produces a capture that misses a fixed target and scores
WORSE. There is no way to win by lying, which is the difference from #566z's authored
expectations.

**Declaration only.** Nothing consumes `reach` yet and no gate behaviour moves. Item 49 records
why: consuming it early has two failure modes, and at the measured declaration rates (the lane
writes 4 of r148's 16 ui_pages, 14 of r147's 27, 1 of r146's 13) both are live. Treating an
undeclared screen as advisory would silently drop all 8; treating it as blocking would wedge
every run until the lane declares. The cheapest way to tell those apart is one run that counts
ADOPTION with the gate untouched, which is exactly what this change enables.
"""
import inspect

import pytest

from env_generator.llm_generator.tools import hub_tools


TOOL = hub_tools.KickoffDeclareUiPageTool


def _params():
    return TOOL.PARAMETERS["properties"]


# --- the surface exists and follows the tool's own convention -----------------------------------

def test_reach_is_declarable():
    assert "reach" in _params()


def test_reference_is_declarable():
    assert "reference" in _params()


def test_reach_is_a_flat_string_list_not_nested_json():
    """The tool's DESCRIPTION promises 'Flat params; no nested JSON' — a list of dicts would
    break that promise in the one tool that makes it."""
    p = _params()["reach"]
    assert p["type"] == "array"
    assert p["items"] == {"type": "string"}
    assert "Flat params; no nested JSON" in TOOL.DESCRIPTION


def test_neither_is_required():
    """A page with no interaction state must stay declarable exactly as before."""
    assert TOOL.PARAMETERS["required"] == ["meeting_id", "id", "route"]


def test_the_verbs_are_named():
    d = _params()["reach"]["description"]
    for verb in ("hover", "click", "scroll", "wait"):
        assert verb in d


def test_the_description_says_when_to_use_it():
    d = _params()["reach"]["description"]
    assert "INTERACTION state" in d
    assert "photograph the base page" in d


# --- it reaches the record ---------------------------------------------------------------------

def test_both_fields_are_written_onto_the_page():
    src = inspect.getsource(TOOL._run)
    assert 'page["reference"] = str(reference)' in src
    assert 'page["reach"] = [str(r) for r in reach][:12]' in src


def test_they_are_omitted_when_absent():
    """An absent field must not appear as an empty value — every sibling behaves this way."""
    src = inspect.getsource(TOOL._run)
    assert "if reference: page[" in src
    assert "if reach: page[" in src


def test_reach_is_capped():
    src = inspect.getsource(TOOL._run)
    assert "[:12]" in src, "an unbounded action list is a log and a runtime hazard"


def test_the_existing_fields_are_untouched():
    src = inspect.getsource(TOOL._run)
    for f in ("purpose", "components", "must_have", "component", "apis_used"):
        assert f'page["{f}"]' in src


# --- nothing consumes it yet ----------------------------------------------------------------------

def test_the_gate_does_not_read_reach_yet():
    """Declaration-only is the whole point of this step; consuming it early is item 49's trap."""
    from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf
    assert '"reach"' not in inspect.getsource(vf)


# --- provenance ---------------------------------------------------------------------------------

def _block() -> str:
    src = inspect.getsource(hub_tools)
    i = src.index("#727: HOW TO REACH THE STATE A REFERENCE SHOWS")
    return src[i:src.index('"reference": {', i)]


def test_the_eight_screens_are_named():
    b = " ".join(_block().replace("#", " ").split())
    for n in ("account_menu", "card_hover_preview", "player_controls", "title_episodes"):
        assert n in b


def test_the_unpassable_measurement_is_recorded():
    b = " ".join(_block().replace("#", " ").split())
    assert "36 of 54 appearances" in b
    assert "maximum of 0.40" in b


def test_why_it_is_not_566z_is_recorded():
    b = " ".join(_block().replace("#", " ").split())
    assert "outside the lane's workspace" in b
    assert "no way to win by lying" in b


def test_the_declaration_only_scope_is_recorded():
    b = " ".join(_block().replace("#", " ").split())
    assert "DECLARATION ONLY" in b
    assert "counts ADOPTION with the gate untouched" in b


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
