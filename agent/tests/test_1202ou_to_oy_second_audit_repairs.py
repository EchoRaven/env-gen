"""#1202ou-#1202oy — repairs from the second full-pipeline audit (delivery gate, seed, kickoff).

#1202ou  Two auth-tampering blockers reached the gate and were dispatched to NOBODY: neither
         prose matched a check token, so each became `deliverability_other:<first 80 chars>` —
         a name that embeds `custom_routes.py:<line>` and changes on every lane edit — and the
         dispatcher looks owners up by exact key. #1202s had been in that state since it
         shipped; #1202oj joined it. The latter is how tiktok-r126 got stuck (custom_routes.py
         made /api/video_saves and /api/user_settings public; the two failing chains failed on
         exactly those paths). Present in 8 of 12 runs that carry the guard.
#1202ov  `/.well-known/jwks.json` and `oauth-authorization-server` are framework OAuth discovery
         documents but classified as BUSINESS, so they were required and their validate tasks
         blocked delivery in 9 runs.
#1202ow  A fresh live row count has a 30-minute TTL; past it the seed audit fell back to the
         seed-REGISTRATION store, which no run writes, so a table measured non-empty flipped to
         `missing_seed` with nothing but time: 50 flips on an unchanged table count across 12 of
         22 runs, and 15 runs dispatched a backend P0 "Seed the empty business table" while live
         counts were non-empty. #956's rule (never measured -> flagged) is kept.
#1202ox  The gate's `business_chain_failing` detail named chains only: before r119, 0 of 700+
         records named any endpoint.
#1202oy  `normalize_steps` injects `framework_isolation_probe_<col>` as a hardcoded PUT without
         knowing the contract, and the unregistered-endpoint check then refused the verifier's
         chain for that injected step: 1,312 of 2,119 such rejections across 74 runs, still live.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.delivery_gate import (  # noqa: E402
    _deliverability_check_token, _first_broken_step_1202ox)
from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402
from multi_agent.runtime.lifecycle import is_business  # noqa: E402


def test_1202ou_both_auth_tampering_blockers_get_a_stable_routable_name():
    a = _deliverability_check_token(
        "framework auth guard tampered with: custom_routes.py:352 reassigns app.router.routes — x")
    b = _deliverability_check_token(
        "custom_routes.py reassigns the auth primitive `verify_user_password` (line 12). The ...")
    assert a == "deliverability_guard_tampering"
    assert b == "deliverability_auth_override"
    # the line number must not leak into the name — that is what made it unroutable
    assert _deliverability_check_token(
        "framework auth guard tampered with: custom_routes.py:999 names _FW_PUBLIC_API_1202KH"
    ) == a


def test_1202ou_the_dispatcher_owns_both():
    import inspect
    from multi_agent.runtime import remediation_dispatcher as RD
    src = inspect.getsource(RD.RemediationDispatcher.dispatch_gate_level_checks)
    table = src[src.index("_GATE_OWNER = {"):]
    for tok in ("deliverability_guard_tampering", "deliverability_auth_override"):
        entry = table[table.index('"%s": (' % tok):]
        entry = entry[entry.index("(") + 1:]                 # landmark, not a byte window
        assert entry.lstrip().startswith('"backend"'), tok


def test_1202ov_oauth_discovery_documents_are_framework_surface():
    assert is_business({"method": "GET", "path": "/.well-known/jwks.json"}) is False
    assert is_business({"method": "GET", "path": "/.well-known/oauth-authorization-server"}) is False
    assert is_business({"method": "GET", "path": "/api/videos"}) is True


def _seed_hub(tmp_path):
    hr = HubRegistry(tmp_path)
    hr.registryhub.register_table("videos", schema={"columns": [
        {"name": "id", "type": "integer"}, {"name": "caption", "type": "text"}]},
        agent="backend")
    return hr


def _capture(tmp_path, counts, age_s):
    import json as _json
    import time as _time
    f = tmp_path / "shared" / "seed_live_counts_1202dj.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(_json.dumps({"at": _time.time() - age_s, "counts": counts}))


def test_1202ow_a_table_this_run_counted_does_not_flip_to_missing_when_the_count_ages(tmp_path):
    from multi_agent.runtime.seed_audit import audit_seed_data
    hr = _seed_hub(tmp_path)
    _capture(tmp_path, {"videos": 39}, age_s=7200)        # counted, but past the 30-minute TTL
    report = audit_seed_data(hr, tmp_path)
    assert not any(f.get("table") == "videos" and f.get("reason") == "missing_seed"
                   for f in report.flagged_tables), report.flagged_tables


def test_1202ow_956_still_flags_a_table_never_measured(tmp_path):
    """#956's decision stands: never measured and not registered is flagged."""
    from multi_agent.runtime.seed_audit import audit_seed_data
    hr = _seed_hub(tmp_path)
    report = audit_seed_data(hr, tmp_path)                # no capture at all
    assert any(f.get("table") == "videos" and f.get("reason") == "missing_seed"
               for f in report.flagged_tables), report.flagged_tables


def test_1202ow_a_capture_that_counted_it_empty_does_not_excuse_it(tmp_path):
    from multi_agent.runtime.seed_audit import audit_seed_data
    hr = _seed_hub(tmp_path)
    _capture(tmp_path, {"videos": 0}, age_s=7200)
    report = audit_seed_data(hr, tmp_path)
    assert any(f.get("table") == "videos" for f in report.flagged_tables), report.flagged_tables


def test_1202ox_the_gate_detail_names_the_first_broken_step():
    """Through `business_chain_blockers`, the reader that writes the gate ledger."""
    import re as _re
    from multi_agent.runtime.delivery_gate import business_chain_blockers

    steps = [{"method": "GET", "path": "/api/videos", "expect": [200]}]

    class _RH:
        def get_endpoints(self):
            return {"e1": {"method": "GET", "path": "/api/videos"}}

        def get_verification_chains(self):
            return {"feed_flow": {"name": "feed_flow", "status": "failing", "steps": steps,
                                  "last_result": {"broken": [
                                      "GET /api/videos → 500 (expected [200]; boom)"],
                                                  "steps": steps}}}

        def endpoint_id(self, m, p):
            return f"{(m or 'GET').upper()} {_re.sub(r'[{][^}]+[}]', '{x}', p)}"

        def register_verification_chain(self, *a, **k):
            return None

        def update_verification_chain(self, *a, **k):
            return None

    out = business_chain_blockers(type("H", (), {"registryhub": _RH()})())
    assert out.get("reason") == "business_chain_failing", out
    assert "first broken step" in out["detail"] and "GET /api/videos" in out["detail"], out["detail"]
    assert _first_broken_step_1202ox([], ["other"]) == ""


def _hub_with(tmp_path, endpoints):
    hr = HubRegistry(tmp_path)
    rh = hr.registryhub
    for m, p in endpoints:
        rh.register_endpoint(m, p, agent="backend", status="implemented")
    return rh


_CHAIN = [
    {"method": "POST", "path": "/auth/register", "body": {"email": "a${rand}@x.io"},
     "save": {"token": "access_token"}, "expect": [200, 201]},
    {"method": "POST", "path": "/api/videos", "auth": "token", "body": {"caption": "c"},
     "save": {"vid": "item.id"}, "expect": [201]},
    {"method": "GET", "path": "/api/videos", "auth": "token", "expect": [200]},
]


def test_1202oy_a_chain_is_not_rejected_for_a_probe_the_framework_injected(tmp_path):
    rh = _hub_with(tmp_path, [("POST", "/auth/register"), ("POST", "/api/videos"),
                              ("GET", "/api/videos"), ("PATCH", "/api/videos/{video_id}")])
    res = rh.register_verification_chain("feed", steps=[dict(s) for s in _CHAIN],
                                         agent="verifier")
    assert "error" not in res, res.get("error")
    stored = rh.get_verification_chains()["feed"]["steps"]
    assert not any(str(s.get("action") or "").startswith("framework_isolation_probe")
                   for s in stored), stored


def test_1202oy_a_probe_whose_route_exists_is_kept(tmp_path):
    rh = _hub_with(tmp_path, [("POST", "/auth/register"), ("POST", "/api/videos"),
                              ("GET", "/api/videos"), ("PUT", "/api/videos/{video_id}")])
    res = rh.register_verification_chain("feed", steps=[dict(s) for s in _CHAIN],
                                         agent="verifier")
    assert "error" not in res, res.get("error")
    stored = rh.get_verification_chains()["feed"]["steps"]
    assert any(str(s.get("action") or "").startswith("framework_isolation_probe")
               for s in stored), stored


def test_1202oy_a_step_the_verifier_wrote_is_still_refused(tmp_path):
    rh = _hub_with(tmp_path, [("POST", "/auth/register"), ("POST", "/api/videos"),
                              ("GET", "/api/videos")])
    steps = [dict(s) for s in _CHAIN] + [{"method": "DELETE", "path": "/api/videos/${vid}",
                                          "auth": "token", "expect": [204]}]
    res = rh.register_verification_chain("feed", steps=steps, agent="verifier")
    assert "error" in res and "DELETE" in res["error"], res
