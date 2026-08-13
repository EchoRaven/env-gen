r"""#655: one lucky screen vetoed the auth re-mint retry for the other ten.

Found by mining the judge's `deviations` — a structured field with 7320 entries that had never
been opened. Unlike `components.missing` (cosmetic), it carries FUNCTIONAL failures:

    43 auth-guard rejections over 11 runs      27 blank/never-hydrated SPA routes over 7 runs

The auth text is framework-generated, so there is already a detector: `capture_route_screenshots`
records every route that redirected to `/login`, and #105 added a one-shot re-mint + re-capture
because a wholesale rejection is usually a race (a parallel validation cycle reset the DB or
rotated the JWT keys between the mint and the capture).

The retry fired only when EVERY auth screen bounced — but `_auth_bounced` is keyed by screen
NAME, while bouncing is a property of the ROUTE. Several screens routinely share one route, and
the bounce is flaky per capture. r30, verbatim:

    scored   sim=0.30   browse_by_languages   /browse
    BOUNCED  sim=0.00   browse_home           /browse     <- same route, same token,
    BOUNCED  sim=0.00   card_hover_preview    /browse     <- same capture pass
    BOUNCED  sim=0.00   ... 8 more, covering every remaining auth route

10 of 12 screens scored 0.0, `auth_unavailable` stayed False, and no re-mint was attempted —
because one screen on an already-bouncing route happened to come back. r49 and r68 are the same
shape; together those three runs are 30 of the 43 auth-bounce records.

Counting by route restores the intent. A genuinely partial failure (r43: 4 routes, the rest
fine) still gets no retry — that is a real per-route auth bug, and the deviation already says
so: *"fix the route's auth handling, not its styling"*.
"""
import pytest

from env_generator.llm_generator.multi_agent.runtime.visual_fidelity import (
    _auth_wipeout_655 as wipeout,
)


def _s(name, route, auth=True):
    return {"name": name, "route": route, "auth": auth}


# r30's actual screen set, with login as the one unauthenticated screen.
_R30 = [_s("browse_by_languages", "/browse"), _s("browse_home", "/browse"),
        _s("card_hover_preview", "/browse"), _s("games", "/games"),
        _s("landing", "/"), _s("movies", "/movies"), _s("my_list", "/my-list"),
        _s("new_and_popular", "/new"), _s("player", "/watch/:titleId"),
        _s("shows", "/shows"), _s("title_detail", "/title/:id"),
        _s("login", "/login", auth=False)]

_R30_BOUNCED = ["browse_home", "card_hover_preview", "games", "landing", "movies",
                "my_list", "new_and_popular", "player", "shows", "title_detail"]


# --- the defect -----------------------------------------------------------------------------

def test_the_r30_shape_now_counts_as_a_wipeout():
    """10 of 11 auth screens bounced; the survivor sits on an already-bouncing route."""
    assert wipeout(_R30, _R30_BOUNCED) is True


def test_the_old_name_keyed_test_would_have_said_no():
    """Pinning the bug so the regression is visible if anyone reverts the keying."""
    auth_names = {s["name"] for s in _R30 if s.get("auth")}
    assert not set(_R30_BOUNCED) >= auth_names       # what the code used to ask
    assert wipeout(_R30, _R30_BOUNCED)               # what it asks now


def test_one_screen_per_route_behaves_exactly_as_before():
    screens = [_s("a", "/a"), _s("b", "/b")]
    assert wipeout(screens, ["a", "b"]) is True
    assert wipeout(screens, ["a"]) is False


# --- it must not fire for a genuinely partial failure ---------------------------------------------

def test_a_route_that_never_bounced_still_blocks_the_retry():
    """r43: 4 routes bounced, the rest captured fine — a real per-route auth bug."""
    screens = [_s("a", "/a"), _s("b", "/b"), _s("c", "/c"), _s("d", "/d")]
    assert wipeout(screens, ["a", "b"]) is False


def test_a_sibling_on_a_clean_route_does_not_get_dragged_in():
    """Route-keying must only spread WITHIN a route, never across routes."""
    screens = [_s("x1", "/x"), _s("x2", "/x"), _s("y", "/y")]
    assert wipeout(screens, ["x1"]) is False
    assert wipeout(screens, ["x1", "y"]) is True


def test_nothing_bounced_is_not_a_wipeout():
    assert wipeout(_R30, []) is False
    assert wipeout(_R30, None) is False


# --- degenerate inputs ------------------------------------------------------------------------

def test_a_run_with_no_auth_screens_never_triggers():
    """An all-public app must not burn a re-mint + re-capture."""
    assert wipeout([_s("login", "/login", auth=False)], ["login"]) is False
    assert wipeout([], []) is False


def test_unauthenticated_screens_are_ignored_on_both_sides():
    screens = [_s("a", "/a"), _s("login", "/login", auth=False)]
    assert wipeout(screens, ["a"]) is True, "login must not be required to bounce"


def test_a_screen_with_no_route_is_handled():
    screens = [{"name": "a", "auth": True}, _s("b", "/b")]
    assert wipeout(screens, ["b"]) is False
    assert wipeout(screens, ["a", "b"]) is True


def test_an_unknown_bounced_name_is_ignored():
    """The bounce list is populated by the capture; a stale name must not fabricate a wipeout."""
    assert wipeout([_s("a", "/a")], ["ghost"]) is False


def test_it_is_pure_and_does_not_mutate_its_inputs():
    screens = [dict(s) for s in _R30]
    bounced = list(_R30_BOUNCED)
    wipeout(screens, bounced)
    assert screens == [dict(s) for s in _R30] and bounced == _R30_BOUNCED


# --- wiring ---------------------------------------------------------------------------------

def test_both_decision_points_use_it():
    """The pre-retry check and the post-retry give-up check must agree."""
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf
    src = inspect.getsource(vf.run_visual_fidelity)
    assert src.count("_auth_wipeout_655(judged_screens, _auth_bounced)") == 2
    assert "set(_auth_bounced) >= set(_auth_routes)" not in src


def test_the_measurement_is_recorded():
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf
    flat = " ".join(inspect.getsource(vf._auth_wipeout_655).replace("#", " ").split())
    assert "30 of the 43 auth-bounce records" in flat
    assert "10 of 12 screens scored 0.0" in flat


def test_why_a_partial_failure_is_left_alone_is_recorded():
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf
    flat = " ".join(inspect.getsource(vf._auth_wipeout_655).split())
    assert "real per-route auth bug" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
