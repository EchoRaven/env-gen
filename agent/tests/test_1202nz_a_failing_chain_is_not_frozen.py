"""#1202nz: freeze-on-green keeps a PASSING chain, not a failing one, and says when it refuses.

tiktok-r126 ab2: business_chain went green ~15:43 and froze every chain. At 15:48:31 the backend
made `GET /api/video_saves` public (schema.auth_required=False) — the endpoint SET did not change,
so the freeze held — and chain `video_saves_page`'s anonymous-denial step went red. The verifier
re-registered it with the corrected expectation at 15:44:41 and 15:52:20 (plus replacement names);
each came back `{registered, steps: 0, status: None}` as a SUCCESS, the stale chain kept running,
and the run died at 15:53:06 on NO-CONVERGENCE with that chain as its only failure. The verifier
said: "a framework/chain registry stale-state limitation from verifier surface".
Corpus: 1384 of those silent results in the verifier logs of 96 of 165 runs.
"""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402

_DENY = [{"method": "POST", "path": "/api/video_saves", "expect": [201], "auth": "token"},
         {"method": "GET", "path": "/api/video_saves", "expect": [401, 403]}]
_FIXED = [{"method": "POST", "path": "/api/video_saves", "expect": [201], "auth": "token"},
          {"method": "GET", "path": "/api/video_saves", "expect": [200]}]


def _rh(tmp_path):
    hr = HubRegistry(tmp_path)
    rh = hr.registryhub
    for m, p in [("POST", "/auth/register"), ("POST", "/api/video_saves"),
                 ("GET", "/api/video_saves")]:
        rh.register_endpoint(m, p, agent="backend", status="implemented")
    return hr, rh


def _expects(rh, name):
    return [s.get("expect") for s in rh.get_verification_chains()[name]["steps"]
            if s.get("method") == "GET" and s.get("path") == "/api/video_saves"]


def test_r126_a_chain_that_went_red_under_the_freeze_can_be_corrected(tmp_path):
    hr, rh = _rh(tmp_path)
    assert "error" not in rh.register_verification_chain("video_saves_page", list(_DENY),
                                                         agent="verifier")
    rh.record_chain_result("video_saves_page", {"broken": []}, agent="framework")
    rh._chains_frozen_eps = set(rh.get_endpoints().keys())           # green -> frozen
    rh.record_chain_result("video_saves_page",
                           {"broken": ["GET /api/video_saves -> 200 (expected [401, 403])"]},
                           agent="framework")                          # contract moved -> red
    res = rh.register_verification_chain("video_saves_page", list(_FIXED), agent="verifier")
    assert not res.get("frozen") and "error" not in res, res
    assert _expects(rh, "video_saves_page") == [[200]]


def test_a_passing_chain_stays_frozen(tmp_path):
    hr, rh = _rh(tmp_path)
    rh.register_verification_chain("video_saves_page", list(_FIXED), agent="verifier")
    rh.record_chain_result("video_saves_page", {"broken": []}, agent="framework")
    rh._chains_frozen_eps = set(rh.get_endpoints().keys())
    res = rh.register_verification_chain("video_saves_page", list(_DENY), agent="verifier")
    assert res.get("frozen") is True
    assert _expects(rh, "video_saves_page") == [[200]]


def test_the_tool_says_a_frozen_chain_was_not_registered(tmp_path):
    from tools.hub_tools import RegistryHubRegisterVerificationChainTool as T
    hr, rh = _rh(tmp_path)
    rh.register_verification_chain("video_saves_page", list(_FIXED), agent="verifier")
    rh.record_chain_result("video_saves_page", {"broken": []}, agent="framework")
    rh._chains_frozen_eps = set(rh.get_endpoints().keys())
    tool = T.__new__(T)
    tool._hubs = hr
    tool._agent_id = "verifier"
    out = asyncio.run(tool._run("video_saves_page", list(_DENY)))
    assert out.success is False
    assert "NOT registered" in out.error_message and "FROZEN" in out.error_message
