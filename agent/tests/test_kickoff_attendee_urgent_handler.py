"""Round-8c regression tests for Fix #2: kickoff_request urgent handler.

Round-8b smoke confirmed every attendee (design/backend/frontend/verifier)
received the kickoff_request urgent event and logged
``[<role>] Handling urgent kickoff_request`` — but the urgent-event
handler had no msg_type=="kickoff_request" branch, so it returned
without entering an LLM turn. The attendee never recorded a meeting
decision; the kickoff sat headless until the orchestrator's legacy
``send_message(task_ready)`` fired ~100s later.

These tests pin the round-8c handler contract closed-by-construction
WITHOUT requiring a real LLM run:

  * ``_check_and_handle_urgent`` MUST dispatch to
    ``_handle_kickoff_request`` for msg_type=="kickoff_request" and
    return True (so the urgent loop drains the event from the inbox).
  * ``_handle_kickoff_request`` MUST render the agent's
    ``kickoff_response_prompt`` macro with (meeting_id, milestone_index,
    requirements, expected_section) and run the agentic loop with that
    rendered prompt as initial_prompt.
  * If render_macro fails / agent has no template, the handler MUST
    fall back to a plain-text prompt that still instructs the LLM to
    author one workhub_add_meeting_decision call.
  * A missing meeting_id MUST log a warning and return without firing
    an LLM turn (closed-by-construction: a malformed event payload
    should not silently dispatch).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))


# ---------------------------------------------------------------------------
# Stub agent exposing exactly what _handle_kickoff_request reads. We import
# the unbound method off the messaging mixin and bind it to the stub.
# ---------------------------------------------------------------------------


class _StubMessage:
    """Mirror of BaseMessage shape for the handler's payload/metadata reads."""
    def __init__(
        self,
        payload: Dict[str, Any],
        msg_type: str = "kickoff_request",
        source: str = "orchestrator",
    ) -> None:
        self.payload = payload
        self.metadata = {"msg_type": msg_type}
        # header.source_agent_id is what _handle_task_ready reads; the
        # kickoff handler doesn't care but include it for completeness.
        self.header = SimpleNamespace(
            source_agent_id=source,
            message_id="msg-1",
        )


class _StubAgent:
    """Minimal stub of a ConfigurableAgent for _handle_kickoff_request."""
    def __init__(
        self,
        agent_id: str = "design",
        template: str = "design_agent.j2",
        render_result: str = "RENDERED",
        render_raises: bool = False,
    ) -> None:
        self.agent_id = agent_id
        self._prompt_cfg = {"template": template}
        self._compose_system_prompt_called = 0
        self._render_macro_calls: List[Dict[str, Any]] = []
        self._render_result = render_result
        self._render_raises = render_raises
        self._agentic_loop_calls: List[Dict[str, Any]] = []
        self._focus_hub_during_loop: List[Any] = []
        self._processing_state = None
        self._focus_hub = None
        self._deferred_task_ready_messages: List[Any] = []
        # Logger
        import logging
        self._logger = logging.getLogger("stub_agent")

    def _compose_system_prompt(self) -> str:
        self._compose_system_prompt_called += 1
        return "SYSTEM PROMPT"

    def render_macro(self, template: str, macro: str, **ctx: Any) -> str:
        self._render_macro_calls.append({
            "template": template,
            "macro": macro,
            "ctx": ctx,
        })
        if self._render_raises:
            raise RuntimeError("render boom")
        return self._render_result

    async def run_agentic_loop(
        self,
        *,
        system_prompt: str,
        initial_prompt: str,
        max_steps: int,
    ) -> None:
        self._agentic_loop_calls.append({
            "system_prompt": system_prompt,
            "initial_prompt": initial_prompt,
            "max_steps": max_steps,
        })
        # Capture _focus_hub at the moment the loop runs so the
        # closed-by-construction Fix #5-bis test can assert it.
        self._focus_hub_during_loop.append(self._focus_hub)

    async def _drain_deferred_task_ready_messages(self) -> None:
        pass

    def _ensure_initial_section_decision(self, **_kw) -> None:
        # Round-8g Fix #C is exercised in test_kickoff_phase_handler_ack.py
        # with a real hubs stub. Here we just no-op so the existing
        # shape-only tests in this file aren't coupled to that helper.
        pass

    def _ensure_revision_section_decision(self, **_kw) -> None:
        # Round-8h Fix #F exercised in test_kickoff_phase_handler_ack.py.
        # Stub kept side-effect-free so shape-only attendee tests don't
        # need to model the workhub stores.
        pass


def _handler_method():
    from multi_agent.agents.runtime.messaging import AgentMessaging
    return AgentMessaging._handle_kickoff_request


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    finally:
        asyncio.set_event_loop(None)
        loop.close()


def _kickoff_payload(meeting_id: str = "mtg-1") -> Dict[str, Any]:
    return {
        "meeting_id": meeting_id,
        "milestone_index": 1,
        "requirements": ["Build a minimal blog."],
        "expected_sections": ["design", "backend", "frontend", "verifier"],
    }


# ---------------------------------------------------------------------------
# Happy path: handler renders macro + runs agentic loop with rendered prompt.
# ---------------------------------------------------------------------------


def test_handler_renders_macro_and_runs_agentic_loop():
    stub = _StubAgent(agent_id="design", render_result="DESIGN-RENDERED-PROMPT")
    msg = _StubMessage(_kickoff_payload())
    _run(_handler_method()(stub, msg))

    # Exactly one render_macro call with the expected kwargs.
    assert len(stub._render_macro_calls) == 1
    call = stub._render_macro_calls[0]
    assert call["template"] == "design_agent.j2"
    assert call["macro"] == "kickoff_response_prompt"
    assert call["ctx"]["meeting_id"] == "mtg-1"
    assert call["ctx"]["milestone_index"] == 1
    assert call["ctx"]["expected_section"] == "design"
    assert call["ctx"]["requirements"] == "Build a minimal blog."

    # Exactly one agentic-loop call with the rendered macro as
    # initial_prompt + system_prompt from _compose_system_prompt.
    assert len(stub._agentic_loop_calls) == 1
    loop_call = stub._agentic_loop_calls[0]
    assert loop_call["initial_prompt"] == "DESIGN-RENDERED-PROMPT"
    assert loop_call["system_prompt"] == "SYSTEM PROMPT"
    # max_steps cap exists — the macro says "Run ONCE then finish()"
    # but a confused LLM should still be bounded. Round-8c reviewer
    # tightened the default from 50 to 12; ~4-8 steps fit normal
    # check_inbox -> draft -> add_meeting_decision -> finish().
    assert loop_call["max_steps"] == 12


# ---------------------------------------------------------------------------
# Section identity: handler uses agent_id verbatim for expected_section.
# Each of the 4 attendees subscribes to kickoff_request and the section
# is identical to the agent_id (per agent_subscriptions.py + macro arity).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "agent_id,template", [
        ("backend", "backend_agent.j2"),
        ("frontend", "frontend_agent.j2"),
        ("verifier", "verifier_agent.j2"),
    ],
)
def test_handler_passes_agent_id_as_expected_section(agent_id, template):
    stub = _StubAgent(agent_id=agent_id, template=template)
    _run(_handler_method()(stub, _StubMessage(_kickoff_payload())))
    call = stub._render_macro_calls[0]
    assert call["ctx"]["expected_section"] == agent_id
    assert call["template"] == template


# ---------------------------------------------------------------------------
# Requirements: list[str] is flattened to a single string for the macro.
# ---------------------------------------------------------------------------


def test_handler_flattens_list_requirements():
    payload = _kickoff_payload()
    payload["requirements"] = [
        "Requirement A: build auth.",
        "",  # empty string should be dropped
        "Requirement B: build posts.",
    ]
    stub = _StubAgent()
    _run(_handler_method()(stub, _StubMessage(payload)))
    rendered_ctx = stub._render_macro_calls[0]["ctx"]
    assert "Requirement A" in rendered_ctx["requirements"]
    assert "Requirement B" in rendered_ctx["requirements"]


# ---------------------------------------------------------------------------
# Fallback: if render_macro raises, the handler uses a plain-text prompt.
# Still runs the agentic loop (does NOT swallow the kickoff event).
# ---------------------------------------------------------------------------


def test_handler_falls_back_when_render_macro_raises():
    stub = _StubAgent(render_raises=True)
    _run(_handler_method()(stub, _StubMessage(_kickoff_payload())))
    assert len(stub._render_macro_calls) == 1  # tried
    assert len(stub._agentic_loop_calls) == 1
    initial = stub._agentic_loop_calls[0]["initial_prompt"]
    # Fallback prompt MUST instruct the LLM to call
    # workhub_add_meeting_decision — the whole point of the response.
    assert "workhub_add_meeting_decision" in initial
    assert "mtg-1" in initial


# ---------------------------------------------------------------------------
# Missing meeting_id: handler MUST log a warning + return without firing.
# Closed-by-construction: a malformed event payload should not silently
# dispatch into an LLM turn that has no way to record a decision.
# ---------------------------------------------------------------------------


def test_handler_skips_when_payload_missing_meeting_id(caplog):
    stub = _StubAgent()
    payload = _kickoff_payload()
    payload.pop("meeting_id")
    _run(_handler_method()(stub, _StubMessage(payload)))
    # No agentic loop fired — the handler bailed.
    assert stub._agentic_loop_calls == []
    # Warning landed (the handler is supposed to log a warning here).
    # The caplog fixture captures records propagated to the root
    # logger; the stub's "stub_agent" logger inherits from root by
    # default.
    warned = any(
        "without meeting_id" in r.message
        for r in caplog.records
    )
    assert warned, f"expected a warning log; got {caplog.records}"


# ---------------------------------------------------------------------------
# _check_and_handle_urgent dispatch: when an urgent msg with
# msg_type='kickoff_request' arrives, _handle_kickoff_request is called and
# the urgent loop returns True. This pins the round-8b regression closed:
# without the new branch, the urgent handler returned False and the event
# was effectively dropped.
# ---------------------------------------------------------------------------


def test_check_and_handle_urgent_dispatches_kickoff_request():
    """The urgent-event handler MUST have a kickoff_request branch that
    dispatches to _handle_kickoff_request. We inspect the source code as
    a closed-by-construction check (vs. booting the full priority queue
    which would be a much larger integration setup)."""
    import inspect
    from multi_agent.agents.runtime.messaging import AgentMessaging
    src = inspect.getsource(AgentMessaging._check_and_handle_urgent)
    assert 'msg_type == "kickoff_request"' in src, (
        "round-8c Fix #2: _check_and_handle_urgent must branch on "
        "msg_type=='kickoff_request' and dispatch to "
        "_handle_kickoff_request. Without this branch, the round-8b "
        "regression returns: attendees receive the event but never "
        "enter an LLM turn."
    )
    assert "_handle_kickoff_request" in src


# ---------------------------------------------------------------------------
# Fix #5-bis closed-by-construction pin: _handle_kickoff_request MUST
# pre-set _focus_hub = "workhub" before running the agentic loop AND
# restore the prior value on exit.
#
# Background (the round-8d-bis 20:35 smoke surfaced this AFTER Fix #5
# landed): the per-step tool ranker (tool_surface.py:rank_tool_names
# line 203) filters always_include AGAINST candidate_names — so a tool
# already dropped by _apply_hub_focus cannot be recovered by
# ACTION_STAGE_ALWAYS_INCLUDE. Without _focus_hub pre-set, every WorkHub
# write tool (INCLUDING workhub_add_meeting_decision, the ONE tool the
# kickoff_response_prompt macro instructs the LLM to call) is filtered
# out before the always-include set is consulted. Observed in the live
# smoke as "Required tools such as workhub_add_meeting_decision /
# focus_hub / codehub_commit are unavailable" + immediate finish().
# ---------------------------------------------------------------------------


def test_handler_presets_focus_hub_workhub_during_agentic_loop():
    """The handler MUST set self._focus_hub = "workhub" BEFORE calling
    run_agentic_loop so the per-step _apply_hub_focus filter doesn't
    drop workhub writes (round-8d-bis regression class)."""
    stub = _StubAgent()
    _run(_handler_method()(stub, _StubMessage(_kickoff_payload())))
    # Captured at the moment run_agentic_loop fired.
    assert stub._focus_hub_during_loop == ["workhub"], (
        f"round-8d Fix #5-bis: _focus_hub during agentic loop must be "
        f"'workhub', got {stub._focus_hub_during_loop}. Without this, "
        "_apply_hub_focus drops workhub_add_meeting_decision before "
        "always_include can rescue it, and attendees finish() blocked."
    )


def test_handler_restores_prior_focus_hub_on_exit():
    """The handler MUST restore the prior _focus_hub on exit (try/finally)
    so the legacy task_ready flow — which sets focus dynamically — isn't
    left in an inconsistent state."""
    stub = _StubAgent()
    stub._focus_hub = "registryhub"  # simulate a prior focus
    _run(_handler_method()(stub, _StubMessage(_kickoff_payload())))
    # During the loop it was workhub; after the loop it's restored.
    assert stub._focus_hub_during_loop == ["workhub"]
    assert stub._focus_hub == "registryhub", (
        "round-8d Fix #5-bis: handler must restore prior _focus_hub "
        f"on exit; got {stub._focus_hub!r}"
    )


def test_handler_restores_none_focus_when_none_was_prior():
    """When the agent had no prior focus (None), the handler must
    restore that too — not leave _focus_hub stuck on 'workhub'."""
    stub = _StubAgent()
    assert stub._focus_hub is None
    _run(_handler_method()(stub, _StubMessage(_kickoff_payload())))
    assert stub._focus_hub_during_loop == ["workhub"]
    assert stub._focus_hub is None


def test_handler_restores_focus_even_when_agentic_loop_raises():
    """If run_agentic_loop raises mid-flight, the prior _focus_hub MUST
    still be restored (the try/finally guarantees this)."""

    class _ExplodingAgent(_StubAgent):
        async def run_agentic_loop(self, **_kw):
            self._focus_hub_during_loop.append(self._focus_hub)
            raise RuntimeError("simulated mid-loop failure")

    stub = _ExplodingAgent()
    stub._focus_hub = "codehub"
    _run(_handler_method()(stub, _StubMessage(_kickoff_payload())))
    assert stub._focus_hub_during_loop == ["workhub"]
    assert stub._focus_hub == "codehub", (
        "round-8d Fix #5-bis: try/finally must restore prior focus "
        "even when the agentic loop raises."
    )


def test_source_pins_focus_hub_preset_and_restore():
    """Source-inspection guard so a future refactor can't silently drop
    the pre-set/restore pair."""
    import inspect
    from multi_agent.agents.runtime.messaging import AgentMessaging
    src = inspect.getsource(AgentMessaging._handle_kickoff_request)
    assert 'self._focus_hub = "workhub"' in src, (
        "round-8d Fix #5-bis source-pin: _handle_kickoff_request must "
        "explicitly assign self._focus_hub = 'workhub' before the "
        "agentic loop."
    )
    assert "prev_focus_hub" in src and "self._focus_hub = prev_focus_hub" in src, (
        "round-8d Fix #5-bis source-pin: handler must capture the prior "
        "_focus_hub and restore it in a finally block."
    )


# ---------------------------------------------------------------------------
# Round-8f.1: kickoff_revision_request — attendee single-pass revision in
# response to a facilitator_note(action='request_revision'). The driver
# (``runtime/kickoff/facilitate.py:request_revisions``) broadcasts the event
# to all subscribers but lists ``revisers`` in the payload; each attendee
# must guard on ``self.agent_id in revisers`` and only fire its LLM turn if
# flagged. Same Fix #5-bis pre-set of ``_focus_hub='workhub'`` so the
# always-include ranker can surface ``workhub_add_meeting_decision``.
# ---------------------------------------------------------------------------


def _revision_payload(
    revisers=None,
    meeting_id: str = "mtg-1",
):
    return {
        "meeting_id": meeting_id,
        "milestone_index": 1,
        "current_round": 2,
        "revisers": list(revisers) if revisers is not None else ["backend", "verifier"],
        "revision_focus": {
            "backend": "Tighten /posts response schema to match design.",
            "verifier": "Add predicate covering 401 on missing auth.",
        },
        "facilitator_rationale": "Backend and verifier disagree on auth shape.",
        "acks_consensus_on": ["data_model.users", "ui_route.posts_list"],
        "open_questions": ["Should /posts/:id include author_email?"],
    }


def test_revision_handler_renders_macro_when_agent_is_reviser():
    """A flagged reviser MUST render kickoff_revision_prompt with all
    facilitator-payload kwargs and run ONE agentic loop with the rendered
    prompt + max_steps=12."""
    from multi_agent.agents.runtime.messaging import AgentMessaging
    handler = AgentMessaging._handle_kickoff_revision_request
    stub = _StubAgent(
        agent_id="backend",
        template="backend_agent.j2",
        render_result="BACKEND-REVISION-PROMPT",
    )
    msg = _StubMessage(_revision_payload(), msg_type="kickoff_revision_request")
    _run(handler(stub, msg))

    # render_macro called once with the kickoff_revision_prompt macro
    # and the expected payload kwargs.
    assert len(stub._render_macro_calls) == 1
    call = stub._render_macro_calls[0]
    assert call["template"] == "backend_agent.j2"
    assert call["macro"] == "kickoff_revision_prompt"
    ctx = call["ctx"]
    assert ctx["meeting_id"] == "mtg-1"
    assert ctx["milestone_index"] == 1
    assert ctx["current_round"] == 2
    assert ctx["revision_focus"] == {
        "backend": "Tighten /posts response schema to match design.",
        "verifier": "Add predicate covering 401 on missing auth.",
    }
    assert ctx["facilitator_rationale"] == "Backend and verifier disagree on auth shape."
    assert ctx["acks_consensus_on"] == ["data_model.users", "ui_route.posts_list"]
    assert ctx["open_questions"] == ["Should /posts/:id include author_email?"]

    # Agentic loop fired once with the rendered prompt; max_steps=12.
    assert len(stub._agentic_loop_calls) == 1
    loop_call = stub._agentic_loop_calls[0]
    assert loop_call["initial_prompt"] == "BACKEND-REVISION-PROMPT"
    assert loop_call["system_prompt"] == "SYSTEM PROMPT"
    assert loop_call["max_steps"] == 12


def test_revision_handler_skips_when_agent_not_in_revisers():
    """A non-reviser (e.g. frontend when only backend+verifier are
    flagged) MUST NOT render the macro and MUST NOT enter the agentic
    loop. Closed-by-construction: the broadcast may fan-out to all
    subscribers, but only the listed revisers act."""
    from multi_agent.agents.runtime.messaging import AgentMessaging
    handler = AgentMessaging._handle_kickoff_revision_request
    stub = _StubAgent(agent_id="frontend", template="frontend_agent.j2")
    payload = _revision_payload(revisers=["backend", "verifier"])
    msg = _StubMessage(payload, msg_type="kickoff_revision_request")
    _run(handler(stub, msg))

    assert stub._render_macro_calls == [], (
        "frontend is NOT in revisers=[backend, verifier]; render_macro "
        "must not be called."
    )
    assert stub._agentic_loop_calls == [], (
        "non-reviser must not enter the agentic loop."
    )


def test_revision_handler_presets_focus_hub_workhub_during_loop():
    """Fix #5-bis class regression pin: the handler MUST set
    self._focus_hub = 'workhub' before run_agentic_loop so the per-step
    ranker can surface workhub_add_meeting_decision. Without this, the
    revision LLM turn finish('blocked') for the same reason kickoff_request
    did pre-round-8d."""
    from multi_agent.agents.runtime.messaging import AgentMessaging
    handler = AgentMessaging._handle_kickoff_revision_request
    stub = _StubAgent(agent_id="backend", template="backend_agent.j2")
    stub._focus_hub = "registryhub"  # simulate a prior focus
    _run(handler(stub, _StubMessage(
        _revision_payload(), msg_type="kickoff_revision_request"
    )))
    # Captured at the moment run_agentic_loop fired.
    assert stub._focus_hub_during_loop == ["workhub"], (
        f"_handle_kickoff_revision_request must pre-set _focus_hub='workhub' "
        f"during the agentic loop; got {stub._focus_hub_during_loop}."
    )
    # And restored on exit.
    assert stub._focus_hub == "registryhub", (
        f"handler must restore prior _focus_hub on exit; got {stub._focus_hub!r}."
    )


def test_revision_handler_dispatched_from_check_and_handle_urgent():
    """Source-inspection pin: ``_check_and_handle_urgent`` MUST have a
    branch on ``msg_type == 'kickoff_revision_request'`` that dispatches
    to ``_handle_kickoff_revision_request``. Without this, the urgent
    loop would log 'Handling urgent kickoff_revision_request' and drop
    the event — same regression class as round-8b for kickoff_request."""
    import inspect
    from multi_agent.agents.runtime.messaging import AgentMessaging
    src = inspect.getsource(AgentMessaging._check_and_handle_urgent)
    assert "'kickoff_revision_request'" in src or '"kickoff_revision_request"' in src, (
        "round-8f.1: _check_and_handle_urgent must branch on "
        "msg_type=='kickoff_revision_request'."
    )
    assert "_handle_kickoff_revision_request" in src
