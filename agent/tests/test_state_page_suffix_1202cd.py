"""#1202cd — the framework's own `StatePage` suffix stopped its pages matching their screens.

The scaffolder names a screen's dedicated page `<screen>StatePage`, and `_match_ui_page`
demands token EQUALITY, so the extra `state` token made every such page fail to match the
reference screen it was built for.

r35 live: `player_controls` was reported as an unjudged declared screen SEVEN times ("an
unbuilt page is not exempt from its own exam — author the page so it can be captured and
scored") while PlayerControlsStatePage.jsx and its route /watch/:titleId/controls both
existed and the page was registered as implemented. The lane answered by writing a
48-character components/player_controls.jsx and the gate blocked again.

LOCAL-ONLY (agent/tests/ gitignored).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.visual_fidelity import (  # noqa: E402
    _screen_name_tokens as T, _UI_PAGE_STOPWORDS)

# Every *StatePage the scaffolder emitted in r35, against the reference screen each was
# built for.
STATE_PAGES = [
    ("player_controls", "player_controls_state_page", "PlayerControlsStatePage"),
    ("card_hover_preview", "card_hover_preview_state_page", "CardHoverPreviewStatePage"),
    ("card_preview", "card_preview_state_page", "CardPreviewStatePage"),
    ("rate_dialog", "rate_dialog_state_page", "RateDialogStatePage"),
]

# r35's 20 measured reference screens.
REFERENCE_SCREENS = [
    "account_menu", "browse_by_languages", "browse_home", "browse_home_rows",
    "card_hover_preview", "card_preview", "games", "genre_category", "landing", "login",
    "movies", "my_list", "new_and_popular", "player_controls", "player", "rate_dialog",
    "shows_genres_menu", "shows", "title_detail", "title_episodes",
]


def test_state_is_treated_as_a_scaffolding_word():
    assert "state" in _UI_PAGE_STOPWORDS


def test_every_state_page_matches_the_screen_it_was_built_for():
    for screen, page_name, component in STATE_PAGES:
        assert T(screen) == T(page_name, component), screen


def test_the_r35_blocker_specifically():
    """The one the gate blocked on seven times."""
    assert T("player_controls") == T("player_controls_state_page", "PlayerControlsStatePage")


def test_variant_screens_stay_distinct_from_their_base():
    """THE control. Equality (not overlap) exists so a variant cannot graft onto the base
    page; `rows`, `hover` and `episodes` are distinct reference screens and must stay so.
    Widening the stopword list is only safe while this holds."""
    assert T("browse_home") != T("browse_home_rows")
    assert T("card_preview") != T("card_hover_preview")
    assert T("title_detail") != T("title_episodes")
    assert T("player") != T("player_controls")


def test_no_two_reference_screens_collapse_together():
    """Measured over r35's full reference set: dropping `state` must not make any two
    screens indistinguishable, or one could be judged against the other's picture."""
    seen = {}
    for name in REFERENCE_SCREENS:
        key = frozenset(T(name))
        assert key not in seen, f"{name} collides with {seen.get(key)}"
        seen[key] = name


def test_page_and_screen_remain_stopwords():
    """The pre-existing behaviour this rides on: browse_home <-> BrowseHomePage."""
    assert T("browse_home") == T("browse_home_page", "BrowseHomePage")
