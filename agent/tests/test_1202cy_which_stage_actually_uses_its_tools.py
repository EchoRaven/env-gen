"""#1202cy — record which STAGE a tool call belonged to.

#1202cr priced the stages and #1202cx spent that: the verifier was paying $10.30 a run
for an `edit_code` stage while `agent/verifier` sat 0 commits ahead of integration with
0 files different. That case was only decidable because "did this role author a commit"
happens to be answerable from git.

`deliver` is the next suspect — 20.6% of r42's spend, with its delivery tools
(deliver_project, deliverability_check/summary, report_completion) used by the
ORCHESTRATOR alone — but the lanes commit from it, and no log in the corpus records
which stage a tool call belonged to, so "is the lane's deliver stage doing anything"
cannot be answered. Trimming a stage on a guess is not cheap: action_stage_policy warns
that a stage is the HOME of its categories and mis-trimming strands granted tools,
wedging the lane on MALFORMED_FUNCTION_CALL. So the instrument comes before the cut.
"""
import json
import logging
import time
from pathlib import Path

import pytest

from utils import llm as llm_mod
from utils.llm import record_stage_tool_1202cy, stage_tools_1202cy


@pytest.fixture(autouse=True)
def _fresh():
    llm_mod._STAGE_TOOLS_1202CY.clear()
    yield
    llm_mod._STAGE_TOOLS_1202CY.clear()


def test_calls_are_attributed_to_the_stage_that_made_them():
    for _ in range(5):
        record_stage_tool_1202cy("frontend:edit_code", "write")
    record_stage_tool_1202cy("frontend:deliver", "codehub_commit")
    got = stage_tools_1202cy()
    assert got["frontend:edit_code"] == {"write": 5}
    assert got["frontend:deliver"] == {"codehub_commit": 1}


def test_the_busiest_stage_sorts_first():
    """The read that matters is a scan for a stage with NOTHING in it, so ordering has
    to put the loud ones out of the way."""
    record_stage_tool_1202cy("a:one", "t")
    for _ in range(9):
        record_stage_tool_1202cy("b:two", "t")
    assert list(stage_tools_1202cy()) == ["b:two", "a:one"]


def test_accounting_never_raises():
    """This sits on the path every tool result takes; an exception here would cost the
    call, which is far worse than a missing count."""
    record_stage_tool_1202cy(None, None)
    record_stage_tool_1202cy(object(), object())
    assert stage_tools_1202cy()


def test_it_reaches_run_budget_json(tmp_path):
    """#947: a measurement that lives only in memory has no ceiling, and this one is read
    AFTER the run, which is the only time the question gets asked."""
    from env_generator.llm_generator.multi_agent.runtime.run_budget import RunBudget

    record_stage_tool_1202cy("verifier:run_checks", "run_validation")
    RunBudget(Path(tmp_path), logging.getLogger("t")).write(
        {"max_wall_sec": 1e5, "max_ticks": 9}, time.time(), 1.0, 1, "running")
    payload = json.loads((Path(tmp_path) / "run_budget.json").read_text())
    assert payload["stage_tools_1202cy"]["verifier:run_checks"] == {"run_validation": 1}


def test_the_hook_sits_where_every_tool_result_passes():
    """Anchored on the #1171 byte counter, which the corpus already trusts as the single
    point every tool result crosses — a second hook elsewhere would undercount."""
    src = Path("env_generator/llm_generator/multi_agent/agents/runtime/"
               "step_pipeline/tooling.py").read_text()
    # #943: anchored on the next landmark, not a byte count — a window sized in bytes
    # breaks the moment a comment above it grows.
    i = src.index("record_tool_result_bytes_1171(tool_name")
    after = src[i:src.index("#1191: DO NOT CARRY THE SAME SNAPSHOT TWICE", i)]
    assert "record_stage_tool_1202cy" in after
    assert "_active_stage" in after
