r"""#916: driving two source-only detectors, and the defect that fell out.

Item 262's targeted pass. Both wipeout detectors on the visual gate had tests that only read their
SOURCE. They are pure functions of two and three arguments, so "unverifiable" was never the reason —
nobody had called them.

`_auth_wipeout_655` decides whether EVERY authenticated route bounced to /login. A True abandons the
entire round:

    return {"passed": False, "auth_unavailable": True, "screens": [], ...}

which is the all-screens-unjudged state #892 exists to prevent.

★ **The defect, found on the third input.** `s.get("route")` is `None` for a screen with no route,
so ONE route-less bounced screen put `None` into `bounced_routes`, and then EVERY route-less auth
screen matched it and counted as covered — a wholesale auth wipeout inferred from two missing
fields. Two screens, neither routed, one bounced → `True`.

    corpus: 140 route-less design screens across 7 runs — and NONE marked `auth`

So it is **latent, not live**, and this file says so rather than dressing it up. Fixed anyway: two
lines, and the failure mode is silent and expensive. The direction is deliberate — missing a wipeout
leaves the round to judge those screens (low scores, recoverable); inventing one throws away a whole
round of real work.

That is the fourth appearance this session of a missing value used as if it were a real one (#902's
blank route as the site root, #907's empty cache as an empty tree, #908's empty child_meta answered
as data). Here `None` was a route key.
"""
import pytest

from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf


# --------------------------------------------------------------------------- _auth_wipeout_655

def test_no_auth_screens_is_never_a_wipeout():
    assert vf._auth_wipeout_655([{"name": "a", "route": "/a"}], ["a"]) is False


def test_every_auth_route_bounced_is_a_wipeout():
    assert vf._auth_wipeout_655([{"name": "a", "route": "/a", "auth": True}], ["a"]) is True


def test_one_auth_route_surviving_is_not_a_wipeout():
    """#655's own point: a PARTIAL auth failure is a real per-route bug, not a session collapse."""
    screens = [{"name": "a", "route": "/a", "auth": True},
               {"name": "b", "route": "/b", "auth": True}]
    assert vf._auth_wipeout_655(screens, ["a"]) is False


def test_it_matches_by_ROUTE_not_by_screen():
    """Two screens on one route: bouncing either proves the route bounced. That is the whole
    reason #655 keys on routes, and it is asserted here by running it."""
    screens = [{"name": "a", "route": "/x", "auth": True},
               {"name": "b", "route": "/x", "auth": True}]
    assert vf._auth_wipeout_655(screens, ["a"]) is True


def test_nothing_bounced_is_not_a_wipeout():
    assert vf._auth_wipeout_655([{"name": "a", "route": "/a", "auth": True}], None) is False
    assert vf._auth_wipeout_655([{"name": "a", "route": "/a", "auth": True}], []) is False


def test_a_routeless_screen_cannot_manufacture_a_wipeout():
    """★ The defect. Before #916 this returned True: `None` went into `bounced_routes` and then
    matched every other route-less screen."""
    screens = [{"name": "a", "auth": True}, {"name": "b"}]
    assert vf._auth_wipeout_655(screens, ["b"]) is False


def test_a_blank_route_counts_as_no_route():
    """`""` and `"  "` are absent routes wearing a string — the same collapse one type along."""
    screens = [{"name": "a", "route": "  ", "auth": True}, {"name": "b", "route": ""}]
    assert vf._auth_wipeout_655(screens, ["b"]) is False


def test_a_routeless_auth_screen_THAT_BOUNCED_still_counts():
    """★ #655's own case, and the one my first fix broke. Both auth screens bounced, one of them
    unrouted — that IS a session collapse, and `test_a_screen_with_no_route_is_handled` has said
    so since #655. I wrote the loss up as a deliberate trade; the existing test said otherwise and
    was right.

    The distinction the fix now makes: a screen is covered when its ROUTE is known to have
    bounced, OR when the screen ITSELF bounced — the latter needs no route."""
    screens = [{"name": "a", "auth": True}, {"name": "b", "route": "/b", "auth": True}]
    assert vf._auth_wipeout_655(screens, ["a", "b"]) is True
    assert vf._auth_wipeout_655(screens, ["b"]) is False


# --------------------------------------------------------------------------- _blank_wipeout_656

def test_no_blank_screens_is_not_a_wipeout():
    assert vf._blank_wipeout_656([{"name": "a"}], [], {"a": 1}) is False


def test_no_shots_at_all_is_the_total_blackout_case():
    assert vf._blank_wipeout_656([{"name": "a"}], ["a"], {}) is True


def test_a_majority_of_blocking_screens_blank_is_a_wipeout():
    results = [{"name": "a", "blank": True}, {"name": "b"}]
    assert vf._blank_wipeout_656(results, ["a"], {"a": 1}) is True


def test_a_minority_is_not():
    results = [{"name": "a", "blank": True}, {"name": "b"}, {"name": "c"}]
    assert vf._blank_wipeout_656(results, ["a"], {"a": 1}) is False


def test_advisory_screens_do_not_count_toward_the_majority():
    """An advisory screen is excluded from the verdict's arithmetic everywhere else; a blank one
    must not be able to declare a wipeout on its own."""
    results = [{"name": "a", "blank": True, "advisory": True}]
    assert vf._blank_wipeout_656(results, ["a"], {"a": 1}) is False


def test_no_blocking_results_is_not_a_wipeout():
    """Conservative by construction — `bool(blocking)` guards the ratio, so an empty result set
    cannot divide its way into a wipeout."""
    assert vf._blank_wipeout_656([], ["a"], {"a": 1}) is False


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
