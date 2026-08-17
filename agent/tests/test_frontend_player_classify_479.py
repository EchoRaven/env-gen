"""#479 — page-type mis-classification: a SINGLE ambiguous control term made the projector
render whole catalog pages as video players. r52 (CLEAN verdict): browse_by_languages'
'Subtitles' language-selector dropdown → _screen_is_player_449 True → the page rendered as a
video player (0.20, biggest single miss); r49: my_list 'video player hero'. FIX: require a
player-EXCLUSIVE control (scrub/playhead/skip/playback-area/pause) OR >=2 DISTINCT control
terms; a lone subtitles/captions/fullscreen/progress-bar no longer triggers. Real player/
player_controls screens still match via name/route. Generalizable, no product literals."""
from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    _screen_is_player_449)


def _s(name="", route="", comps=None):
    return {"name": name, "route": route, "components": comps or []}


def _c(role):
    return {"role": role}


def test_languages_selector_not_player():
    s = _s("browse_by_languages", "/browse/languages",
           [_c("first selector dropdown showing Original Language / Subtitles")])
    assert _screen_is_player_449(s) is False, "#479: a 'Subtitles' language selector is NOT a player"


def test_lone_progress_bar_not_player():
    s = _s("my_list", "/my-list", [_c("continue-watching card with a progress bar")])
    assert _screen_is_player_449(s) is False, "#479: a lone continue-watching progress bar is not a player"


def test_real_player_by_route():
    assert _screen_is_player_449(_s("player", "/watch/:id", [])) is True


def test_real_player_by_strong_control():
    s = _s("featured", "/featured", [_c("scrub bar with playhead and skip forward")])
    assert _screen_is_player_449(s) is True, "#479: a player-exclusive control (scrub/playhead) → player"


def test_control_cluster_two_terms_is_player():
    s = _s("watch_area", "/media", [_c("captions toggle"), _c("fullscreen button")])
    assert _screen_is_player_449(s) is True, "#479: >=2 distinct control terms = a real control cluster"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
