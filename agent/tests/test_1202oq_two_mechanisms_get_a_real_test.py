"""#1202oq — behavioural coverage for two mechanisms whose only wiring test read the source.

An audit of this suite mutated the mechanism behind ~85 recent fix tests and found eight that
stayed green anyway. Both below were in that set, and both are cheap to drive for real:

* `_stack_serving_1202ne` — the bounded wait for a recycled stack to answer again. Every test
  that mentions it does `monkeypatch.setattr(HP, "_stack_serving_1202ne", ...)`, so the function
  itself had never executed in a test: replacing its body with `return True` (never waits — the
  re-walk hits a still-booting stack, which is the 12-blank-pages defect #1202ne exists to
  prevent) or `return False` left 7/7 green.
* `DockerUpTool`'s host-fault notice (#1202mh) — the test class is named "A notice that never
  reaches a tool result is the defect this fixes", and its wiring test called the helper again
  instead of the tool. `if _hf1202mh:` → `if False:` left 10/10 green and 132 passed across all
  18 docker/host-fault files.

These drive the real objects: a wait against a served/unserved endpoint, and the real
`DockerUpTool.execute` against a compose failure.
"""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime import heal_pipeline as HP  # noqa: E402
from multi_agent.runtime import validation_runner as VR  # noqa: E402


def test_1202ne_the_wait_returns_only_once_both_ends_serve(monkeypatch):
    calls = {"n": 0}
    # frontend answers at once; the backend needs three polls — the recycled-stack case
    def _http(method, url, timeout=5, **kw):
        if url.endswith("/health"):
            calls["n"] += 1
            return {"status": 200 if calls["n"] >= 3 else 502}
        return {"status": 200}

    monkeypatch.setattr(VR, "_http", _http)
    monkeypatch.setattr(HP.time, "sleep", lambda s: None)
    assert HP._stack_serving_1202ne("http://fe", "http://be", timeout_s=30, poll_s=0) is True
    assert calls["n"] == 3, calls


def test_1202ne_it_gives_up_at_the_deadline_instead_of_hanging(monkeypatch):
    monkeypatch.setattr(VR, "_http", lambda *a, **k: {"status": 502})
    monkeypatch.setattr(HP.time, "sleep", lambda s: None)
    assert HP._stack_serving_1202ne("http://fe", "http://be", timeout_s=0, poll_s=0) is False


def test_1202ne_a_frontend_only_stack_is_not_asked_about_a_backend(monkeypatch):
    seen = []

    def _http(method, url, timeout=5, **kw):
        seen.append(url)
        return {"status": 200}

    monkeypatch.setattr(VR, "_http", _http)
    assert HP._stack_serving_1202ne("http://fe", None, timeout_s=5, poll_s=0) is True
    assert seen == ["http://fe"]


def test_1202mh_the_host_fault_notice_reaches_the_tool_result(monkeypatch, tmp_path):
    from tools import docker_tools as DT

    compose = tmp_path / "docker" / "docker-compose.yml"
    compose.parent.mkdir(parents=True)
    compose.write_text("services:\n  backend:\n    image: x\n")

    tool = DT.DockerUpTool.__new__(DT.DockerUpTool)
    tool.workspace = SimpleNamespace(base_root=str(tmp_path))
    monkeypatch.setattr(DT.DockerUpTool, "_find_compose_file", lambda self: compose)
    monkeypatch.setattr(DT, "_docker_daemon_reachable", lambda *a, **k: True)
    monkeypatch.setattr(DT, "_missing_build_contexts", lambda *a, **k: [])
    monkeypatch.setattr(DT, "_run_compose", lambda *a, **k: SimpleNamespace(
        returncode=1, stdout="",
        stderr="failed to solve: write /var/lib/docker/...: no space left on device"))

    out = asyncio.run(tool.execute())
    text = (out.error_message or "") + " ".join(getattr(out, "notices", []) or [])
    assert out.success is False
    assert "no space left" in text.lower()
    # the point of #1202mh: the lane is told this is the HOST, not its code
    assert "operator" in text.lower() or "host" in text.lower(), text[:400]
