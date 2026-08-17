"""#448 (netflix title_detail was the projector's LOWEST screen, r25=0.18; the
visual gate weights component completeness MOST heavily). Detail/overlay screens
(title_detail, title_episodes) carry a DOMINANT 'Episodes' block — a ~6-row list
(index, thumbnail, title, runtime, description) with a season selector — that the
projector had NO renderer for, so those screens shipped with their biggest
component group entirely absent. FIX: when a detail/overlay screen's design has an
'episode' component, render a data-driven episode list (from cur.episodes, else 6
structural rows populated from the entity's own image/title/description so the
block is VISIBLE in the STATIC screenshot). Gated by the design's own component
roles, so overlays WITHOUT episodes (card_hover_preview, rate_dialog) are
byte-identical. Generalizable — any media/streaming detail screen; no product
literals. Locks it in."""
from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    _episode_list_jsx_448, _screen_has_episodes_448, _render_reference_page)

_DESIGN = {
    "design_system": {"palette": {"bg": "#141414", "accent": "#e50914"},
                      "theme": {"default": "dark"}},
    "assets": [{"id": "b1", "file": "backdrops/b1.jpg", "type": "jpg",
                "dims": [1280, 720], "staged_path": "public/assets/backdrops/b1.jpg"}],
}


# ── unit: the episode-list JSX block ──────────────────────────────────────
def test_episode_jsx_is_data_driven_with_structural_fallback():
    out = _episode_list_jsx_448("#ffffff")
    assert "Episodes" in out and 'aria-label="Season"' in out, "header + season selector"
    # data-driven from the entity, structural fallback so it's visible when empty
    assert "cur.episodes" in out and "Array.from({ length: 6 })" in out
    assert "_titleOf(ep)" in out and "_subOf(ep)" in out
    # #782: still "runtime from the episode", but via the fallback accessor. Asserting the bare
    # spelling is what kept the defect alive — 17% of episode tables call it duration_minutes.
    assert "_durOf(ep)" in out, "runtime from the episode"
    assert "_refImg(ei)" in out or "_imgOf(ep)" in out, "per-row thumbnail"


# ── unit: episode detection from the design's own components ──────────────
def test_detects_episode_component():
    scr = {"components": [{"id": "ep-list", "role": "episode list rows with runtime"}]}
    assert _screen_has_episodes_448(scr) is True


def test_no_episode_component_detected():
    scr = {"components": [{"id": "hero", "role": "hero billboard title art"},
                          {"id": "rail", "role": "poster rail of Trending Now"}]}
    assert _screen_has_episodes_448(scr) is False


# ── integration: a detail overlay WITH episodes renders the list ──────────
_DETAIL_WITH_EPS = {"route": "/title/:id", "name": "title_detail", "kind": "overlay",
                    "components": [
                        {"id": "hero", "region": [0.2, 0.0, 0.8, 0.6],
                         "role": "hero still from the show", "assets": ["b1"]},
                        {"id": "actions", "region": [0.24, 0.51, 0.5, 0.6],
                         "role": "Play, add to list, thumbs-up action row"},
                        {"id": "episodes", "region": [0.24, 0.85, 0.77, 1.0],
                         "role": "'Episodes' section title with season selector"},
                        {"id": "ep1", "region": [0.24, 0.94, 0.77, 1.0],
                         "role": "first episode list item with index, thumbnail, "
                                 "title, duration, description"}]}


def _render(scr):
    return _render_reference_page(scr["name"], {"route": scr["route"]}, scr, _DESIGN,
                                  [("Home", "/browse")], "/api/titles/:id")


def test_detail_modal_with_episodes_renders_list():
    out = _render(_DETAIL_WITH_EPS)
    assert "fixed inset-0 z-50" in out, "still a detail modal (#447)"
    assert "Episodes" in out and 'aria-label="Season"' in out, "episode list present"
    assert "Array.from({ length: 6 })" in out, "structural rows so the block is visible"


# ── regression: a detail overlay WITHOUT episodes stays byte-identical ────
# a TRUE modal (#456: param route + 'detail' name) that has NO episode component
_DETAIL_NO_EPS = {"route": "/title/:id", "name": "title_detail", "kind": "page",
                  "components": [
                      {"id": "hero", "region": [0.2, 0.0, 0.8, 0.6],
                       "role": "detail still", "assets": ["b1"]},
                      {"id": "actions", "region": [0.24, 0.51, 0.5, 0.6],
                       "role": "play/add/like buttons"}]}


def test_modal_without_episodes_has_no_list():
    out = _render_reference_page("TitleDetail", {"route": "/title/:id"},
                                 _DETAIL_NO_EPS, _DESIGN, [("Home", "/browse")], "/api/titles/:id")
    assert "fixed inset-0 z-50" in out, "a param-route detail is still a modal (#456)"
    assert "aria-label=\"Season\"" not in out, "no episode list without an episode component"


def test_page_screen_never_gets_episode_list():
    # a plain browse page (not a modal) must never sprout an episode list
    scr = {"route": "/browse", "name": "browse_home", "kind": "page", "components": [
        {"id": "hero", "role": "hero billboard", "region": [0.0, 0.05, 1.0, 0.6]},
        {"id": "rail", "role": "poster rail of Trending Now",
         "region": [0.0, 0.65, 1.0, 0.85], "geometry": {"columns": 6}}]}
    out = _render_reference_page("BrowseHomePage", {"route": "/browse"}, scr, _DESIGN,
                                 [("Home", "/browse")], "/api/titles")
    assert 'aria-label="Season"' not in out


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
