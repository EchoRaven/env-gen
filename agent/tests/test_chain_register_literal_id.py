"""FIX #137 — chain registration matches a LITERAL numeric id segment against the
registered {id} template endpoint.

instagram run-61 (also run-52), live: the verifier's remediation REWRITE bound real
seed ids into by-id steps (GET /api/posts/1, POST /api/posts/1/like) and RegistryHub
REJECTED the whole chain ("endpoints NOT registered: GET /api/posts/1") because
_chain_eid only collapsed ${var} segments — a literal digit segment never matched the
registered /api/posts/{id} template. That locked the verifier out of its own fix path
and left the stale failing chain to 404 forever.

ENV-AGNOSTIC + LOCAL-ONLY (agent/tests/ gitignored).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402


def _rh(tmp_path):
    hr = HubRegistry(tmp_path)
    rh = hr.registryhub
    for m, p in [("POST", "/auth/register"), ("GET", "/api/posts"),
                 ("GET", "/api/posts/{id}"), ("POST", "/api/posts/{id}/like")]:
        rh.register_endpoint(m, p, agent="backend", status="implemented")
    return rh


def test_literal_numeric_id_matches_template(tmp_path):
    rh = _rh(tmp_path)
    res = rh.register_verification_chain("real_ids", steps=[
        {"method": "POST", "path": "/auth/register",
         "body": {"email": "a-${rand}@x.io", "password": "P4ss!word"},
         "expect": [200, 201], "save": {"token": "access_token"}},
        {"method": "GET", "path": "/api/posts/1", "auth": "token", "expect": [200]},
        {"method": "POST", "path": "/api/posts/1/like", "auth": "token",
         "expect": [200, 201]},
    ], agent="verifier")
    assert not res.get("error"), res


def test_placeholder_paths_still_match(tmp_path):
    rh = _rh(tmp_path)
    res = rh.register_verification_chain("var_ids", steps=[
        {"method": "GET", "path": "/api/posts/${post_id}", "expect": [200]},
    ], agent="verifier")
    assert not res.get("error"), res


def test_truly_unregistered_endpoint_still_rejected(tmp_path):
    rh = _rh(tmp_path)
    res = rh.register_verification_chain("phantom", steps=[
        {"method": "DELETE", "path": "/api/ghosts/1", "expect": [200]},
    ], agent="verifier")
    assert res.get("error") and "NOT registered" in res["error"], res


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
