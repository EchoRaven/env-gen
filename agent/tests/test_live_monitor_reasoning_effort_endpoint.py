import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # agent/
SRC = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(SRC)):
    if p not in sys.path:
        sys.path.insert(0, p)


def test_set_reasoning_effort_per_lane_unknown_and_all(tmp_path):
    from live_monitor_server import (
        create_project_call,
        set_reasoning_effort_call,
        _project_workspace,
    )
    from multi_agent.runtime.reasoning_effort import read_effort_map

    root = tmp_path
    pid = create_project_call(root, {"name": "re-test"})["id"]
    ws = _project_workspace(root, pid)

    # per-lane merge
    set_reasoning_effort_call(root, pid, {"backend": "high"})
    assert read_effort_map(ws)["backend"] == "high"

    # unknown value normalizes to medium; merge preserves prior lanes
    set_reasoning_effort_call(root, pid, {"verifier": "bogus"})
    m = read_effort_map(ws)
    assert m["verifier"] == "medium"
    assert m["backend"] == "high"  # untouched by the verifier write

    # {"all": ...} sets every resident lane
    set_reasoning_effort_call(root, pid, {"all": "low"})
    m = read_effort_map(ws)
    for lane in ("orchestrator", "backend", "frontend", "verifier", "debugger", "knowledge"):
        assert m[lane] == "low"

    # metadata keys (leading underscore) are ignored, not written as lanes
    set_reasoning_effort_call(root, pid, {"_requester_role": "admin", "orchestrator": "high"})
    m = read_effort_map(ws)
    assert "_requester_role" not in m
    assert m["orchestrator"] == "high"


def test_set_reasoning_effort_unknown_project(tmp_path):
    from live_monitor_server import set_reasoning_effort_call

    assert "error" in set_reasoning_effort_call(tmp_path, "nope", {"all": "high"})
