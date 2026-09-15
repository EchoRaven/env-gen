"""#1202mu: a RunHub run must not tear down a stack somebody else brought up.

`RunHub.start_run` ends in `finally: compose.down()`. The stack it names is the run's one shared
app — booted by validation_runner, walked by the verifier, driven by the test-user squad.

tiktok-r125, 01:30–01:40:
    01:30:22  test-user squad launched in the background, 12 agents against :8005/:8006
    01:38:07  the orchestrator's `run_start` begins; 01:38:10 it completes — and runs `down`
    01:38:14  "#1198 shared browser driver is gone"
    01:38:44  squad: connection refused, NOTHING IS LISTENING
    01:39:15+ three P0 bugs "running app became unreachable" filed against the lanes;
              squad verdict DEFECTS holds M1's release

Corpus: 938 `run_start` calls. A connection refusal follows within 60s after 203 of them, against
110 in the same-length window just before the call.

A stack already answering `/health` before `up` belongs to someone else and is left running. A
stack that was not is still torn down (the leak protection the `finally` exists for). The live
probe only runs for the real lifecycle; a caller that injects `compose` decides for itself.
"""
import http.server
import socket
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime.hubs.runhub import service as SVC  # noqa: E402
from multi_agent.runtime.hubs.runhub.compose import ComposeResult, HealthcheckResult  # noqa: E402
from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402


class _Compose:
    def __init__(self):
        self.down_called = False

    def up(self, timeout=180.0):
        return ComposeResult(returncode=0)

    def down(self, timeout=60.0):
        self.down_called = True
        return ComposeResult(returncode=0)


class _Healthy:
    def wait(self):
        return HealthcheckResult(healthy=True, status_code=200, attempts=1, elapsed_s=0.01)


def _run(tmp, **kw):
    reg = HubRegistry(Path(tmp))
    compose = kw.pop("compose", _Compose())
    reg.runhub.start_run(branch="integration", generated_dir=tmp, base_url=kw.pop("base_url",
                         "http://127.0.0.1:9"), agent="orchestrator", compose=compose,
                         healthcheck=_Healthy(), probe_runner=lambda plan: {"status_code": 200},
                         **kw)
    return compose


def test_a_stack_that_was_already_serving_is_left_running():
    with tempfile.TemporaryDirectory() as tmp:
        assert _run(tmp, already_serving=True).down_called is False


def test_a_stack_this_run_brought_up_is_still_torn_down():
    with tempfile.TemporaryDirectory() as tmp:
        assert _run(tmp, already_serving=False).down_called is True


def test_an_injected_compose_without_an_answer_keeps_the_old_teardown():
    """Hermetic: injected lifecycles never trigger the live probe, whatever listens here."""
    with tempfile.TemporaryDirectory() as tmp:
        assert _run(tmp).down_called is True


# ── the live probe itself ─────────────────────────────────────────────────────────────────

class _Health(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200 if self.path == "/health" else 404)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *a):
        pass


def test_the_probe_sees_a_serving_app():
    srv = http.server.HTTPServer(("127.0.0.1", 0), _Health)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        assert SVC._stack_serving_1202mu(f"http://127.0.0.1:{srv.server_port}") is True
    finally:
        srv.shutdown()


def test_the_probe_sees_nothing_on_a_closed_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    assert SVC._stack_serving_1202mu(f"http://127.0.0.1:{port}", timeout_s=1.0) is False


def test_the_real_caller_gets_the_live_probe(monkeypatch):
    """`run_start` injects no compose, so the probe decides; a serving stack survives it."""
    calls = []
    monkeypatch.setattr(SVC, "_stack_serving_1202mu", lambda url, **k: calls.append(url) or True)
    downs = []

    class _Lifecycle(_Compose):
        def __init__(self, *a, **k):
            super().__init__()

        def down(self, timeout=60.0):
            downs.append(1)
            return ComposeResult(returncode=0)

    monkeypatch.setattr(SVC, "ComposeLifecycle", _Lifecycle, raising=False)
    import multi_agent.runtime.hubs.runhub.compose as C
    monkeypatch.setattr(C, "ComposeLifecycle", _Lifecycle)
    with tempfile.TemporaryDirectory() as tmp:
        reg = HubRegistry(Path(tmp))
        reg.runhub.start_run(branch="integration", generated_dir=tmp,
                             base_url="http://127.0.0.1:9", agent="orchestrator",
                             healthcheck=_Healthy(), probe_runner=lambda plan: {"status_code": 200})
    assert calls == ["http://127.0.0.1:9"]
    assert downs == []


def test_an_injected_compose_ignores_a_live_app_on_the_same_port():
    """The hermetic rule proven against something actually listening: this host carries old
    runs' stacks on real ports (3001 and 8081 answer /health), which tests also use."""
    srv = http.server.HTTPServer(("127.0.0.1", 0), _Health)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            compose = _run(tmp, base_url=f"http://127.0.0.1:{srv.server_port}")
            assert compose.down_called is True
    finally:
        srv.shutdown()
