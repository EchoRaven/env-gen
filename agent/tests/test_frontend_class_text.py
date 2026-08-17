"""#433 (netflix r29 browse_by_languages: a MIDDLE poster rail 'row2-carousel'
rendered as a bogus HERO billboard while its identical siblings rendered as rails
— the last structural miss on that 0.20 screen). Root cause: a substring
false-match. The rail/hero classifiers matched structural terms against the WHOLE
component text, including the role's parenthetical EXAMPLE-TITLE list; a sample
title 'Heroes' contains 'hero' → tripped _RAIL_NEG_TERMS ('hero' ⇒ not a rail)
AND _HERO_ROLE_TERMS ('hero' ⇒ is a hero). FIX: _class_text_221 strips the '(…)'
example list before structural term-matching, so enumerated DATA can't drive
classification. Generalizable — any title substring ('Navigator' ⊃ 'nav',
'Tabula' ⊃ 'tab') would have caused the same class of bug. Locks it in."""
from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    _class_text_221, _is_rail_comp, _is_hero_comp, _render_reference_page)


def test_class_text_strips_parenthetical_examples():
    c = {"id": "row2-carousel", "role": "second content row (Shipwrecked, Heroes, Vikings)"}
    t = _class_text_221(c)
    assert "hero" not in t, "example titles must not leak into classification text"
    assert "carousel" in t and "content row" in t, "structural terms are preserved"


def test_content_row_with_hero_titled_item_is_a_rail_not_hero():
    # a middle content rail whose sample titles include 'Heroes'
    c = {"id": "row2-carousel", "role": "second content row (Shipwrecked, Heroes, Vikings)",
         "region": [0.0, 0.5, 1.0, 0.72], "geometry": {"columns": 6}}
    assert _is_rail_comp(c) is True, "'Heroes' in the example list must not un-rail it"
    assert _is_hero_comp(c) is False, "'Heroes' in the example list must not make it a hero"


def test_other_title_substrings_dont_misclassify():
    for title in ("The Navigator", "Tabula Rasa", "Header Games", "Billboard Hot 100"):
        c = {"id": "content-row", "role": f"horizontal poster rail ({title})",
             "region": [0.0, 0.4, 1.0, 0.6], "geometry": {"columns": 6}}
        assert _is_rail_comp(c) is True, f"'{title}' must not defeat rail detection"


def test_genuine_hero_still_detected():
    # a real hero-billboard component (term OUTSIDE any parenthetical) is unaffected
    c = {"id": "hero-billboard", "role": "large featured content billboard (RAW)",
         "region": [0.0, 0.06, 1.0, 0.82]}
    assert _is_hero_comp(c) is True


# ── integration: a rows screen enumerating a 'Heroes' title renders no bogus hero ──
_DESIGN = {"design_system": {"palette": {"bg": "#141414", "accent": "#e50914"},
                             "theme": {"default": "dark"}}, "assets": []}


def test_rows_screen_with_hero_titled_item_no_bogus_billboard():
    scr = {"route": "/browse/languages", "name": "browse_by_languages", "components": [
        {"id": "topnav", "role": "top navigation bar", "region": [0.0, 0.0, 1.0, 0.06]},
        {"id": "row1-carousel", "role": "first content row (RAW, Avatar, Hawk)",
         "region": [0.0, 0.29, 1.0, 0.5], "geometry": {"columns": 6}},
        {"id": "row2-carousel", "role": "second content row (Shipwrecked, Heroes, Vikings)",
         "region": [0.0, 0.5, 1.0, 0.72], "geometry": {"columns": 6}},
        {"id": "row3-carousel", "role": "third content row (Young Sheldon, Shameless)",
         "region": [0.0, 0.72, 1.0, 0.94], "geometry": {"columns": 6}}]}
    out = _render_reference_page("P", {"route": "/browse/languages"}, scr, _DESIGN,
                                 [("Home", "/browse")], "/api/titles")
    assert "text-4xl font-bold drop-shadow-lg" not in out, \
        "no content row must render as a hero billboard"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
