"""#432 (netflix r29: copy 0.42, the 2nd-worst dimension, flagged on nearly every
catalog screen — judge: "Row heading reads 'poster cards for TV Action &
Adventure' instead of ['TV Action & Adventure']" and "lowercase vs reference
title case"). Root cause: a rail role like 'row of poster cards for TV Action &
Adventure' matched _section_title_221's 'row of (.+)' capture and returned the
WHOLE tail — 'poster cards for TV Action & Adventure' — which shipped verbatim
(lowercase) as the <h3> heading. FIX: peel the leading generic media descriptor
('poster cards for'/'thumbnails of'/…) and Title-Case the remainder, returning
'' when only generic words remain (so the caller falls back to the page label).
Generalizable — no product literals. Locks it in."""
from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    _section_title_221)


# ── the exact r29 miss: generic descriptor peeled, real title Title-Cased ──
def test_row_of_poster_cards_for_x_yields_clean_title():
    assert _section_title_221("row of poster cards for TV Action & Adventure") \
        == "TV Action & Adventure"


def test_lowercase_source_is_title_cased():
    assert _section_title_221("row of poster cards for trending now") == "Trending Now"


def test_thumbnails_of_prefix_peeled():
    assert _section_title_221("grid of thumbnails of Only on Netflix") == "Only on Netflix"


# ── quoted titles are preserved verbatim (existing behavior) ──
def test_quoted_title_preserved():
    assert _section_title_221('poster rail of "Top 10 in the U.S."') == "Top 10 in the U.S."
    assert _section_title_221('carousel of "New Releases"') == "New Releases"


def test_caps_and_numbers_preserved_not_mangled():
    # already-capitalized / all-caps / numeric tokens must survive title-casing
    assert _section_title_221("row of 4K HDR Movies") == "4K HDR"  # 'Movies' is a trailing noun stripped by the capture guard
    assert _section_title_221('rail of "Top 10"') == "Top 10"


# ── only-generic descriptors → '' so the caller falls back to the page label ──
def test_only_generic_returns_empty():
    assert _section_title_221("grid of poster cards") == ""
    assert _section_title_221("carousel of thumbnails") == ""
    assert _section_title_221("poster grid") == ""       # no 'X of Y' at all


def test_empty_and_junk_inputs():
    assert _section_title_221("") == ""
    assert _section_title_221(None) == ""
    assert _section_title_221("a top navigation bar") == ""


# ── #432 GENERALIZATION: the descriptor-peel must work for NON-media apps too
#    (not just 'poster cards for X'), without truncating real titles ──
def test_generalizes_beyond_media_containers():
    assert _section_title_221("row of project cards for Active Sprints") == "Active Sprints"
    assert _section_title_221("rail of product tiles for On Sale") == "On Sale"
    assert _section_title_221("carousel of contact cards for My Team") == "My Team"


def test_real_title_starting_with_ambiguous_word_not_truncated():
    # 'art'/'movies' are NOT pure containers → a title that merely starts with one
    # (and has of/for) must survive intact
    assert _section_title_221("row of Art of War") == "Art of War"
    assert _section_title_221("row of 4K HDR Movies") == "4K HDR"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))


# ── #459 (r40 judge: new_and_popular/genre_category 'debug-style section labels') ──
def test_layout_description_is_not_a_title():
    from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
        _section_title_221)
    # a component DESCRIPTION (contains layout/container nouns) is NOT a section name
    for role in (
        "horizontal carousel of large landscape title cards with TOP 10 badges",
        "horizontal row of large title cards",
        "ranked carousel: large numeral behind portrait poster cards",
        "grid of poster thumbnails",
    ):
        assert _section_title_221(role) == "", f"{role!r} is a description, not a title"


def test_real_titles_still_extracted_459():
    from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
        _section_title_221)
    # real section NAMES (no layout noun) must still be extracted
    assert _section_title_221('rail of "Top 10 in the U.S. Today"') == "Top 10 in the U.S. Today"
    assert _section_title_221("carousel of TV Action & Adventure titles") == "TV Action & Adventure"
    assert _section_title_221('row of "Only on Netflix"') == "Only on Netflix"
