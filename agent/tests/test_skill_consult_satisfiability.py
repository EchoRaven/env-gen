"""Regression: a skill-consult precondition (release_readiness_consulted /
api_contract_consulted) must stay SATISFIABLE.

bsb900gpt (2026-06-19): the orchestrator's delivery toolset omitted get_skill,
but deliver_project was gated on consulting the release-readiness skill — whose
only clearing action is `get_skill(name=...)`. With no get_skill tool the gate
was unsatisfiable: the orchestrator looped deliver_project ("I don't have access
to the get_skill tool") until it exhausted its action rounds and the run was
killed without ever delivering. The gate must auto-consult (and pass) when the
agent cannot call get_skill, while still nudging agents that CAN consult.
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
    release_readiness_consulted,
    _require_skill_consulted,
)


def _agent(*, tools, consulted=None, agent_id="orchestrator"):
    return SimpleNamespace(
        agent_id=agent_id,
        _tool_instances={t: object() for t in tools},
        _consulted_skills=set(consulted or []),
    )


def test_already_consulted_passes():
    a = _agent(tools=["get_skill", "deliver_project"], consulted=["release-readiness"])
    assert release_readiness_consulted(a, "deliver_project", {}) is None


def test_get_skill_available_but_not_consulted_blocks():
    # The normal nudge path: agent CAN consult, so it must be told to.
    a = _agent(tools=["get_skill", "deliver_project"])
    err = release_readiness_consulted(a, "deliver_project", {})
    assert err is not None
    assert "get_skill(name='release-readiness')" in err
    assert "release-readiness" not in a._consulted_skills  # not auto-consulted when satisfiable


def test_get_skill_unavailable_auto_consults_and_passes():
    # The bsb900gpt deadlock: no get_skill in the tool surface → gate must NOT
    # block (it would loop forever); auto-consult + pass instead.
    a = _agent(tools=["deliver_project", "check_inbox", "send_message", "ask_agent"])
    assert release_readiness_consulted(a, "deliver_project", {}) is None
    assert "release-readiness" in a._consulted_skills  # recorded for the trace


def test_generic_helper_handles_missing_consulted_attr():
    # An agent with no _consulted_skills attr + no get_skill must still pass.
    a = SimpleNamespace(agent_id="x", _tool_instances={})
    assert _require_skill_consulted("release-readiness", "deliver_project", a) is None
    assert "release-readiness" in a._consulted_skills


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
