"""#529 + #530 (netflix, 2026-08-06) — three projector dataflow bugs that cap
catalog fidelity even once GET /api/titles returns real title data. Verified
against generated/netflix-web-r95 renders + projected sources.

GROUND TRUTH (netflix-web-r95):
  - design/component_specs/browse_home.json line 216 role:
      "horizontal poster rail of shows (partially visible at bottom)"
    -> the projector shipped the rail heading LITERALLY as
      <h3>{"Shows (partially Visible at Bottom)"}</h3>   (a screenshot/debug
    annotation leaking into the UI).
  - design/design_system.json measured layout_constants.hero_backdrop_height_vh
    = 56, yet the projected movies hero rendered minHeight:'80vh' (region-derived;
    #527 had deliberately left hero height alone) -> pushed the first rail off
    screen.
  - the field-guesser _subOf omitted 'synopsis', so a title record whose only
    long-text field is `synopsis` rendered NO hero/card subtitle.

FIXES:
  #529 - add 'synopsis' to the _subOf subtitle-key list AND to the _metaOf
         exclusion regex (so it feeds the subtitle, never a raw meta chip), in all
         THREE copies (_REF_HELPERS_JS + the two structured/list-fallback preludes).
  #530a - (no change) the projected hero backdrop already prefers the current
          record's own backdrop: ((cur && _backdropOf(cur)) || _refImg(0) || ...);
          r95 fell to _refImg(0) only because `cur` was null (the GET 500'd). This
          test locks that ordering so a regression that hardcodes _refImg(0) is caught.
  #530b - _section_title_221 strips a TRAILING render-state parenthetical
          ('(partially visible at bottom)', '(cut off)', '(off-screen)' ...) that
          annotates the rail's on-screen state, not its NAME. Quoted titles and
          real titular parentheticals ('Top 10 (This Week)') are preserved.
  #530c - the projected hero honours the design's MEASURED hero_backdrop_height_vh
          (capped to a sane billboard max) so a rail stays above the fold; with NO
          measured value the height is today's region-derived value (byte-identical).

All fixes are additive: when the annotation/measurement/field is ABSENT the emitted
output is byte-identical to pre-#529/#530. No product literals.
"""
import re

from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    _section_title_221, _render_reference_page, _REF_HELPERS_JS)
import env_generator.llm_generator.multi_agent.runtime.frontend_scaffold as _fs


# ─────────────────────────── #529: _subOf / _metaOf ───────────────────────────

def _module_source() -> str:
    with open(_fs.__file__, "r", encoding="utf-8") as fh:
        return fh.read()


def test_subof_includes_synopsis_in_all_three_definitions():
    defs = [ln for ln in _module_source().splitlines() if "_subOf = (r) =>" in ln]
    assert len(defs) == 3, "expected the three _subOf definitions"
    for d in defs:
        assert "'synopsis'" in d, "each _subOf must guess the synopsis field"
        # placed among the descriptive-text keys, not the identity/sender keys
        assert "'summary','synopsis'" in d or "'synopsis','description'" in d


def test_emitted_ref_helpers_subof_carries_synopsis():
    # the helper block actually shipped into every projected reference page
    m = re.search(r"_subOf = \(r\) => \{ for \(const k of \[([^\]]*)\]",
                  _REF_HELPERS_JS)
    assert m and "'synopsis'" in m.group(1)


def test_metaof_excludes_synopsis_in_all_three_definitions():
    defs = [ln for ln in _module_source().splitlines() if "_metaOf = (r) =>" in ln]
    assert len(defs) == 3, "expected the three _metaOf definitions"
    for d in defs:
        # synopsis is a subtitle, never a raw scalar meta chip
        assert "synopsis" in d, "each _metaOf exclusion regex must drop synopsis"


# ───────────────────────── #530b: section-title strip ─────────────────────────

def test_section_title_strips_render_state_parenthetical():
    # the exact r95 role that shipped 'Shows (partially Visible at Bottom)'
    out = _section_title_221(
        "horizontal poster rail of shows (partially visible at bottom)")
    for leak in ("partially", "Partially", "Visible", "visible", "Bottom", "bottom",
                 "("):
        assert leak not in out, f"debug annotation {leak!r} leaked into {out!r}"


def test_section_title_keeps_clean_name_after_stripping_annotation():
    # a real category name carrying the same annotation -> clean human title
    out = _section_title_221(
        "horizontal poster rail of Documentaries (partially visible at bottom)")
    assert out == "Documentaries"
    out2 = _section_title_221("carousel of Trending Now (cut off) titles")
    assert out2 == "Trending Now"


def test_section_title_preserves_quoted_and_titular_parenthetical():
    # a QUOTED title is curated copy — its parenthetical is content, not an annotation
    assert _section_title_221("rail of 'Top 10 (This Week)' titles") == "Top 10 (This Week)"


def test_section_title_byte_identical_without_annotation():
    # no render-state parenthetical -> untouched vs pre-#530 behaviour
    assert _section_title_221("carousel of Trending Now titles") == "Trending Now"
    assert _section_title_221("section title for New on Netflix rail") == "New on Netflix"
    assert _section_title_221("row of poster cards for TV Action & Adventure") == \
        "TV Action & Adventure"


# ─────────────────────── #530c / #530a: hero render props ─────────────────────

def _design(lc=None):
    ds = {"palette": {"bg": "#141414", "accent": "#e50914"},
          "theme": {"default": "dark"}}
    if lc is not None:
        ds["layout_constants"] = lc
    return {"design_system": ds,
            "assets": [{"id": "m1", "file": "backdrops/m1.jpg", "type": "jpg",
                        "dims": [1280, 720],
                        "staged_path": "public/assets/backdrops/m1.jpg"}]}


# a hero whose measured REGION is a tall 80vh (mirrors r95's movies hero)
_SCREEN_TALL_HERO = {"route": "/browse", "name": "browse_home", "components": [
    {"id": "hero", "region": [0.0, 0.0, 1.0, 0.80],
     "role": "hero billboard title art", "assets": ["m1"]},
    {"id": "rail", "region": [0.0, 0.85, 1.0, 0.98],
     "role": "horizontal poster rail", "geometry": {"columns": 6, "rows": 1}}]}


def _render(design):
    return _render_reference_page("BrowseHomePage", {}, _SCREEN_TALL_HERO, design,
                                  [("Home", "/browse")], "/api/titles")


def test_hero_height_reflects_measured_value():
    out = _render(_design({"hero_backdrop_height_vh": 56}))
    assert "minHeight: '56vh'" in out
    assert "minHeight: '80vh'" not in out  # region-derived 80vh no longer wins


def test_hero_height_clamps_measured_over_cap():
    # an over-large measurement is capped to the billboard max so a rail stays visible
    out = _render(_design({"hero_backdrop_height_vh": 80}))
    m = re.search(r"minHeight: '(\d+)vh'", out)
    assert m and int(m.group(1)) <= 60


def test_hero_height_without_metric_is_today_default():
    # no layout_constants -> today's region-derived height, byte-identical to pre-#530
    out = _render(_design())
    assert "minHeight: '80vh'" in out  # (0.80 - 0.0) * 100, clamped [40,85]


def test_hero_backdrop_prefers_current_record_over_reference_fallback():
    # #530a: the record's OWN backdrop wins; _refImg(0) is only a fallback
    out = _render(_design())
    assert "(cur && _backdropOf(cur)) || _refImg(0)" in out


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
