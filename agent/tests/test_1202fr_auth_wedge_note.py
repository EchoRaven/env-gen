"""#1202fr -- when a critical UI flow fails, say whether the CONTRACT marks one of the
endpoints that page declares as auth_required.

#320 already names this class in backend_skeleton: an explicit `auth_required: false` is
"the lane's deliberate 'this read is public' declaration (r88/r89's PUBLIC-FEED WEDGE)".
The declaration exists; nothing said when the wedge had happened. tiktok-r96 set
auth_required: true on GET /api/videos — the only feed endpoint — and the logged-out
landing page could never render. 4 of that run's 12 failing flows, rediscovered by browser
walk each time and reported as "the page did not work", while the route is
framework-projected and only the contract could change.

Reports, never blocks: an app whose entry is a login screen legitimately serves an
authenticated feed, and deciding that from a route shape would be a guess.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "env_generator" / "llm_generator"))

from multi_agent.runtime.deliverability import _auth_wedge_note_1202fr  # noqa: E402

PAGES = {
    "feed": {"name": "fyp_feed_logged_out", "route": "/",
             "apis_used": ["GET /api/videos", "POST /api/videos/{id}/like"]},
    "explore": {"name": "explore_grid", "route": "/explore",
                "apis_used": ["GET /api/explore"]},
}
ENDPOINTS = {
    "GET /api/videos": {"method": "GET", "path": "/api/videos",
                        "schema": {"auth_required": True}},
    "GET /api/explore": {"method": "GET", "path": "/api/explore",
                         "schema": {"auth_required": False}},
    "POST /api/videos/{id}/like": {"method": "POST", "path": "/api/videos/{id}/like",
                                   "schema": {"auth_required": True}},
}


class _Reg:
    def __init__(self, pages=PAGES, eps=ENDPOINTS):
        self._p, self._e = pages, eps

    def list_ui_pages(self):
        return self._p

    def get_endpoints(self):
        return self._e


class _Hubs:
    def __init__(self, **kw):
        self.registryhub = _Reg(**kw)


def test_names_the_page_and_the_endpoint():
    note = _auth_wedge_note_1202fr(_Hubs(), ["fyp_feed_logged_out"])
    assert "fyp_feed_logged_out" in note and "GET /api/videos" in note, note


def test_silent_when_the_failing_flow_uses_only_public_endpoints():
    assert _auth_wedge_note_1202fr(_Hubs(), ["explore_grid"]) == ""


def test_silent_when_nothing_failed():
    assert _auth_wedge_note_1202fr(_Hubs(), []) == ""
    assert _auth_wedge_note_1202fr(_Hubs(), None) == ""


def test_only_failing_flows_are_annotated():
    """It must not lecture about pages the run has no complaint about."""
    note = _auth_wedge_note_1202fr(_Hubs(), ["explore_grid"])
    assert "fyp_feed_logged_out" not in note


def test_reports_a_condition_not_a_verdict():
    """#1114/#1023: a flow that authenticates first never sees the 401, so this must read
    as evidence, not as a diagnosis."""
    note = _auth_wedge_note_1202fr(_Hubs(), ["fyp_feed_logged_out"]).lower()
    assert "anonymous visitor" in note
    for asserted in ("contract cause", "the cause is", "because the contract"):
        assert asserted not in note, f"states a verdict: {asserted!r}"


def test_carries_neither_gate_anchor_phrase():
    """The text is appended after the anchored blocker prefix that
    orchestrator._validate_delivery_gate canonicalises on."""
    note = _auth_wedge_note_1202fr(_Hubs(), ["fyp_feed_logged_out"]).lower()
    assert "ui flow(s) failed" not in note and "ui flow(s) missing" not in note


def test_auth_required_read_from_any_of_the_three_spellings():
    for shape in ({"auth_required": True},
                  {"schema": {"auth_required": True}},
                  {"metadata": {"auth_required": True}}):
        eps = {"GET /api/videos": dict(shape, method="GET", path="/api/videos")}
        note = _auth_wedge_note_1202fr(_Hubs(eps=eps), ["fyp_feed_logged_out"])
        assert "GET /api/videos" in note, f"missed the {shape} spelling"


def test_registry_hiccup_degrades_to_empty_not_to_a_raise():
    class _Bad:
        def list_ui_pages(self):
            raise RuntimeError("hub down")

        def get_endpoints(self):
            return {}

    hubs = _Hubs()
    hubs.registryhub = _Bad()
    assert _auth_wedge_note_1202fr(hubs, ["fyp_feed_logged_out"]) == ""
