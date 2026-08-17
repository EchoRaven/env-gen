"""#449 (netflix player/player_controls: the projector emitted only Play + title +
Fullscreen on the full-screen media surface, so most player chrome — a scrub bar
with playhead, pause, skip ∓10, volume, next-episode, episodes/queue, captions,
fullscreen + time-remaining — was MISSING, a components/iconography drag on 2
screens; the visual gate scores STATIC screenshots so the controls must be
rest-visible). FIX: a video-PLAYER screen (name/route/component-role gated) gets
the full control cluster; a generic media surface (live-stream featured area)
keeps the minimal chrome. Generalizable — any video player; no product literals.
Locks it in."""
from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    _player_controls_jsx_449, _screen_is_player_449, _render_reference_page)

_DESIGN = {
    "design_system": {"palette": {"bg": "#000000", "accent": "#e50914"},
                      "theme": {"default": "dark"}},
    "assets": [{"id": "v1", "file": "video/v1.mp4", "type": "video",
                "staged_path": "public/assets/video/v1.mp4"}],
}


# ── unit: the control-cluster JSX ─────────────────────────────────────────
def test_player_controls_have_scrub_and_full_cluster():
    out = _player_controls_jsx_449("#e50914")
    # scrub bar with an accent playhead + time-remaining
    assert "#e50914" in out and "width: '35%'" in out, "accent-filled scrub + playhead"
    assert "\\u2212" in out, "time-remaining readout"
    # full control cluster
    for lbl in ('aria-label="Pause"', 'aria-label="Rewind 10 seconds"',
                'aria-label="Forward 10 seconds"', 'aria-label="Volume"',
                'aria-label="Next episode"', 'aria-label="Episodes"',
                'aria-label="Subtitles"', 'aria-label="Fullscreen"'):
        assert lbl in out, f"missing control: {lbl}"
    assert ">CC<" in out, "captions rendered as a CC badge"


# ── unit: player detection ────────────────────────────────────────────────
def test_detects_player_by_name():
    assert _screen_is_player_449({"name": "player_controls", "route": "/x"}) is True
    assert _screen_is_player_449({"name": "player", "route": "/watch/:id"}) is True


def test_detects_player_by_route():
    assert _screen_is_player_449({"name": "x", "route": "/watch/:id"}) is True


def test_detects_player_by_component_role():
    scr = {"name": "x", "route": "/x", "components": [
        {"id": "c", "role": "horizontal scrub bar with chapter ticks and playhead"}]}
    assert _screen_is_player_449(scr) is True


def test_generic_media_surface_not_a_player():
    scr = {"name": "live_home", "route": "/live", "components": [
        {"id": "feat", "role": "featured live stream video area"},
        {"id": "rail", "role": "stream thumbnails rail"}]}
    assert _screen_is_player_449(scr) is False


# ── integration: a player screen renders the full cluster ─────────────────
_PLAYER = {"route": "/watch/:id", "name": "player_controls", "components": [
    {"id": "video", "region": [0.0, 0.0, 1.0, 0.93],
     "role": "main video playback area filling the screen"},
    {"id": "scrub", "region": [0.0, 0.93, 0.96, 0.96],
     "role": "horizontal scrub bar with chapter ticks and playhead"},
    {"id": "cc", "region": [0.9, 0.96, 0.95, 1.0], "role": "subtitles/captions toggle"}]}


def test_player_screen_renders_full_controls():
    out = _render_reference_page("PlayerControls", {"route": "/watch/:id"}, _PLAYER,
                                 _DESIGN, [("Home", "/browse")], "")
    assert 'aria-label="Pause"' in out and 'aria-label="Subtitles"' in out
    assert 'aria-label="Rewind 10 seconds"' in out, "skip controls present"
    assert "width: '35%'" in out, "scrub bar present"
    # the minimal single-Play chrome must be gone for player screens
    assert out.count('aria-label="Play"') == 0, "player uses Pause, not the minimal Play chrome"


# ── regression: a PLAYER screen marked kind=overlay (player_controls IS
#    kind=overlay in the real design) must render as the media surface, NOT a
#    detail modal — a player detected by name/role beats the overlay→modal rule ──
def test_player_controls_overlay_kind_is_not_a_modal():
    scr = {"route": "/player-controls", "name": "player_controls", "kind": "overlay",
           "components": [
               {"id": "video", "region": [0.0, 0.0, 1.0, 0.93],
                "role": "main video playback area filling the screen"},
               {"id": "scrub", "region": [0.0, 0.93, 0.96, 0.96],
                "role": "horizontal scrub bar with chapter ticks and playhead"}]}
    out = _render_reference_page("PlayerControls", {"route": "/player-controls"}, scr,
                                 _DESIGN, [("Home", "/browse")], "")
    assert "fixed inset-0 z-50" not in out, "a player is not a detail modal, even kind=overlay"
    assert 'aria-label="Pause"' in out and "width: '35%'" in out, "renders player chrome"


# ── regression: an EPISODE-LIST screen with a 'next episode row' must NOT be
#    misread as a player (the ambiguous 'next episode' term was dropped) ──
def test_episode_row_screen_is_not_a_player():
    scr = {"route": "/title/:id/episodes", "name": "title_episodes", "kind": "overlay",
           "components": [
               {"id": "eplist", "region": [0.24, 0.11, 0.76, 0.17],
                "role": "section header 'Episodes' with season selector"},
               {"id": "row6", "region": [0.24, 0.86, 0.76, 1.0],
                "role": "partially visible next episode row indicating scrollable list"}]}
    assert _screen_is_player_449(scr) is False, "'next episode row' is a list item, not a player"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
