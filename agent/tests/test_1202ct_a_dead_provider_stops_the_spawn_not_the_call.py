"""#1202ct — decline task_ready while the provider is latched terminal.

#326 aborts the run on a terminal provider, but from the orchestrator's TICK loop, up
to ~60s away. In that window every task_ready still opened a full agentic loop and
registered 141 tools before the first call discovered the provider was dead. r41
measured 81 dead spawns per MINUTE after its spend ceiling latched at $400.01 — 88 in
the first 135 seconds, 267KB of log.

#1161 guards the step boundary and #1161b the staged call. Neither is reached: the
waste happens upstream of the first LLM call, which is exactly why it stayed invisible
to both.
"""
from pathlib import Path

import pytest


def test_the_guard_precedes_the_starting_work_log_line():
    """Order is the whole mechanism: after the 'Starting work' line the loop has already
    been entered and the tools registered, which is the cost being avoided."""
    src = Path("env_generator/llm_generator/multi_agent/agents/runtime/messaging.py").read_text()
    body = src[src.index("async def _handle_task_ready"):]
    body = body[:body.index("lane_recipe")]
    guard = body.index("terminal_llm_error as _term_1202ct")
    starting = body.index("Starting work - triggered by")
    assert guard < starting


def test_the_decline_reports_failure_upstream():
    """A silent return would leave the orchestrator waiting on a lane that never answers.
    The status update is what lets it stop rather than re-dispatch."""
    src = Path("env_generator/llm_generator/multi_agent/agents/runtime/messaging.py").read_text()
    body = src[src.index("async def _handle_task_ready"):]
    body = body[:body.index("lane_recipe")]
    assert 'status="failed"' in body
    assert "terminal_llm_1202ct" in body


def test_a_healthy_provider_is_not_declined():
    """The guard must key on the latch, not on its own existence — a run with a live
    provider must reach 'Starting work' exactly as before."""
    src = Path("env_generator/llm_generator/multi_agent/agents/runtime/messaging.py").read_text()
    body = src[src.index("async def _handle_task_ready"):]
    body = body[:body.index("lane_recipe")]
    assert "if _dead_1202ct:" in body
    assert body.index("if _dead_1202ct:") < body.index("Starting work - triggered by")


def test_a_broken_import_cannot_block_a_working_run():
    """Cost-avoidance must never become a new failure path: if the latch cannot be read,
    the lane proceeds rather than declining every task."""
    src = Path("env_generator/llm_generator/multi_agent/agents/runtime/messaging.py").read_text()
    body = src[src.index("async def _handle_task_ready"):]
    body = body[:body.index("lane_recipe")]
    assert "except Exception:\n            _dead_1202ct = None" in body
