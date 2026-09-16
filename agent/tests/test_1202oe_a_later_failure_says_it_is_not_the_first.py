"""#1202oe: a failing step that follows an earlier failure says so, and names it.

Corpus: of 252 chain 404s, 94 (37%) have a failed step ahead of them in the SAME chain and say
nothing about it — the lane is handed `GET /api/v1/users/14 → 404` for a user the chain's own
earlier step never registered (tiktok-r76, follow_creator_relationship_effect). The note states
the fact and names the step; it asserts no causality (#1023: attach evidence, not a verdict).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime import chain_executor as CE  # noqa: E402


def _run(monkeypatch, responses, steps):
    calls = {"i": 0}

    def _http(method, url, **kw):
        i = calls["i"]
        calls["i"] += 1
        return responses[min(i, len(responses) - 1)]

    monkeypatch.setattr(CE, "_http", _http)
    return CE.execute_chain("http://127.0.0.1:1", {"name": "flow", "steps": steps})


def test_r76_the_second_failure_names_the_first(monkeypatch):
    out = _run(monkeypatch,
               [{"status": 500, "body_text": '{"detail":"register failed"}'},
                {"status": 404, "body_text": '{"detail":"user not found"}'}],
               [{"method": "POST", "path": "/auth/register", "expect": [200, 201]},
                {"method": "GET", "path": "/api/users/14", "expect": [200]}])
    assert len(out["broken"]) == 2
    first, second = out["broken"]
    assert "NOT THE FIRST FAILURE" not in first
    assert "NOT THE FIRST FAILURE" in second and "/auth/register" in second


def test_the_first_failure_is_reported_plainly(monkeypatch):
    out = _run(monkeypatch,
               [{"status": 200, "body_text": '{"item":{"id":1}}'},
                {"status": 404, "body_text": '{"detail":"not found"}'}],
               [{"method": "POST", "path": "/auth/register", "expect": [200, 201]},
                {"method": "GET", "path": "/api/users/14", "expect": [200]}])
    assert len(out["broken"]) == 1
    assert "NOT THE FIRST FAILURE" not in out["broken"][0]


def test_an_unreachable_step_also_counts_as_the_first_failure(monkeypatch):
    out = _run(monkeypatch,
               [{"status": None, "error": "ConnectionResetError: [Errno 104] Connection reset"},
                {"status": 404, "body_text": '{"detail":"not found"}'}],
               [{"method": "POST", "path": "/auth/register", "expect": [200, 201]},
                {"method": "GET", "path": "/api/users/14", "expect": [200]}])
    assert len(out["environment_1202od"]) == 1
    assert len(out["broken"]) == 1
    assert "NOT THE FIRST FAILURE" in out["broken"][0] and "/auth/register" in out["broken"][0]
