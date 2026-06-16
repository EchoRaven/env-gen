"""FIX #28 — bound the orchestrator's ask_agent drift.

instagram-core froze after the orchestrator asked ~28 questions in a no-progress
question/answer ping-pong that derailed the implementing backend (1 of 8
endpoints) and ended in a coordination deadlock. orchestrator_ask_cap allows asks
while the run is progressing (implemented-endpoint count rising) and blocks once
it has asked > THRESHOLD times with no new endpoint implemented. Self-resets on
real progress so it never wedges a healthy run.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.agents.runtime.preconditions import (  # noqa: E402
    orchestrator_ask_cap,
    resolve_precondition,
)


def _orch(impl_count):
    eps = {}
    for i in range(impl_count):
        eps[f"i{i}"] = {"method": "GET", "path": f"/api/r{i}",
                        "status": "implemented"}
    eps["d0"] = {"method": "POST", "path": "/api/x", "status": "defined"}
    return SimpleNamespace(
        _hubs=SimpleNamespace(registryhub=SimpleNamespace(get_endpoints=lambda: eps)))


def test_allows_under_threshold():
    o = _orch(2)
    for _ in range(15):
        assert orchestrator_ask_cap(o, "ask_agent", {}) is None


def test_blocks_after_threshold_without_progress():
    o = _orch(2)
    for _ in range(15):
        orchestrator_ask_cap(o, "ask_agent", {})
    blocked = orchestrator_ask_cap(o, "ask_agent", {})
    assert blocked is not None
    assert "ask_agent paused" in blocked


def test_resets_on_endpoint_progress():
    # Use a mutable endpoint set so we can simulate an endpoint getting implemented.
    state = {"impl": 2}

    def _eps():
        eps = {f"i{i}": {"method": "GET", "path": f"/api/r{i}",
                         "status": "implemented"} for i in range(state["impl"])}
        eps["d0"] = {"method": "POST", "path": "/api/x", "status": "defined"}
        return eps

    o = SimpleNamespace(_hubs=SimpleNamespace(
        registryhub=SimpleNamespace(get_endpoints=_eps)))
    for _ in range(15):
        orchestrator_ask_cap(o, "ask_agent", {})
    assert orchestrator_ask_cap(o, "ask_agent", {}) is not None  # blocked
    state["impl"] = 3  # an endpoint got implemented → progress
    assert orchestrator_ask_cap(o, "ask_agent", {}) is None       # reset, allowed


def test_vacuous_pass_on_no_registryhub():
    o = SimpleNamespace(_hubs=SimpleNamespace(registryhub=None))
    # never blocks while progress can't be measured (count still grows but cur=0)
    for _ in range(15):
        assert orchestrator_ask_cap(o, "ask_agent", {}) is None


def test_registered():
    assert resolve_precondition("orchestrator_ask_cap") is orchestrator_ask_cap


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
