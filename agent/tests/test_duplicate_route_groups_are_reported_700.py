r"""#700: #615's detector has existed for 85 fixes and has never been called, not even to report.

Sweep B of the "computed but never consumed" search (see #699) returned 26 module-level functions
whose name appears only at their own `def`. `duplicate_route_content_groups` is one of them, and
it is the one that finds a real product defect: distinct routes whose delivered pages fetch an
identical, unparameterised endpoint set therefore render identical content — "click Games, see
Movies".

Half of its silence is deliberate and documented at the detector:

    "Deliberately NOT wired as a delivery blocker. At 32/45 it would wedge nearly every run,
     and whether 'six identical pages' should block OR MERELY BE REPORTED is a calibration
     decision, not a measurement."

The other half is not. Nobody took the reporting option either, so a defect measured in 32 of 45
runs has never once been said out loud. Running the detector over r146's DELIVERED frontend:

    /browse, /browse/browse-by-languages, /browse/games, /browse/latest
        all fetch only /api/titles
        components BrowseByLanguagesPage, BrowseHomePage, GamesPage, NewAndPopularPage

Four nav destinations rendering the same list, in a run that shipped. r145 finds none, so it is
not a universal artifact of the projection.

WARNING only. The calibration decision is untouched, nothing blocks, and the same reasoning as
#691/#696/#698 applies: a finding that is computed and unobservable is worth no more than one that
was never computed.

**The path is the trap.** `ui_page_delivery_blockers` takes `frontend/src`;
`duplicate_route_content_groups` appends `"src"/"pages"` itself and so takes the frontend ROOT.
Passing it the sibling's argument returns `[]` — and its contract is "[] when nothing can be
resolved", which is indistinguishable from "nothing found". My first run of the detector did
exactly that and reported a clean zero.
"""
import inspect
import json
from pathlib import Path

import pytest

from env_generator.llm_generator.multi_agent.runtime import deliverability as dv
from env_generator.llm_generator.multi_agent.runtime.frontend_audit import (
    duplicate_route_content_groups as groups,
)


def _block() -> str:
    src = inspect.getsource(dv)
    i = src.index("#700: REPORT the #615 groups")
    # Cut at the START of the line that returns the blockers, not at the call inside it:
    # slicing mid-line left a dangling "return " in the block and made a "this code does not
    # return" assertion fail on text that is not this code.
    j = src.index("ui_page_delivery_blockers(Path(app_root)", i)
    return src[i:src.rfind("\n", i, j) + 1]


# --- the detector itself, on real shapes ----------------------------------------------------------

def _tree(tmp_path: Path, pages: dict) -> Path:
    root = tmp_path / "frontend"
    (root / "src" / "pages").mkdir(parents=True)
    for comp, body in pages.items():
        (root / "src" / "pages" / f"{comp}.jsx").write_text(body, encoding="utf-8")
    return root


def test_it_groups_routes_that_fetch_the_same_bare_endpoint(tmp_path: Path):
    root = _tree(tmp_path, {
        "A": "fetch('/api/titles')", "B": "fetch('/api/titles')"})
    out = groups(root, {"a": {"component": "A", "route": "/a"},
                        "b": {"component": "B", "route": "/b"}})
    assert len(out) == 1
    assert out[0]["routes"] == ["/a", "/b"]


def test_a_parameterised_fetch_differentiates_the_page(tmp_path: Path):
    """`/api/titles/{id}` is a different page from a bare `/api/titles`."""
    root = _tree(tmp_path, {
        "A": "fetch('/api/titles')", "B": "fetch(`/api/titles/${id}`)"})
    out = groups(root, {"a": {"component": "A", "route": "/a"},
                        "b": {"component": "B", "route": "/b"}})
    assert out == []


def test_a_query_string_differentiates_the_page(tmp_path: Path):
    root = _tree(tmp_path, {
        "A": "fetch('/api/titles')", "B": "fetch('/api/titles?kind=movie')"})
    out = groups(root, {"a": {"component": "A", "route": "/a"},
                        "b": {"component": "B", "route": "/b"}})
    assert out == []


def test_one_route_is_not_a_group(tmp_path: Path):
    root = _tree(tmp_path, {"A": "fetch('/api/titles')"})
    assert groups(root, {"a": {"component": "A", "route": "/a"}}) == []


def test_the_frontend_ROOT_is_the_argument_not_src(tmp_path: Path):
    """The trap that produced a false clean zero on the first attempt."""
    root = _tree(tmp_path, {
        "A": "fetch('/api/titles')", "B": "fetch('/api/titles')"})
    pages = {"a": {"component": "A", "route": "/a"}, "b": {"component": "B", "route": "/b"}}
    assert len(groups(root, pages)) == 1
    assert groups(root / "src", pages) == [], "src/ silently resolves nothing"


# --- it is now reported ---------------------------------------------------------------------------

def test_the_detector_is_called():
    assert "duplicate_route_content_groups(" in _block()


def test_it_is_passed_the_frontend_root():
    b = _block()
    assert 'Path(app_root) / "frontend"' in b
    assert 'Path(app_root) / "frontend" / "src"' not in b


def test_it_warns_rather_than_blocks():
    """Not "the word blocker is absent" — the comment discusses blocking. What matters is that
    the CODE neither returns nor contributes to a blocker list."""
    b = _block()
    assert "_LOG_700.warning(" in b
    # Only the BLOCK's own indentation level. #708b added a nested helper whose `return`
    # statements are its own; a flat "return not in text" check read those as an early exit
    # from the enclosing function, which they are not.
    own = [l for l in b.split("\n")
           if l.strip() and not l.strip().startswith("#")
           and len(l) - len(l.lstrip()) <= 8]
    joined = "\n".join(own)
    assert "return" not in joined
    assert ".append(" not in joined


def test_the_report_names_routes_endpoints_and_components():
    b = _block()
    for key in ("routes", "endpoints", "components"):
        assert f'_g.get("{key}")' in b


def test_it_fetches_its_own_pages():
    """Reusing the name bound in the try/except-pass above would skip the report silently."""
    b = _block()
    assert "workhub.get_ui_pages()" in b
    assert "_pages_700" in b


def test_the_report_cannot_break_the_gate():
    b = _block()
    assert "except Exception:" in b and "pass" in b


def test_the_blocker_call_is_unchanged():
    src = inspect.getsource(dv)
    assert 'ui_page_delivery_blockers(Path(app_root) / "frontend" / "src", workhub)' in src


# --- #705: the premise carries a current number --------------------------------------------------

def _detector_src() -> str:
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import frontend_audit as fa
    src = inspect.getsource(fa)
    i = src.index("#615 — N NAV DESTINATIONS, ONE UNFILTERED COLLECTION")
    return src[i:src.index("_PAGE_FETCH_RE_615", i)]


def test_the_original_measurement_is_kept():
    assert "32 of 45" in _detector_src()


def test_the_re_measurement_is_recorded_beside_it():
    d = " ".join(_detector_src().replace("#", " ").split())
    assert "112 of 136 (82%)" in d
    assert "RE-MEASURED 2026-08-14" in d


def test_the_distribution_is_recorded():
    d = " ".join(_detector_src().replace("#", " ").split())
    assert "2:10 3:19 4:27 5:28 6:23 7:4 8:1" in d


def test_it_says_the_calibration_call_is_reinforced_not_overturned():
    d = " ".join(_detector_src().replace("#", " ").split())
    assert "reinforces the calibration call" in d
    assert "wedge more runs" in d


# --- #708: the objection to fixing the CAUSE is withdrawn -----------------------------------------

def test_the_stale_kind_standard_claim_is_marked_stale():
    d = " ".join(_detector_src().replace("#", " ").split())
    assert "THAT LAST SENTENCE IS STALE" in d


def test_the_real_seed_distribution_is_recorded():
    d = " ".join(_detector_src().replace("#", " ").split())
    assert "kind: movie 28 / series 32" in d
    assert "seed_dataset.json" in d


def test_it_says_which_seed_the_stale_claim_came_from():
    """The 6-row framework fallback is where kind='standard' still lives."""
    d = " ".join(_detector_src().replace("#", " ").split())
    assert "6-row fallback seed" in d
    assert "not the shipped catalog" in d


def test_only_the_technical_objection_is_withdrawn():
    """The calibration decision — block vs report — is a separate question and stays open."""
    d = " ".join(_detector_src().replace("#", " ").split())
    assert "calibration question above is untouched" in d
    assert "Deliberately NOT wired as a delivery blocker" in d


# --- provenance -------------------------------------------------------------------------------------

def test_the_deliberate_half_is_recorded_as_deliberate():
    flat = " ".join(_block().replace("#", " ").split())
    assert "Deliberately NOT wired as a delivery blocker" in flat
    assert "calibration decision" in flat


def test_the_r146_evidence_is_recorded():
    flat = " ".join(_block().replace("#", " ").split())
    assert "r146's DELIVERED frontend" in flat
    assert "r145 finds none" in flat


def test_the_path_trap_is_recorded():
    flat = " ".join(_block().replace("#", " ").split())
    assert "indistinguishable from \"nothing found\"" in flat


def test_it_names_the_sibling_findings():
    flat = " ".join(_block().replace("#", " ").split())
    assert "691" in flat and "696" in flat and "698" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
