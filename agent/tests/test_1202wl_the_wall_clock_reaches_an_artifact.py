"""#1202wl: per-tool wall clock must survive the run that measured it.

`duration_ms` is computed for every tool call and was only formatted into a log line. Run
logs are not kept, so the pipeline's largest cost could only be found while a run was live
-- both measurements that drove the last cost work were read off a terminal: check_inbox at
45 min/run (fixed by #1202sg, 12x) and run_validation at 49 min.

A per-operation store already existed and was DEAD THREE WAYS: `record_operation_time` has
no caller, `get_performance_stats` has no reader, and `system_performance.json` appears in 0
of the corpus's 176 run directories. It is not reused, because it re-reads and re-writes its
entire JSON file on EVERY call -- at ~674 tool calls per run that is precisely the
synchronous read-modify-write storm #1202sg spent a third of the wall clock removing.

So the totals are aggregated in memory and flushed every 50 calls: each write is
self-consistent, the I/O is ~14 writes per run, and a stopped run loses only the tail.
"""
import json
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))
sys.path.insert(0, _AGENT)

from multi_agent.agents.runtime.tooling import AgentTooling  # noqa: E402


class _Host(AgentTooling):
    """The two attributes the recorder reads, and nothing else."""

    def __init__(self, base):
        class _Hubs:
            base_dir = base
        self._hubs = _Hubs()
        self.agent_id = "tester"


def _artifact(tmp_path):
    return tmp_path / "logs" / "tool_timings_1202wl.json"


def test_nothing_is_written_before_the_first_flush(tmp_path):
    h = _Host(tmp_path)
    for _ in range(h._FLUSH_EVERY_1202WL - 1):
        h._record_tool_ms_1202wl("read", 5)
    assert not _artifact(tmp_path).exists(), (
        "a write per call is the storm #1202sg removed; it must batch")


def test_the_totals_land_on_the_flush(tmp_path):
    h = _Host(tmp_path)
    for _ in range(h._FLUSH_EVERY_1202WL):
        h._record_tool_ms_1202wl("check_inbox", 100)
    row = json.loads(_artifact(tmp_path).read_text(encoding="utf-8"))
    assert row["tools"]["check_inbox"]["count"] == h._FLUSH_EVERY_1202WL
    assert row["tools"]["check_inbox"]["total_ms"] == 100.0 * h._FLUSH_EVERY_1202WL
    assert row["calls"] == h._FLUSH_EVERY_1202WL


def test_the_slowest_tool_is_first(tmp_path):
    """The artifact exists to answer "where did the wall clock go", so it is ranked."""
    h = _Host(tmp_path)
    for _ in range(10):
        h._record_tool_ms_1202wl("write", 1)
        h._record_tool_ms_1202wl("check_inbox", 500)
        h._record_tool_ms_1202wl("read", 2)
    for _ in range(h._FLUSH_EVERY_1202WL):
        h._record_tool_ms_1202wl("read", 1)
    tools = list(json.loads(_artifact(tmp_path).read_text(encoding="utf-8"))["tools"])
    assert tools[0] == "check_inbox", tools


def test_the_maximum_is_kept_not_just_the_mean(tmp_path):
    """r120's worst check_inbox was 200s against a 2.0s median; an average hides that."""
    h = _Host(tmp_path)
    h._record_tool_ms_1202wl("check_inbox", 200_000)
    for _ in range(h._FLUSH_EVERY_1202WL - 1):
        h._record_tool_ms_1202wl("check_inbox", 1)
    got = json.loads(_artifact(tmp_path).read_text(encoding="utf-8"))["tools"]["check_inbox"]
    assert got["max_ms"] == 200_000.0, got


def test_a_non_numeric_duration_is_ignored_not_fatal(tmp_path):
    h = _Host(tmp_path)
    h._record_tool_ms_1202wl("read", None)
    h._record_tool_ms_1202wl("read", "slow")
    assert getattr(h, "_tool_ms_1202wl", {}) == {} or \
        h._tool_ms_1202wl.get("read", {}).get("count", 0) == 0


def test_no_hub_and_no_workspace_writes_nothing(tmp_path):
    """Reporting must never be the reason a tool call fails."""
    h = _Host(tmp_path)
    h._hubs = None
    h.workspace = None
    for _ in range(h._FLUSH_EVERY_1202WL):
        h._record_tool_ms_1202wl("read", 1)
    assert not _artifact(tmp_path).exists()
    assert h._flush_tool_ms_1202wl() is False


def test_the_run_directory_wins_over_the_workspace(tmp_path):
    """A lane worktree's workspace is not the run directory -- the gate has paid for that."""
    run = tmp_path / "run"
    worktree = tmp_path / "worktree"
    h = _Host(run)
    h.workspace = worktree
    for _ in range(h._FLUSH_EVERY_1202WL):
        h._record_tool_ms_1202wl("read", 1)
    assert (run / "logs" / "tool_timings_1202wl.json").exists()
    assert not (worktree / "logs").exists()


def test_the_dead_store_is_still_dead(tmp_path):
    """★ The reason this does not call `record_operation_time`: it writes per call.

    If that ever gains a caller, this note and the choice here should be revisited together.
    """
    import inspect

    from env_generator.llm_generator.tools import system_tools

    src = inspect.getsource(system_tools.SystemMetrics.record_operation_time)
    assert "_save(" in src and "_load(" in src, (
        "the reuse was declined because it is a full read-modify-write per call; if that "
        "changed, reuse it instead of this aggregate")


def test_the_recorder_is_on_the_live_tool_path():
    """★ This ticket exists because a timing facility was never wired. Pin the wiring.

    Asserted over the AST in both files: the recorder is called inside `_log_tool_result`,
    and `_log_tool_result` is called by the step pipeline right after it measures a tool.
    A helper nobody calls is the defect being fixed, not a fix.
    """
    import ast

    def _read(path):
        with open(path, encoding="utf-8") as fh:      # #1202eu
            return fh.read()

    runtime = os.path.join(_AGENT, "env_generator", "llm_generator", "multi_agent",
                           "agents", "runtime")
    tooling = ast.parse(_read(os.path.join(runtime, "tooling.py")))
    logger_fn = next((n for n in ast.walk(tooling)
                      if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                      and n.name == "_log_tool_result"), None)
    assert logger_fn is not None, "_log_tool_result is gone"
    assert any(isinstance(c, ast.Call)
               and getattr(c.func, "attr", "") == "_record_tool_ms_1202wl"
               for c in ast.walk(logger_fn)), (
        "the recorder is not called where every tool call is logged")

    pipeline = ast.parse(_read(os.path.join(runtime, "step_pipeline", "tooling.py")))
    assert any(isinstance(c, ast.Call)
               and getattr(c.func, "attr", "") == "_log_tool_result"
               for c in ast.walk(pipeline)), (
        "nothing on the step pipeline logs a tool result, so nothing records its duration")
