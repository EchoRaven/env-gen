"""wait_backend_ready: bounded backend-readiness wait for the final delivery gate
(outlook run-28 rc=1 + run-31 FAILED, 2026-07-02).

The post-loop hard gate probes LIVE state (sql_tables introspection, business-chain runs)
while the compose stack restarts between milestones — a mid-restart evaluation saw
sql_tables=4-of-11 / failing chains on a HEALTHY app and killed otherwise-delivered runs.
The orchestrator now waits (bounded) for the backend to serve and re-evaluates ONCE before
raising. ENV-AGNOSTIC + LOCAL-ONLY (agent/tests/ gitignored).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime import validation_runner as vr  # noqa: E402

_COMPOSE = """services:
  backend:
    ports:
      - "3999:8082"
"""


def _proj(tmp_path):
    d = tmp_path / "docker"
    d.mkdir()
    (d / "docker-compose.yml").write_text(_COMPOSE, encoding="utf-8")
    return tmp_path


def test_ready_backend_returns_true(tmp_path, monkeypatch):
    monkeypatch.setattr(vr, "_backend_host_port", lambda c, cwd: 3999)
    monkeypatch.setattr(vr, "_http", lambda *a, **k: {"status": 200, "body_text": "", "error": None})
    assert vr.wait_backend_ready(_proj(tmp_path), timeout_s=5, gap_s=0.01) is True


def test_backend_coming_up_mid_wait(tmp_path, monkeypatch):
    calls = {"n": 0}
    def fake_http(*a, **k):
        calls["n"] += 1
        if calls["n"] < 3:
            return {"status": None, "body_text": "", "error": "ConnectionRefused"}
        return {"status": 200, "body_text": "", "error": None}
    monkeypatch.setattr(vr, "_backend_host_port", lambda c, cwd: 3999)
    monkeypatch.setattr(vr, "_http", fake_http)
    assert vr.wait_backend_ready(_proj(tmp_path), timeout_s=5, gap_s=0.01) is True
    assert calls["n"] >= 3


def test_never_ready_returns_false_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(vr, "_backend_host_port", lambda c, cwd: 3999)
    monkeypatch.setattr(vr, "_http", lambda *a, **k: {"status": None, "body_text": "", "error": "refused"})
    assert vr.wait_backend_ready(_proj(tmp_path), timeout_s=1, gap_s=0.05) is False


def test_missing_compose_is_bounded_false(tmp_path):
    assert vr.wait_backend_ready(tmp_path, timeout_s=1, gap_s=0.05) is False


def test_5xx_not_ready(tmp_path, monkeypatch):
    monkeypatch.setattr(vr, "_backend_host_port", lambda c, cwd: 3999)
    monkeypatch.setattr(vr, "_http", lambda *a, **k: {"status": 502, "body_text": "", "error": None})
    assert vr.wait_backend_ready(_proj(tmp_path), timeout_s=1, gap_s=0.05) is False


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
