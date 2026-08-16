"""#436 (netflix r29: the top nav on EVERY screen shipped stray items 'search',
'notifications', 'and profile' as nav LINKS — judge on browse_home/games/
browse_home_rows: "Nav includes stray 'and profile' label", "'Log out' text
replaces avatar menu", wrong nav order). Root cause: _ref_nav_labels captured
the enumerated nav labels with a GREEDY (.+)$, so for a top-nav-bar role
'…(Home, …, Browse by Languages), search, notifications, and profile' it pulled
the utility cluster from AFTER the closing paren into the label list — and that
inflated 10-item list then WON the most-labels selection over the clean 7-item
primary-nav-links. FIX: stop the capture at the first ')'; strip an oxford-comma
'and '/'& ' head. Generalizable — parses the design's own nav enumeration, no
product literals. Locks it in."""
from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    _ref_nav_labels, _ref_nav_jsx)


# ── #443: profile avatar chip + caret on the top nav (most-cited missing component) ──
def test_top_nav_renders_profile_avatar_chip():
    out = _ref_nav_jsx([("Home", "/browse"), ("Movies", "/browse/movies")], "#e50914",
                       vertical=False, design={"design_system": {"palette": {"accent": "#e50914"}}})
    assert 'aria-label="Profile"' in out and "#e50914" in out, "accent avatar chip present"
    # #859: same correction as test_frontend_control_bar — the caret must be present and DRAWN,
    # not spelled. Three independent tests asserting a glyph is how #782 survived 122 rounds.
    assert 'd="M6 9l6 6 6-6"' in out, "avatar caret present and drawn"
    assert "\u25be" not in out, "a typed caret is the #859 defect"


def test_vertical_nav_has_no_avatar_chip():
    out = _ref_nav_jsx([("Home", "/browse")], "#e50914", vertical=True, design={})
    assert 'aria-label="Profile"' not in out, "avatar chip is a top-bar element only"


def _design(*roles):
    return {"screens": [{"name": f"s{i}", "components": [
        {"id": "primary-nav-links", "role": r}]} for i, r in enumerate(roles)]}


def test_paren_enumeration_stops_at_closing_paren():
    d = _design("top navigation bar with logo, primary nav links "
                "(Home, Shows, Movies, Games, New & Popular, My List, Browse by Languages), "
                "search, notifications, and profile")
    assert _ref_nav_labels(d) == ["Home", "Shows", "Movies", "Games",
                                   "New & Popular", "My List", "Browse by Languages"]


def test_no_stray_utility_or_and_profile():
    d = _design("horizontal nav (Home, Shows, Movies), search, notifications, and profile")
    labels = _ref_nav_labels(d)
    assert "and profile" not in labels and "search" not in labels and "notifications" not in labels
    assert labels == ["Home", "Shows", "Movies"]


def test_colon_enumeration_still_works():
    d = _design("horizontal primary nav: Home, Shows, Movies, Games, New & Popular")
    assert _ref_nav_labels(d) == ["Home", "Shows", "Movies", "Games", "New & Popular"]


def test_oxford_and_head_stripped():
    # a tail item introduced by 'and' must not be labelled 'and X'
    d = _design("nav (Home, Shows and Movies)")
    labels = _ref_nav_labels(d)
    assert not any(l.lower().startswith("and ") for l in labels)


def test_inflated_bad_role_does_not_win_over_clean():
    # the polluted top-nav-bar role must NOT beat the clean primary-nav-links
    d = {"screens": [
        {"name": "a", "components": [{"id": "primary-nav-links",
            "role": "nav (Home, Shows, Movies, Games, New & Popular, My List, Browse by Languages)"}]},
        {"name": "b", "components": [{"id": "top-nav-bar",
            "role": "nav links (Home, Shows, Movies, Games, New & Popular, My List, Browse by Languages), search, notifications, and profile"}]},
    ]}
    labels = _ref_nav_labels(d)
    assert "and profile" not in labels and len(labels) == 7


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
