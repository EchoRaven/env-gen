"""#472b (r48: multi-rail pages new_and_popular/browse_home rendered as ONE 6-col GRID
instead of rails). ROOT: _is_catalog_grid fires when len(_sec_titles)<2, and _sec_titles
comes from _section_title_221 — which matched 'rail OF X' but MISSED the common
'section title FOR X [rail]' phrasing. new_and_popular's 'section title for New on Netflix
rail' therefore extracted nothing, then #459's layout-noun strip (the role contains
'rail') discarded it → _sec_titles<2 → the multi-rail page misfired into a grid. FIX: add
a 'title/header/label for X [rail/row/area]' extraction so curated section names survive.
Validated to NOT regress: browse_by_languages (single collection) still yields '' → grid,
and #459 debug/layout descriptions still strip to ''. (An earlier raw-role-signature
attempt, #472, was REVERTED because within a single collection the analyst describes one
row with extra descriptors → false distinctness → would regress browse_by_languages.)"""
from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    _section_title_221)


def test_extracts_curated_name_from_for_x_rail_phrasing():
    # #472b target: the exact r48 new_and_popular section-title roles → curated names KEPT
    assert _section_title_221("section title for New on Netflix rail") == "New on Netflix"
    assert _section_title_221("section title for Coming This Week rail") == "Coming This Week"
    assert _section_title_221("header for Trending Now row") == "Trending Now"


def test_single_collection_still_returns_empty():
    # browse_by_languages roles have NO curated name → '' → single-collection → grid
    assert _section_title_221("implicit row label area (title clipped by layout)") == ""
    assert _section_title_221("first horizontal rail of 5 title cards") == ""


def test_459_layout_descriptions_still_strip():
    # #459 intent preserved: component DESCRIPTIONS / debug labels → '' (no debug headers)
    assert _section_title_221("large landscape title cards with top 10 badges") == ""
    assert _section_title_221("new_and_popular 4") == ""
    assert _section_title_221("header: section of poster cards") == ""


def test_existing_curated_extraction_unaffected():
    assert _section_title_221("row of poster cards for TV Action & Adventure") == "TV Action & Adventure"
    assert _section_title_221('"Trending Now"') == "Trending Now"
    assert _section_title_221("rail of Only on Netflix") == "Only on Netflix"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
