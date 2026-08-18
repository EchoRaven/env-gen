"""#968: the orchestrator's finish() must actually end its turn.

`FinishContinuePolicy` translated every `finish()` into "keep going" and appended three
messages, so the orchestrator's agentic loop never exited and its conversation never
reset. Measured on netflix r156: messages 266→336 (+10 per step), content_chars
159,540→179,596 (+2,900 per step), 5.4M prompt tokens in 22 minutes, and `finish` was the
ONLY action tool called in 168 of ~200 steps. The loop had no other exit —
`deliver_project` is gated on `delivery_phase_reached`, unreachable during kickoff.

Polling is NOT removed. The orchestrator prompt's own stop_rules say "coord_tick is NOT a
finish() call — the pipeline loop manages tick lifecycle"; that mechanism dispatches a
fresh task (and a fresh conversation) whenever the lane is FREE. Exiting on finish() is
what makes the lane free.

Safety facts this rests on, verified before the change:
  * agent/utils/base_agent.py:754   `_main_loop` keeps consuming `_message_queue`
  * .../multi_agent/agents/base.py:693  `run_loop` drains urgent messages every 0.5s
  Both are independent of the agentic loop, so an exited lane still receives work.
"""

import asyncio
import logging
from pathlib import Path

import pytest
import yaml

from env_generator.llm_generator.multi_agent.workflow_policies import (
    FinishContinuePolicy, RetroBeforeDeliverPolicy, create_workflow_policies)

_CONFIG = (Path(__file__).resolve().parents[1]
           / "env_generator/llm_generator/multi_agent/agents/agents_config.yaml")


def _profile(name):
    cfg = yaml.safe_load(_CONFIG.read_text(encoding="utf-8"))
    agents = cfg.get("profiles") or {}
    assert name in agents, f"profile {name} not found; config layout changed"
    return agents[name]


def _kinds(profile):
    return [str((p or {}).get("kind", "")) for p in (profile.get("workflow_policies") or [])]


def test_the_orchestrator_no_longer_declares_finish_continue():
    kinds = _kinds(_profile("orchestrator"))
    assert "finish_continue" not in kinds, (
        "finish_continue makes the coordinator's turn non-terminating, so its conversation "
        f"never resets; declared kinds are {kinds}")


def test_no_profile_picked_it_up_instead():
    """The policy class stays (it is generic) but nothing should be using it on a lane
    whose idle mechanism is a re-dispatched task."""
    cfg = yaml.safe_load(_CONFIG.read_text(encoding="utf-8"))
    agents = cfg.get("profiles") or {}
    users = [n for n, p in agents.items()
             if isinstance(p, dict) and "finish_continue" in _kinds(p)]
    assert users == [], f"finish_continue reappeared on {users}"


def test_the_orchestrator_keeps_its_delivery_gate():
    """Removing one policy must not disarm the other."""
    policies = create_workflow_policies(_profile("orchestrator"))
    assert any(isinstance(p, RetroBeforeDeliverPolicy) for p in policies), (
        "retro_before_deliver is unrelated to the spin and must survive")
    assert not any(isinstance(p, FinishContinuePolicy) for p in policies)


def test_finish_now_falls_through_to_the_default_path():
    """With no policy claiming `finish`, `handle_finish` must yield nothing — that is what
    lets the tool run and the turn return instead of looping."""
    policies = create_workflow_policies(_profile("orchestrator"))

    class _Agent:
        agent_id = "orchestrator"
        _logger = logging.getLogger("test.finish968")

    async def _ask(policy):
        return await policy.handle_finish(
            _Agent(), tool_name="finish", tool_args={"message": "done"},
            tool_call=None, tool_call_id="c1", messages=[],
            files_created=[], files_modified=[])

    for policy in policies:
        outcome = asyncio.run(_ask(policy))
        assert outcome is None or outcome.get("action") != "continue", (
            f"{type(policy).__name__} still forces the loop to continue on a plain finish")


def test_the_control_still_continues(caplog):
    """Planted control: a SYNTHETIC profile that declares finish_continue must still get a
    `continue` outcome. Proves the assertion above discriminates rather than passing
    because handle_finish is inert."""
    synthetic = {
        "workflow_policies": [
            {"kind": "finish_continue", "tool_name": "finish",
             "followup_message": "Continue monitoring."},
        ],
    }
    policies = create_workflow_policies(synthetic)
    assert any(isinstance(p, FinishContinuePolicy) for p in policies)

    class _Agent:
        agent_id = "synthetic"
        _logger = logging.getLogger("test.finish968")

        async def _execute_tool(self, name, args):
            return type("R", (), {"success": True, "data": "ok"})()

    messages = []
    outcome = asyncio.run(policies[0].handle_finish(
        _Agent(), tool_name="finish", tool_args={"message": "done"},
        tool_call="tc", tool_call_id="c1", messages=messages,
        files_created=[], files_modified=[]))

    assert outcome == {"action": "continue"}, (
        "the control was supposed to force a continue; if it does not, the main "
        "assertion proves nothing")
    assert len(messages) == 3, (
        f"the control should append assistant+tool+followup (the +3 of the +10 per step), "
        f"got {len(messages)}")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
