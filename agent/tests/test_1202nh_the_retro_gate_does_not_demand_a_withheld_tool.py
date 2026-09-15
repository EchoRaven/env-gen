"""#1202nh: the retro gate must not demand `submit_retro` while #361 withholds it.

#361 offers `deliver_project` and `submit_retro` only on the final milestone. RetroBeforeDeliverPolicy
blocked every milestone's `report_completion` until a retro existed, so before the final milestone
the orchestrator was told to call a tool it did not have. Across the run logs: 82
`report_completion blocked by retro gate` in 17 logs; tiktok-r125's M2 resume, 9 — answered with
"submit_retro is not exposed in this tool surface" and another turn.
"""
from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))

from multi_agent.agents.runtime.step_pipeline.tooling import (  # noqa: E402
    withhold_delivery_before_final_milestone)
from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402
from multi_agent.workflow_policies import RetroBeforeDeliverPolicy  # noqa: E402


class _Agent:
    def __init__(self, hubs, final):
        self.agent_id = "orchestrator"
        self._hubs = hubs
        self._logger = MagicMock()
        if final is not None:
            self._is_final_milestone = final


def _gate(tool, final):
    with tempfile.TemporaryDirectory() as tmp:
        hubs = HubRegistry(Path(tmp))
        agent = _Agent(hubs, final)
        msgs = []
        out = asyncio.run(RetroBeforeDeliverPolicy().handle_finish(
            agent, tool_name=tool, tool_args={}, tool_call=MagicMock(), tool_call_id="tc",
            messages=msgs, files_created=[], files_modified=[]))
        return out, msgs, withhold_delivery_before_final_milestone(agent)


def test_r125_m2_report_completion_is_not_blocked_on_a_withheld_retro():
    out, msgs, withheld = _gate("report_completion", final=False)
    assert withheld is True
    assert out is None and msgs == []


def test_the_final_milestone_still_requires_the_retro():
    out, msgs, withheld = _gate("report_completion", final=True)
    assert withheld is False
    assert out == {"action": "continue"} and "submit_retro" in str(msgs[1].content)
    out, _, _ = _gate("deliver_project", final=True)
    assert out == {"action": "continue"}


def test_an_unstamped_agent_is_final_as_before():
    out, _, withheld = _gate("report_completion", final=None)
    assert withheld is False and out == {"action": "continue"}
