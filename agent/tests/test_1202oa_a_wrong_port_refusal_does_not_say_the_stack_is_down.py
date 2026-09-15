"""#1202oa: a refusal at a port this run does not publish must not tell the lane to bring the stack up.

tiktok-r126 ab2: the backend lane probed `localhost:8082` — the backend's CONTAINER port, published
as 8005 — and each result carried two opposite sentences: #677 "The service is not running, so
retrying this call cannot succeed. Bring the stack up (docker compose)…" and #1202lv "nothing is
listening on :8082 and nothing was going to be … this is not evidence the service is down". It
retried five times in 22 minutes.
"""
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from tools import runtime_tools as RT  # noqa: E402


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def test_r126_a_container_port_refusal_drops_the_bring_the_stack_up_remedy(monkeypatch):
    published, container = _free_port(), _free_port()
    monkeypatch.setenv(RT._RUN_PORTS_ENV_1134, str(published))
    out = RT.TestAPITool().execute("GET", f"http://localhost:{container}/api/videos")
    assert out.success is False
    assert f"NOTHING IS LISTENING at localhost:{container}" in out.error_message
    assert "Bring the stack up" not in out.error_message
    assert "not one this run publishes" in out.error_message
    assert any("#1134 WRONG TARGET" in n for n in out.notices)


def test_a_refusal_at_the_published_port_keeps_the_remedy(monkeypatch):
    published = _free_port()
    monkeypatch.setenv(RT._RUN_PORTS_ENV_1134, str(published))
    out = RT.TestAPITool().execute("GET", f"http://localhost:{published}/health")
    assert out.success is False
    assert "Bring the stack up" in out.error_message


def test_unknown_ports_keep_the_remedy(monkeypatch):
    monkeypatch.delenv(RT._RUN_PORTS_ENV_1134, raising=False)
    out = RT.TestAPITool().execute("GET", f"http://localhost:{_free_port()}/health")
    assert "Bring the stack up" in out.error_message
