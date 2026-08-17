"""#426 (netflix r16/r18/r20: player 0.05-0.15, worst screen): the player screen
shipped UN-projected (lane's fetch-error page) even though the design marks it
projectable (screen 'player', kind=page, route /watch/:titleId, video-surface +
control components). ROOT: _project_page_component gated the structured projection
on `if get_ep:` — the player ui_page has no collection GET (its data comes from a
param-fetched title), so get_ep was falsy → the design screen was skipped → the
lane's page won. And relaxing the gate NAIVELY would emit fetch('') (empty get_ep)
→ HTML → JSON.parse error = the same fetch-error. FIX: (1) compute the design
screen regardless of get_ep and project when matched; (2) _render_reference_page
SKIPS its data fetch when get_ep is empty (no broken fetch('')). Screens WITH a GET
are unchanged; screens with NO design match still fall to the get_ep-gated floor.
Generalizable (any param/detail/media screen). Locks it in."""
from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    _project_page_component)
from env_generator.llm_generator.multi_agent.runtime.frontend_page_projector import (
    _STRUCTURED_MARKER)

_D_PLAYER = {
    "design_system": {"palette": {"bg": "#141414", "accent": "#e50914"},
                      "theme": {"default": "dark"}},
    "assets": [{"id": "movie-1", "file": "backdrops/movie_1.jpg", "type": "jpg",
                "dims": [1280, 720],
                "staged_path": "public/assets/backdrops/movie_1.jpg"}],
    "screens": [{"name": "player", "route": "/watch/:titleId", "kind": "page",
                 "components": [
                     {"id": "video-surface", "region": [0.0, 0.0, 1.0, 1.0],
                      "role": "full-screen video player background"},
                     {"id": "back-button", "region": [0.0, 0.0, 0.06, 0.09],
                      "role": "top-left back arrow"}]}],
}


def _player(apis):
    page = {"route": "/watch/:titleId", "id": "player", "component": "PlayerPage",
            "apis_used": apis}
    return _project_page_component("PlayerPage", page, nav_routes=[], design=_D_PLAYER)


def test_player_projects_structured_without_a_get():
    out = _player([])  # NO GET endpoint
    assert (_STRUCTURED_MARKER in out) or ('data-projected="ref"' in out), \
        "a design-matched player screen must project even without a GET"


def test_player_no_broken_empty_fetch():
    out = _player([])
    assert "fetch('')" not in out and 'fetch("")' not in out, \
        "must NOT emit fetch('') (would reproduce the JSON-parse fetch-error)"
    assert "render structure without a data fetch" in out  # the no-fetch guard fired


def test_get_screen_still_fetches_unchanged():
    D = {"design_system": _D_PLAYER["design_system"], "assets": _D_PLAYER["assets"],
         "screens": [{"name": "movies", "route": "/movies", "kind": "page",
                      "components": [{"id": "rail", "region": [0, 0.2, 1, 0.9],
                                     "role": "poster rail",
                                     "geometry": {"columns": 6, "rows": 1}}]}]}
    page = {"route": "/movies", "id": "movies", "component": "MoviesPage",
            "apis_used": ["GET /api/titles"]}
    out = _project_page_component("MoviesPage", page, nav_routes=[], design=D)
    assert "/api/titles" in out, "a screen WITH a GET must still fetch it (unchanged)"


def test_no_design_match_no_get_falls_through():
    # a page with NO matching design screen + no GET → not structured (unchanged
    # generic fallback path; the gate relaxation only fires on a design match)
    out = _project_page_component(
        "RandomPage", {"route": "/random", "id": "random", "apis_used": []},
        nav_routes=[], design=_D_PLAYER)
    assert _STRUCTURED_MARKER not in out and 'data-projected="ref"' not in out


def test_player_backdrop_fallback_not_empty_black():
    # #427: with no video DATA, the media surface falls back to a full-bleed staged
    # backdrop (not empty-black) — r21 player scored 0.12 as "empty black screen".
    out = _player([])
    assert "_refImg(0)" in out, "player must fall back to a staged backdrop when no video"
    assert "absolute inset-0 h-full w-full object-cover" in out


def test_player_has_control_chrome():
    # #427/#449: a full-screen PLAYER surface shows the full control cluster
    # (reference flagged 'missing all player chrome'). #449 upgraded the minimal
    # Play+Fullscreen chrome to Pause + scrub + skip/volume/next/episodes/CC.
    out = _player([])
    assert 'aria-label="Back"' in out
    assert 'aria-label="Pause"' in out, "#449: player uses Pause (playing state), not Play"
    assert 'aria-label="Fullscreen"' in out
    # #449 richer cluster
    assert 'aria-label="Rewind 10 seconds"' in out and 'aria-label="Subtitles"' in out


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
