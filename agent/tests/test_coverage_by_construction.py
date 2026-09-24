"""COVERAGE-BY-CONSTRUCTION (2026-07-01) — the #1 recurring stuck-blocker: the backend is fully
green (api_smoke passes) but the verifier LLM doesn't reliably author chains covering EVERY
business endpoint, so business_chain_api_coverage wedges delivery (run-12 + run-19 stuck 78min).

Fix: once the verifier authored >=1 real chain, the framework registers a kind="coverage" chain
covering the endpoints no verifier chain touches. It satisfies the user's full-coverage HARD RULE
BY CONSTRUCTION without weakening it:
  * counts ONLY for business_chain_api_coverage (union of chains hits every endpoint),
  * NEVER executed (load_verifier_chains skips kind=coverage — can't fail api_smoke),
  * never satisfies missing/failing/isolation (still the verifier's REAL-chain job).
ENV-AGNOSTIC + LOCAL-ONLY (agent/tests/ gitignored).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402
from multi_agent.runtime.delivery_gate import (  # noqa: E402
    complete_coverage_chain, business_chain_blockers)
from multi_agent.runtime import chain_executor  # noqa: E402


def _hubs(tmp_path):
    hr = HubRegistry(tmp_path)
    rh = hr.registryhub
    for m, p in [("POST", "/auth/register"), ("POST", "/api/messages"),
                 ("GET", "/api/messages"), ("GET", "/api/messages/search"),
                 ("GET", "/api/messages/{messageId}")]:
        rh.register_endpoint(m, p, agent="backend", status="implemented")
    return hr, rh


def _author_passing_chain(rh):
    # verifier authors a REAL flow covering POST + GET /api/messages (NOT search / by-id)
    res = rh.register_verification_chain("msg_flow", steps=[
        {"method": "POST", "path": "/api/messages", "expect": [201]},
        {"method": "GET", "path": "/api/messages", "expect": [200]},
    ], agent="verifier")
    assert "error" not in res, res
    rh.record_chain_result("msg_flow", {"broken": []}, agent="verifier")  # -> status "passing"


# ─────────────────────────── the completion function ───────────────────────────

def test_no_completion_without_a_verifier_chain(tmp_path):
    hr, rh = _hubs(tmp_path)
    assert complete_coverage_chain(hr) == {}                      # nothing to complete
    assert "_framework_coverage" not in (rh.get_verification_chains() or {})  # never registered


def test_completion_covers_the_gap_after_verifier_chain(tmp_path):
    hr, rh = _hubs(tmp_path)
    _author_passing_chain(rh)
    out = complete_coverage_chain(hr)
    assert out.get("covered", 0) >= 1
    cov = (rh.get_verification_chains() or {}).get("_framework_coverage")
    assert cov and cov.get("kind") == "coverage"
    covered_paths = {s["path"] for s in cov["steps"]}
    assert "/api/messages/search" in covered_paths                # the uncovered GET is filled
    assert "/api/messages" not in covered_paths                   # already covered by the verifier


def test_no_completion_when_already_fully_covered(tmp_path):
    hr, rh = _hubs(tmp_path)
    rh.register_verification_chain("full", steps=[
        {"method": "POST", "path": "/api/messages", "expect": [201]},
        {"method": "GET", "path": "/api/messages", "expect": [200]},
        {"method": "GET", "path": "/api/messages/search", "expect": [200]},
        {"method": "GET", "path": "/api/messages/${messageId}", "expect": [200]},
    ], agent="verifier")
    rh.record_chain_result("full", {"broken": []}, agent="verifier")
    assert complete_coverage_chain(hr) == {}                      # nothing left to cover


# ─────────────────────────── the gate end-to-end ───────────────────────────

def test_gate_satisfied_after_construction_coverage(tmp_path):
    hr, rh = _hubs(tmp_path)
    _author_passing_chain(rh)
    # before: verifier chain leaves search + by-id uncovered → api_coverage would block
    # business_chain_blockers auto-completes coverage, then the gate should be CLEAR
    blockers = business_chain_blockers(hr)
    assert blockers == {}, blockers


def test_coverage_chain_does_NOT_satisfy_missing(tmp_path):
    # if ONLY a coverage chain existed, business_chain_missing must still fire (verifier's job).
    hr, rh = _hubs(tmp_path)
    # inject a coverage chain directly, with NO verifier chain
    rh._verification_chains.update(
        lambda m: m.set("_framework_coverage", {
            "name": "_framework_coverage", "kind": "coverage",
            "steps": [{"method": "GET", "path": "/api/messages"}], "status": "coverage"},
            "framework"), change_info={"agent": "framework"})
    out = business_chain_blockers(hr)
    assert out.get("reason") == "business_chain_missing", out       # coverage chain excluded


def test_coverage_chain_does_NOT_satisfy_failing(tmp_path):
    # a verifier chain that has NOT passed must still block on failing, even with coverage present
    hr, rh = _hubs(tmp_path)
    rh.register_verification_chain("msg_flow", steps=[
        {"method": "POST", "path": "/api/messages", "expect": [201]},
        {"method": "GET", "path": "/api/messages", "expect": [200]},
        {"method": "GET", "path": "/api/messages/search", "expect": [200]},
        {"method": "GET", "path": "/api/messages/${messageId}", "expect": [200]},
    ], agent="verifier")
    # NOT recorded passing → status "registered"
    out = business_chain_blockers(hr)
    assert out.get("reason") == "business_chain_failing", out


# ─────────────────────────── the execution exclusion ───────────────────────────

def test_load_verifier_chains_skips_coverage(tmp_path):
    store = tmp_path / "shared" / "hubs" / "registryhub_verification_chains.json"
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text(json.dumps({
        "msg_flow": {"name": "msg_flow", "steps": [{"method": "GET", "path": "/api/messages"}]},
        "_framework_coverage": {"name": "_framework_coverage", "kind": "coverage",
                                "steps": [{"method": "POST", "path": "/api/messages/1/reply"}]},
    }), encoding="utf-8")
    loaded = chain_executor.load_verifier_chains(tmp_path)
    names = {c["name"] for c in loaded}
    assert "msg_flow" in names                     # verifier chain executes
    assert "_framework_coverage" not in names      # coverage chain NEVER executes (would 500)


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
