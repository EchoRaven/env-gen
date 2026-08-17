r"""#573 (netflix r137, live): `primary_dataless` (#231d) held delivery for 6 attempts / 38
minutes on a CORRECT app. Its premise is "the delivered app's FACE is showing an empty shell"
— r21: a feed rendering "No videos found" while the API served 39 rows. That premise only holds
for a page that ASKED the backend for data and got nothing onto the screen.

r137's primary route is a logged-out marketing landing: `LandingPage.jsx`, 198 lines, ZERO
`fetch(`, zero catalog markup — precisely what netflix.com serves at `/`. It renders no seed
value because it is not a data surface, and the gate read that as an unusable app. Worse, the
deferral message did not even name the signal (#572), so the frontend's P0 said nothing.

Fix: require the primary route to have issued at least one `/api/` request, measured at runtime
from the Resource Timing buffer (`performance.getEntriesByType('resource')`) — no driver wiring,
no source parsing. Unknown (`None`/`-1`, older probe or unsupported API) keeps the old
behaviour; only a provable ZERO suppresses the hold.
"""
import pytest

from env_generator.llm_generator.multi_agent.runtime import test_user_runner as tur


def _page(route, *, seed_hit=False, blank=False, api_requests=None, name=None):
    return {"name": name or route, "route": route, "route_seed_hit": seed_hit,
            "blank": blank, "api_requests": api_requests}


def _primary_dataless(pages):
    """Mirror of the report expression under test (kept in one place)."""
    return any(
        str(p.get("route") or "").rstrip("/") in ("", "/")
        and p.get("route_seed_hit") is False and not p.get("blank")
        and p.get("api_requests") != 0
        for p in pages)


def test_r137_a_landing_page_that_never_fetched_is_not_an_empty_shell():
    assert _primary_dataless([_page("/", api_requests=0, name="landing")]) is False


def test_r21_a_feed_that_fetched_and_rendered_nothing_still_holds():
    """The motivating case must keep every tooth."""
    assert _primary_dataless([_page("/", api_requests=3, name="feed")]) is True


def test_unknown_request_count_keeps_the_previous_behaviour():
    for unknown in (None, -1):
        assert _primary_dataless([_page("/", api_requests=unknown)]) is True


def test_a_blank_or_data_bearing_primary_is_unaffected():
    assert _primary_dataless([_page("/", api_requests=3, blank=True)]) is False   # blank_pages owns it
    assert _primary_dataless([_page("/", api_requests=3, seed_hit=True)]) is False


def test_only_the_primary_route_is_considered():
    pages = [_page("/browse", api_requests=3), _page("/my-list", api_requests=3)]
    assert _primary_dataless(pages) is False


def test_the_probe_reports_api_request_counts():
    """The runtime side of the fix: the probe must actually collect the number."""
    assert "apiReqs" in tur._PROBE
    assert "getEntriesByType('resource')" in tur._PROBE
    assert "apiReqs: apiReqs" in tur._PROBE
    assert "apiReqs = -1" in tur._PROBE, "unsupported must degrade to UNKNOWN, not to zero"


def test_the_report_expression_requires_a_fetch():
    """Guard against the condition being dropped in a future edit."""
    import inspect
    src = inspect.getsource(tur)
    i = src.index('report["primary_dataless"]')
    assert 'p.get("api_requests") != 0' in src[i:i + 400], src[i:i + 400]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
