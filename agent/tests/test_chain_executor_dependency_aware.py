"""execute_chain: a single broken step must NOT abort the whole chain.

Before, the first 'broken' step `break`ed the loop, so the broken[] report only ever
showed the FIRST failure even when later, INDEPENDENT steps would also fail — the verifier
lane then fixed one bug, re-ran, hit the next, milestone after milestone. Now the chain
CONTINUES past a broken step and only SKIPS steps that depend on a variable the broken step
was supposed to save (those would cascade-fail on a missing var). This never converts a
failing chain to passing — the first broken step is always recorded first.

LOCAL-ONLY (agent/tests/ gitignored).
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from multi_agent.runtime import chain_executor as ce  # noqa: E402


def _mk_http(script):
    def _h(method, url, token=None, body=None, timeout=10, **_kw):
        path = "/" + url.split("://", 1)[-1].split("/", 1)[-1]
        for (m, suf), resp in script.items():
            if method.upper() == m and path.rstrip("/").endswith(suf.rstrip("/")):
                return resp
        return {"status": 200, "body_text": "{}", "error": None}
    return _h


def test_independent_broken_steps_are_all_reported(monkeypatch):
    chain = {"name": "c", "steps": [
        {"method": "GET", "path": "/api/a", "expect": [200]},   # ok
        {"method": "GET", "path": "/api/b", "expect": [200]},   # broken, independent
        {"method": "GET", "path": "/api/c", "expect": [200]},   # ok, independent
    ]}
    monkeypatch.setattr(ce, "_http", _mk_http({
        ("GET", "/api/a"): {"status": 200, "body_text": "{}", "error": None},
        ("GET", "/api/b"): {"status": 500, "body_text": "boom", "error": None},
        ("GET", "/api/c"): {"status": 200, "body_text": "{}", "error": None},
    }))
    res = ce.execute_chain("http://x:3001", chain)
    assert any("/api/b" in b for b in res["broken"])           # the broken step is reported
    c = next(s for s in res["steps"] if s["path"] == "/api/c")
    assert c["ok"] is True and c["kind"] == "ok"               # the independent later step still RAN


def test_dependent_step_is_skipped_not_run(monkeypatch):
    chain = {"name": "c", "steps": [
        {"method": "POST", "path": "/api/items", "expect": [201], "save": {"item_id": "id"}},  # broken producer
        {"method": "GET", "path": "/api/items/${item_id}", "expect": [200], "auth": "token"},  # depends → skip
    ]}
    monkeypatch.setattr(ce, "_http", _mk_http({
        ("POST", "/api/items"): {"status": 500, "body_text": "x", "error": None},
    }))
    res = ce.execute_chain("http://x:3001", chain)
    dep = next(s for s in res["steps"] if "item_id" in s["path"])
    assert dep["kind"] == "skipped"
    # a skipped (unreachable) step is NOT counted as a real broken failure
    assert not any("item_id" in b for b in res["broken"])


def test_clean_chain_unaffected(monkeypatch):
    chain = {"name": "c", "steps": [
        {"method": "GET", "path": "/api/a", "expect": [200]},
        {"method": "GET", "path": "/api/b", "expect": [200]},
    ]}
    monkeypatch.setattr(ce, "_http", _mk_http({}))  # default 200
    res = ce.execute_chain("http://x:3001", chain)
    assert res["broken"] == []
    assert all(s["kind"] == "ok" for s in res["steps"])


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
