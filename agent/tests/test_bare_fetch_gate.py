"""FIX #154 (§6-1) — bare unauthenticated fetch() to an authed /api/ endpoint (gmrun4).

gmrun4 delivered all 4 milestones with the backend + real dataset fully wired, yet the
browser showed a login wall: SearchResultsList.jsx:13 called
``fetch(`/api/places/search?q=${query}`)`` with NO Authorization token (and the lane's own
services/api.js was equally bare) → every /api/ request 401'd → empty pages. api_smoke
probes endpoints with a FRAMEWORK-minted token, so it can never see a frontend token-wiring
gap; #151's ``_has_real_api_call`` counts any ``fetch(`` as a real call without checking
auth. This gate statically flags a bare ``fetch('/api/...')`` whose call site carries no
auth evidence, BEFORE the browser gate has to catch the 401 at runtime.

Must NOT flag (danger list, HANDOFF §6-1): public endpoints (/auth/*, login/register,
the framework /api/v1/* control plane e.g. TenantPicker's pre-auth tenants call), calls
that DO attach auth (Authorization header, authHeaders() spread, token interpolation),
variable-URL fetches (the baseline api.js ``fetch(path, ...)`` wrapper), calls whose
options object is an opaque identifier, and api-client-mediated calls (api.get(...)).
LOCAL-ONLY (agent/tests/ is gitignored).
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import pytest  # noqa: E402

from multi_agent.runtime.frontend_audit import bare_authed_fetch_blockers  # noqa: E402

ANCHOR = "bare unauthenticated fetch"

# ---- verbatim shapes from the gmrun4 archive (the class this gate exists for) ----

RUN4_SEARCH_RESULTS_LIST = """import React, { useState, useEffect } from 'react';
import SearchResultCard from './SearchResultCard';

function SearchResultsList({ query }) {
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const fetchResults = async () => {
      if (!query) return;
      setLoading(true);
      try {
        const response = await fetch(`/api/places/search?q=${query}`);
        const data = await response.json();
        setResults(data.items || []);
      } catch (error) {
        console.error('Failed to search places:', error);
      } finally {
        setLoading(false);
      }
    };
    fetchResults();
  }, [query]);
  return <div>{results.map(r => <SearchResultCard key={r.id} place={r} />)}</div>;
}
export default SearchResultsList;
"""

RUN4_SEARCH_BAR_CONCAT = """import React from 'react';
export default function SearchBar({ query }) {
  const go = async () => {
    const response = await fetch('/api/places/autocomplete?q=' + query);
    return response.json();
  };
  return <input onChange={go} />;
}
"""

RUN4_LANE_API_SERVICE = """export const api = {
  async searchPlaces(query) {
    if (!query) return { items: [] };
    const response = await fetch('/api/places/search?q=' + encodeURIComponent(query));
    if (!response.ok) throw new Error('Failed to search places');
    const data = await response.json();
    return data.items || [];
  },
};
"""

MULTILINE_POST_NO_AUTH = """export async function addReview(placeId, body) {
  const r = await fetch('/api/reviews', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ place_id: placeId, body }),
  });
  return r.json();
}
export default function ReviewForm() { return <form onSubmit={addReview} />; }
"""


def _fe(tmp_path, files):
    fe = tmp_path / "app" / "frontend" / "src"
    for rel, txt in files.items():
        p = fe / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(txt)
    return fe


# ------------------------------ must flag ------------------------------

def test_run4_template_literal_bare_fetch_flagged(tmp_path):
    fe = _fe(tmp_path, {"components/SearchResultsList.jsx": RUN4_SEARCH_RESULTS_LIST})
    blockers = bare_authed_fetch_blockers(fe)
    assert len(blockers) == 1, blockers
    b = blockers[0]
    assert ANCHOR in b.lower()
    assert "components/SearchResultsList.jsx" in b
    assert "/api/places/search" in b


def test_string_concat_bare_fetch_flagged(tmp_path):
    fe = _fe(tmp_path, {"components/SearchBar.jsx": RUN4_SEARCH_BAR_CONCAT})
    blockers = bare_authed_fetch_blockers(fe)
    assert len(blockers) == 1, blockers
    assert "/api/places/autocomplete" in blockers[0]


def test_lane_authored_service_without_auth_flagged(tmp_path):
    # gmrun4's OWN services/api.js was bare too — the service layer is not exempt,
    # only a service that actually attaches auth is.
    fe = _fe(tmp_path, {"services/api.js": RUN4_LANE_API_SERVICE})
    blockers = bare_authed_fetch_blockers(fe)
    assert len(blockers) == 1, blockers
    assert "services/api.js" in blockers[0]


def test_multiline_post_content_type_only_flagged(tmp_path):
    # a headers object with only Content-Type still 401s — Content-Type is not auth.
    fe = _fe(tmp_path, {"components/ReviewForm.jsx": MULTILINE_POST_NO_AUTH})
    blockers = bare_authed_fetch_blockers(fe)
    assert len(blockers) == 1, blockers
    assert "/api/reviews" in blockers[0]


def test_interpolated_base_prefix_still_flagged(tmp_path):
    # `${API_BASE}/api/places/1` reaches the same authed backend — the static text
    # of the template names an /api/ path, so it flags like a plain literal.
    src = ("const API_BASE = '';\n"
           "export async function load(id) {\n"
           "  const r = await fetch(`${API_BASE}/api/places/${id}`);\n"
           "  return r.json();\n}\n")
    fe = _fe(tmp_path, {"services/places.js": src})
    blockers = bare_authed_fetch_blockers(fe)
    assert len(blockers) == 1, blockers


def test_reports_file_and_line(tmp_path):
    fe = _fe(tmp_path, {"components/SearchResultsList.jsx": RUN4_SEARCH_RESULTS_LIST})
    b = bare_authed_fetch_blockers(fe)[0]
    # the bare fetch sits on line 13 of the verbatim run-4 component
    assert "SearchResultsList.jsx:13" in b, b


# ---------------------------- must NOT flag ----------------------------

def test_api_client_mediated_call_not_flagged(tmp_path):
    src = ("import api from '../services/api';\n"
           "export default function Page(){\n"
           "  useEffect(() => { api.get('/api/places/search?q=x').then(setR); }, []);\n"
           "  return <div/>;\n}\n")
    fe = _fe(tmp_path, {"pages/SearchPage.jsx": src})
    assert bare_authed_fetch_blockers(fe) == []


def test_public_endpoints_not_flagged(tmp_path):
    src = ("export async function boot() {\n"
           "  await fetch('/auth/login', { method: 'POST' });\n"
           "  await fetch('/api/auth/register', { method: 'POST' });\n"
           "  await fetch('/api/v1/tenants');\n"  # framework control plane, pre-auth
           "  await fetch('/health');\n"
           "}\n")
    fe = _fe(tmp_path, {"services/boot.js": src})
    assert bare_authed_fetch_blockers(fe) == []


def test_authorization_header_at_call_site_not_flagged(tmp_path):
    src = ("export async function load(token) {\n"
           "  const r = await fetch('/api/places/1', {\n"
           "    headers: { Authorization: `Bearer ${token}` },\n"
           "  });\n"
           "  return r.json();\n}\n")
    fe = _fe(tmp_path, {"services/places.js": src})
    assert bare_authed_fetch_blockers(fe) == []


def test_auth_helper_spread_not_flagged(tmp_path):
    src = ("import { authHeaders } from './auth';\n"
           "export async function load() {\n"
           "  const r = await fetch('/api/places/1', { headers: { ...authHeaders() } });\n"
           "  return r.json();\n}\n")
    fe = _fe(tmp_path, {"services/places.js": src})
    assert bare_authed_fetch_blockers(fe) == []


def test_inline_token_interpolation_not_flagged(tmp_path):
    src = ("export async function load() {\n"
           "  const t = localStorage.getItem('token');\n"
           "  const r = await fetch('/api/places/1', { headers: { 'X-Auth': t } });\n"
           "  return r.json();\n}\n")
    fe = _fe(tmp_path, {"services/places.js": src})
    assert bare_authed_fetch_blockers(fe) == []


def test_variable_url_not_flagged(tmp_path):
    # the baseline wrapper style: fetch(path, {...}) — URL is a variable, the wrapper
    # attaches authHeaders(); flagging it would self-flag the framework scaffold.
    src = ("async function request(path, { method = 'GET', body } = {}) {\n"
           "  const r = await fetch(path, { method });\n"
           "  return r.json();\n}\n"
           "export const get = (path) => request(path);\n")
    fe = _fe(tmp_path, {"services/api.js": src})
    assert bare_authed_fetch_blockers(fe) == []


def test_opaque_options_identifier_not_flagged(tmp_path):
    # fetch('/api/x', opts) — the options are built elsewhere and may carry auth;
    # precision-first: skip what we cannot see.
    src = ("export async function load(opts) {\n"
           "  const r = await fetch('/api/places/1', opts);\n"
           "  return r.json();\n}\n")
    fe = _fe(tmp_path, {"services/places.js": src})
    assert bare_authed_fetch_blockers(fe) == []


def test_framework_baseline_api_js_not_flagged(tmp_path):
    from multi_agent.runtime.frontend_scaffold import _BASELINE_API_JS
    fe = _fe(tmp_path, {"services/api.js": _BASELINE_API_JS})
    assert bare_authed_fetch_blockers(fe) == []


def test_missing_src_dir_returns_empty(tmp_path):
    assert bare_authed_fetch_blockers(tmp_path / "nope" / "src") == []


# ------------------------- delivery-gate mapping -------------------------

def test_blocker_maps_to_bare_fetch_check():
    from multi_agent.runtime.delivery_gate import _deliverability_check_token
    b = ("frontend calls an authed API via bare unauthenticated fetch(): "
         "app/frontend/src/components/SearchResultsList.jsx:13 ...")
    assert _deliverability_check_token(b) == "deliverability_bare_authed_fetch"


def test_existing_mappings_preserved():
    from multi_agent.runtime.delivery_gate import _deliverability_check_token
    assert (_deliverability_check_token("ui_page `x` declared but unusable: route ...")
            == "deliverability_ui_page_unwired")
    assert (_deliverability_check_token("no successful RunHub run since session start")
            == "deliverability_no_successful_run")
    assert _deliverability_check_token("something novel").startswith("deliverability_other:")


# ----------------------- deliverability integration -----------------------

def _registry(tmp_path):
    from multi_agent.runtime.hub_registry import HubRegistry
    return HubRegistry(tmp_path)


def test_deliverability_blockers_include_bare_fetch(tmp_path):
    from multi_agent.runtime.deliverability import compute_deliverability
    reg = _registry(tmp_path)
    app_root = tmp_path / "app"
    _fe(tmp_path, {"components/SearchResultsList.jsx": RUN4_SEARCH_RESULTS_LIST})
    report = compute_deliverability(reg, app_root, session_start_ts=0.0)
    assert any(ANCHOR in b.lower() for b in report.blockers), report.blockers


def test_deliverability_bare_fetch_kill_switch(tmp_path, monkeypatch):
    from multi_agent.runtime.deliverability import compute_deliverability
    monkeypatch.setenv("ENVGEN_BARE_FETCH_GATE", "0")
    reg = _registry(tmp_path)
    app_root = tmp_path / "app"
    _fe(tmp_path, {"components/SearchResultsList.jsx": RUN4_SEARCH_RESULTS_LIST})
    report = compute_deliverability(reg, app_root, session_start_ts=0.0)
    assert not any(ANCHOR in b.lower() for b in report.blockers), report.blockers


# --------------------------- dispatcher routing ---------------------------

def test_bare_fetch_check_routes_to_frontend_with_offenders(tmp_path):
    import asyncio
    import logging
    import types
    from multi_agent.runtime.remediation_dispatcher import RemediationDispatcher

    class _FakeWorkHub:
        def __init__(self):
            self.tasks = []

        def create_task(self, **kw):
            self.tasks.append(kw)
            return {"id": f"task_{len(self.tasks)}"}

    class _FakeBus:
        def __init__(self):
            self.sent = []

        async def send(self, msg):
            self.sent.append(msg)

    _fe(tmp_path, {"components/SearchResultsList.jsx": RUN4_SEARCH_RESULTS_LIST})
    orch = types.SimpleNamespace(
        hubs=types.SimpleNamespace(workhub=_FakeWorkHub()),
        message_bus=_FakeBus(),
        _logger=logging.getLogger("test_bare_fetch_gate"),
        _current_milestone_version="1.0.0",
        output_dir=tmp_path,
    )
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        loop.run_until_complete(RemediationDispatcher(orch).dispatch_gate_level_checks(
            ["deliverability_bare_authed_fetch"]))
    finally:
        asyncio.set_event_loop(None)
        loop.close()
    assert len(orch.hubs.workhub.tasks) == 1
    t = orch.hubs.workhub.tasks[0]
    assert t["assignee"] == "frontend" and t["priority"] == "P0"
    # the exact offender (file:line) must reach the lane — imprecise diagnosis is
    # why gmrun4's lane missed 7 repair attempts.
    assert "SearchResultsList.jsx:13" in t["description"], t["description"]
    assert orch.message_bus.sent


# ------------------------- real-archive empiricism -------------------------

_GM4 = (ROOT.parent / "generated" /
        "googlemaps-core-di.SUCCESS-gmrun4-4milestones" / "app" / "frontend" / "src")
_GM3 = (ROOT.parent / "generated" /
        "googlemaps-core-di.SUCCESS-gmrun3-3milestones-realdata" / "app" / "frontend" / "src")


@pytest.mark.skipif(not _GM4.is_dir(), reason="gmrun4 archive not on this host")
def test_gmrun4_archive_real_offenders_flagged():
    blockers = bare_authed_fetch_blockers(_GM4)
    joined = "\n".join(blockers)
    # the run-4 death: the component AND the lane's own bare service
    assert "components/SearchResultsList.jsx:13" in joined, joined
    assert "components/SearchBar.jsx" in joined, joined
    assert "services/api.js" in joined, joined
    # public calls stay clean: LoginPage posts /auth/login; TenantPicker reads /api/v1/tenants
    assert "components/LoginPage.jsx" not in joined, joined
    assert "TenantPicker.jsx" not in joined, joined


@pytest.mark.skipif(not _GM3.is_dir(), reason="gmrun3 archive not on this host")
def test_gmrun3_archive_yields_no_false_positives():
    # gmrun3's failure was a mock twin (#151/#153 territory) — every fetch( in its src is
    # a skip-case (variable URL wrappers, /api/v1 tenants, auth'd service): zero blockers.
    assert bare_authed_fetch_blockers(_GM3) == []


def test_helper_indirection_headers_not_flagged(tmp_path):
    """#233 (r23 FALSE-BLOCK, 83min abort): the lane's api.js attached auth via
    `{ headers: getHeaders() }` — a helper whose body adds the Bearer token —
    but the gate only recognized literal evidence or a bare options identifier,
    flagged all 11 correct call sites, and the run died on an unwinnable gate.
    A non-literal headers value (call or identifier) is opaque — never flag."""
    from multi_agent.runtime.frontend_audit import bare_authed_fetch_blockers
    src = tmp_path / "src"
    (src / "services").mkdir(parents=True)
    (src / "services" / "api.js").write_text(
        "const getHeaders = () => ({ 'Authorization': 'Bearer x' });\n"
        "export const getFeed = async () => {\n"
        "  const res = await fetch(`${baseUrl}/api/feed`, { headers: getHeaders() });\n"
        "  return res.json();\n"
        "};\n"
        "export const getLive = async () => {\n"
        "  const res = await fetch('/api/live', { ...getHeaders(), method: 'GET' });\n"
        "  return res.json();\n"
        "};\n", encoding="utf-8")
    assert bare_authed_fetch_blockers(src) == []


def test_truly_bare_fetch_still_flagged(tmp_path):
    from multi_agent.runtime.frontend_audit import bare_authed_fetch_blockers
    src = tmp_path / "src"
    src.mkdir(parents=True)
    (src / "Feed.jsx").write_text(
        "export default function F(){ return fetch('/api/feed').then(r=>r.json()); }\n",
        encoding="utf-8")
    bl = bare_authed_fetch_blockers(src)
    assert bl and "/api/feed" in bl[0]
