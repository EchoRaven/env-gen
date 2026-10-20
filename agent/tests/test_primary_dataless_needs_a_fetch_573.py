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


# #1203qm: the real thing, not a copy of it. This file used to define a "mirror of the
# report expression under test (kept in one place)" and drive the mirror, so a change to
# production was invisible here -- mutation caught two such changes slipping through.
_primary_dataless = tur._primary_dataless_1203qm

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


def test_the_report_assembly_uses_the_one_owner():
    """#1203qm: the report must ASK the function, not carry its own copy of the rule.

    This replaces a source-text assertion that read a fixed 400-character window after
    `report["primary_dataless"]` (#943) -- it saw the one substring it quoted and missed
    both of the conjuncts below."""
    import ast
    import inspect
    tree = ast.parse(inspect.getsource(tur))
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id in ("_primary_dataless_1203qm", "_primary_route_sample_1203qm")]
    assert len(calls) == 2, "%d call site(s); the report must ask for both" % len(calls)


def test_an_unknown_seed_hit_does_not_fire_a_hold_that_cannot_escape():
    """#1026b on the modern era's second-commonest blocker. `route_seed_hit` is None when
    the probe could not tell; `is False` is what keeps an unknown from becoming a verdict,
    and FIX #152 means this hold never escapes."""
    assert _primary_dataless([_page("/", seed_hit=None, api_requests=5)]) is False
    assert _primary_dataless([_page("/", seed_hit=False, api_requests=5)]) is True


def test_a_blank_primary_route_belongs_to_blank_pages_not_here():
    """Two signals for one page would make the P0 name the wrong one."""
    assert _primary_dataless([_page("/", seed_hit=False, blank=True, api_requests=5)]) is False
    assert _primary_dataless([_page("/", seed_hit=False, blank=False, api_requests=5)]) is True



def _report_assignment_1203qm(key):
    """The AST node that writes `report[key]`, or None.

    A call-site COUNT cannot see arrival: `f(pages) and False` keeps the call and
    `report["other_key"] = f(pages)` keeps it too. So the WRITE is read structurally --
    the lesson from the write-site assertion that its own read sites fed."""
    import ast
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import test_user_runner as _tur
    for n in ast.walk(ast.parse(inspect.getsource(_tur))):
        if not isinstance(n, ast.Assign) or len(n.targets) != 1:
            continue
        t = n.targets[0]
        if (isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name)
                and t.value.id == "report" and isinstance(t.slice, ast.Constant)
                and t.slice.value == key):
            return n
    return None


def test_the_signal_is_written_from_the_owner_1203qm():
    """ARRIVAL. The mutation `_primary_dataless_1203qm(pages) and False` leaves the call in
    place, so only the shape of the WRITE shows that the answer reaches the report."""
    import ast
    node = _report_assignment_1203qm("primary_dataless")
    assert node is not None, "nothing writes report['primary_dataless']"
    assert isinstance(node.value, ast.Call), ast.dump(node.value)[:200]
    assert isinstance(node.value.func, ast.Name), ast.dump(node.value)[:200]
    assert node.value.func.id == "_primary_dataless_1203qm", node.value.func.id

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
