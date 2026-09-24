"""FIX #231 (r21 split-brain autopsy) — deprecated endpoints must not count as
"registered" for frontend-side consumers, and consolidation must cascade.

r21: the contract carried BOTH GET /api/feed (later deprecated) and
GET /api/v1/feed. Because every frontend-side consumer treated the deprecated
record as registered, (a) the audit's contract-miss never fired, (b) the heal
reconciler early-exited on the dead path, and (c) the stale ui_page
declaration steered the lane back onto /api/feed 29s after the backend
dropped it → authed 404 → "No videos found in feed" in the DELIVERED app.
LOCAL-ONLY (agent/tests/ gitignored).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


class _Hub:
    def __init__(self, eps):
        self._eps = eps

    def get_endpoints(self):
        return self._eps


_EPS = {
    "ep_feed_old": {"method": "GET", "path": "/api/feed", "status": "deprecated"},
    "ep_feed_v1": {"method": "GET", "path": "/api/v1/feed", "status": "implemented"},
    "ep_videos": {"method": "GET", "path": "/api/videos", "status": "implemented"},
}


def test_registered_paths_excludes_deprecated():
    from multi_agent.runtime.frontend_audit import _registered_paths
    reg = _registered_paths(_Hub(_EPS))
    assert ("GET", "/api/v1/feed") in reg
    assert ("GET", "/api/feed") not in reg


def test_contract_miss_fires_for_deprecated_only_path():
    from multi_agent.runtime.frontend_audit import _registered_paths, _api_registered
    reg = _registered_paths(_Hub(_EPS))
    assert not _api_registered("GET /api/feed", reg)
    assert _api_registered("GET /api/v1/feed", reg)


def test_reconcile_rewrites_version_variant_call(tmp_path):
    """A called path that is unregistered but shares its version-stripped key
    with exactly ONE registered path gets rewritten (both directions)."""
    from multi_agent.runtime.frontend_scaffold import reconcile_frontend_api_paths
    src = tmp_path / "src"
    src.mkdir(parents=True)
    (src / "Feed.jsx").write_text(
        "export default function F(){ return fetch('/api/feed').then(r=>r.json()); }\n",
        encoding="utf-8")
    registered = {"/api/v1/feed", "/api/videos"}
    reconcile_frontend_api_paths(tmp_path, registered)
    out = (src / "Feed.jsx").read_text(encoding="utf-8")
    assert "'/api/v1/feed'" in out
    assert "'/api/feed'" not in out


def test_deprecate_endpoint_cascades_metadata_and_ui_pages(tmp_path):
    """registryhub.deprecate_endpoint must carry auth_required/response_key to
    the replacement when absent and rewrite ui_pages.apis_used off the dead
    path — the stale declaration is what steered the r21 lane onto the 404."""
    from multi_agent.runtime.registryhub import RegistryHub
    hub = RegistryHub(tmp_path / "hubs")
    a = hub.register_endpoint("GET", "/api/feed", agent="backend",
                              auth_required=False, response_key="items")
    b = hub.register_endpoint("GET", "/api/v1/feed", agent="backend")
    hub.register_ui_page("for_you_feed", route="/", component="FeedPage",
                         apis_used=["GET /api/feed"], agent="orchestrator")
    hub.deprecate_endpoint(a["id"], replacement_id=b["id"], agent="backend")
    eps = hub.get_endpoints()
    rep = eps[b["id"]]
    meta = rep.get("metadata") or {}
    assert (rep.get("auth_required") is False
            or meta.get("auth_required") is False)
    page = (hub.list_ui_pages() or {}).get("for_you_feed") or {}
    assert page.get("apis_used") == ["GET /api/v1/feed"]


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
