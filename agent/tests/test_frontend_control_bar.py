"""#432b (netflix r29: components 0.38 = the MIN dim that bottlenecks every
per-screen score; judge on browse_by_languages 0.20: "Missing: … Original
Language dropdown, Language dropdown …" and "missing dropdown caret icons on
selects"). The band projector (hero/rail/grid/nav/media) has NO path for a
filter/dropdown/selector, so the design's genre/language/sort controls were
dropped entirely (or a full-height open dropdown mis-filed as a right aside).
FIX: render matched control components once as a right-aligned row of labeled
<select> dropdowns with a caret; strip them from the content bands. ADDITIVE —
screens with no controls stay byte-identical. Generalizable (keys off the
design's own dropdown/selector/filter/genre role tokens). Locks it in."""
from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    _is_control_comp, _control_label_432b, _control_bar_432b, _render_reference_page)


# ── detection: real controls in, nav utilities out ──
def test_detects_dropdowns_and_filters():
    assert _is_control_comp({"id": "original-language-dropdown", "role": "dropdown selector for original language"})
    assert _is_control_comp({"id": "genres-dropdown", "role": "genre filter dropdown button"})
    assert _is_control_comp({"id": "sort-control", "role": "sort by selector"})


def test_excludes_nav_and_profile_utilities():
    assert not _is_control_comp({"id": "profile-dropdown-menu", "role": "account dropdown listing profiles"})
    assert not _is_control_comp({"id": "primary-nav-links", "role": "horizontal nav links dropdown"})
    assert not _is_control_comp({"id": "top-nav-bar", "role": "global top navigation with search"})
    assert not _is_control_comp({"id": "hero", "role": "hero billboard"})


# ── labels: generic filter vocabulary, no product literals ──
def test_labels_are_clean_generic():
    # #551: the Original/Dubbing/Subtitles TYPE selector is a DISTINCT filter dimension
    # from the language list (the judge wanted BOTH dropdowns) -> 'Original Language',
    # not a collapsed 'Language'. Still clean generic catalog vocabulary, no literal.
    assert _control_label_432b({"id": "original-language-dropdown"}) == "Original Language"
    assert _control_label_432b({"id": "language-dropdown", "role": "language dropdown"}) == "Language"
    assert _control_label_432b({"id": "genres-dropdown", "role": "genre filter"}) == "Genres"
    assert _control_label_432b({"id": "some-thing-selector", "role": "a selector"}) == "Some Thing"


# ── control bar: additive; renders a <select> + caret; dedups ──
def test_control_bar_renders_select_with_caret():
    out = _control_bar_432b([
        {"id": "language-dropdown", "role": "language dropdown"},
        {"id": "language-list-dropdown", "role": "another language dropdown"}])  # dup 'Language'
    # #859: was `"\\u25BE" in out` — an assertion on the SPELLING of the caret, which pinned a
    # typed triangle in place for as long as it was green. The intent is "the select has a
    # disclosure affordance"; assert that, and assert it is DRAWN, which is the actual invariant.
    assert "<select" in out, "must render a select"
    assert 'd="M6 9l6 6 6-6"' in out, "must render a drawn caret"
    assert "\u25be" not in out and "\u25bc" not in out, "a typed caret is the #859 defect"
    assert out.count("<select") == 1, "duplicate labels are collapsed"


def test_control_bar_distinguishes_original_language_from_language():
    # #551: two DISTINCT dimensions -> two selects (not collapsed to one).
    out = _control_bar_432b([
        {"id": "original-language-dropdown", "role": "dropdown for language type"},
        {"id": "language-dropdown", "role": "language dropdown"}])
    assert out.count("<select") == 2
    assert "Original Language" in out and ">Language<" in out


def test_control_bar_empty_when_no_controls():
    assert _control_bar_432b([{"id": "hero", "role": "hero billboard"}]) == ""
    assert _control_bar_432b([]) == ""


# ── integration: a browse-by-languages-shaped screen renders its dropdowns and
#    does NOT ship them as a stray right aside ──
_DESIGN = {"design_system": {"palette": {"bg": "#141414", "accent": "#e50914"},
                             "theme": {"default": "dark"}}, "assets": []}
_LANGS = {"route": "/browse/languages", "name": "browse_by_languages", "components": [
    {"id": "top-nav-bar", "role": "top navigation bar", "region": [0.0, 0.0, 1.0, 0.06]},
    {"id": "page-title", "role": "page heading 'Browse by Languages'", "region": [0.02, 0.09, 0.35, 0.15]},
    {"id": "original-language-dropdown", "role": "dropdown selector for original language",
     "region": [0.685, 0.09, 0.845, 0.24]},
    {"id": "language-dropdown", "role": "open language dropdown listing all languages",
     "region": [0.845, 0.09, 1.0, 1.0]},
    {"id": "row1-carousel", "role": "row of poster cards for TV Action & Adventure",
     "region": [0.0, 0.29, 1.0, 0.5], "geometry": {"columns": 6}},
    {"id": "row2-carousel", "role": "row of poster cards for Only on Netflix",
     "region": [0.0, 0.5, 1.0, 0.72], "geometry": {"columns": 6}}]}


def test_browse_by_languages_renders_dropdowns():
    out = _render_reference_page("BrowseByLanguagesPage", {"route": "/browse/languages"},
                                 _LANGS, _DESIGN, [("Home", "/browse")], "/api/titles")
    assert "<select" in out, "the language dropdowns must render"
    assert "Language" in out
    # the full-height open dropdown must NOT ship as the bogus ▲▼ right aside
    assert "\\u25B2" not in out and "\\u25BC" not in out, "no stray prev/next aside"


def test_screen_without_controls_has_no_select():
    scr = {"route": "/browse", "name": "browse_home", "components": [
        {"id": "topnav", "role": "top navigation bar", "region": [0.0, 0.0, 1.0, 0.08]},
        {"id": "hero", "role": "hero billboard title art", "region": [0.0, 0.1, 1.0, 0.55]},
        {"id": "rail", "role": 'poster rail of "Trending"', "region": [0.0, 0.6, 1.0, 0.82],
         "geometry": {"columns": 6}}]}
    out = _render_reference_page("BrowseHomePage", {"route": "/browse"}, scr, _DESIGN,
                                 [("Home", "/browse")], "/api/titles")
    assert "<select" not in out, "a screen with no filter controls stays byte-identical"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
