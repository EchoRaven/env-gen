"""#1176 — name the contract switch behind a 401 on a page that is public by construction.

r17 (live, 2026-08-30) held both halves of this answer for 20 minutes and ~$80 without
joining them: `validation:ui_smoke:landing_page` FAILED with "GET /api/titles/top10 401",
`registryhub_endpoints` carried `metadata.auth_required=True` for that endpoint, and
App.jsx declared `<Route path="/" element={<LandingPage />} />` with no guard. The backend
lane re-registered the endpoint again and again, re-sending `status=implemented` and never
touching the flag, because the remediation named the symptom and no cause.

The second test is the one that matters most: a GUARDED route must stay silent. The
diagnosis says "consider making this endpoint public", and offering that about a page that
is supposed to be authenticated and merely failed to log in would repair a red gate by
deleting an auth boundary — #1158's fail-open, dressed as remediation.
"""
import json
from pathlib import Path

from env_generator.llm_generator.multi_agent.runtime.remediation_dispatcher import (
    auth_contradiction_1176, _route_is_public_1176,
)


class _Orch:
    def __init__(self, root):
        self.output_dir = str(root)


def _project(tmp_path, *, auth_required, app_jsx):
    hubs = tmp_path / "shared" / "hubs"
    hubs.mkdir(parents=True)
    (hubs / "codehub_checks.json").write_text(json.dumps({"checks": [{
        "name": "validation:ui_smoke:landing_page", "status": "failure",
        "evidence": {"summary": "Landing page loaded but emitted GET /api/titles/top10 "
                                "401 Unauthorized network/console error."}}]}))
    ep = {"method": "GET", "path": "/api/titles/top10", "metadata": {"response_key": "items"}}
    if auth_required is not None:
        ep["metadata"]["auth_required"] = auth_required
    (hubs / "registryhub_endpoints.json").write_text(json.dumps({"endpoints": [ep]}))
    (hubs / "registryhub_ui_pages.json").write_text(json.dumps(
        {"pages": [{"name": "landing_page", "route": "/"}]}))
    src = tmp_path / "app" / "frontend" / "src"
    src.mkdir(parents=True)
    (src / "App.jsx").write_text(app_jsx)
    return _Orch(tmp_path)


_PUBLIC_APP = ('<Routes>\n'
               '  <Route path="/" element={<LandingPage />} />\n'
               '  <Route path="/browse" element={<ProtectedRoute><BrowsePage /></ProtectedRoute>} />\n'
               '</Routes>')


def test_public_route_plus_authed_contract_names_the_switch(tmp_path):
    out = auth_contradiction_1176(_project(tmp_path, auth_required=True, app_jsx=_PUBLIC_APP),
                                  ["landing_page"])
    assert out, "the contradiction r17 could not see must be stated"
    assert "GET /api/titles/top10" in out and "auth_required=True" in out
    # Both legal repairs, and the reason the obvious one (edit main.py) is not among them.
    assert "auth_required=False" in out              # (a) publish the endpoint
    assert "auth guard" in out                       # (b) protect the page
    assert "main.py CANNOT fix this" in out
    # r17's actual dead end, named so the lane does not repeat it.
    assert "re-registering the endpoint with the same metadata changes nothing" in out


def test_guarded_route_stays_silent_no_fail_open_advice(tmp_path):
    """A page behind a guard that 401s is a LOGIN defect; publishing its data is not a fix."""
    guarded = ('<Routes>\n'
               '  <Route path="/" element={<RequireAuth><LandingPage /></RequireAuth>} />\n'
               '</Routes>')
    assert auth_contradiction_1176(
        _project(tmp_path, auth_required=True, app_jsx=guarded), ["landing_page"]) == ""


def test_contract_that_does_not_demand_a_token_is_not_blamed(tmp_path):
    for stated in (False, None):
        assert auth_contradiction_1176(
            _project(tmp_path / str(stated), auth_required=stated, app_jsx=_PUBLIC_APP),
            ["landing_page"]) == "", f"auth_required={stated} does not force the 401"


def test_guard_is_found_past_any_fixed_window(tmp_path):
    """#943's rule, applied to production: the span ends at the NEXT route landmark.

    A guarded `<Route>` carrying a lazy import and a long prop list runs well past any
    constant byte window, and a window that stops early reads as 'no guard' — precisely
    the direction that yields the fail-open advice.
    """
    padded = ('<Routes>\n'
              '  <Route path="/" element={<Suspense fallback={<Spinner label="'
              + "loading the catalogue shell " * 60 + '" />}><PrivateRoute>'
              '<LandingPage /></PrivateRoute></Suspense>} />\n'
              '  <Route path="/login" element={<LoginPage />} />\n'
              '</Routes>')
    _decl = padded.index('<Route path="/"')
    assert padded.index("PrivateRoute") - _decl > 1500, "guard must sit past a naive window"
    assert _route_is_public_1176(padded, "/") is False


def test_unknown_route_says_nothing(tmp_path):
    assert _route_is_public_1176(_PUBLIC_APP, "/not-declared") is None
