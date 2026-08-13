r"""#658: two constructors were called with keyword arguments the classes do not have.

Both are guaranteed `TypeError`, both sat on paths that only fire in the uncommon case, and both
were invisible until the type checker could resolve imports ([tool.pyrefly] in pyproject.toml).

1. `ToolResult(error=...)` x3 in tools/hub_tools.py

   ToolResult's fields are success/data/error_message/execution_time/metadata. There is no
   `error`. The callers are written correctly —

       coerced = _coerce_dict_param(decision, "decision")
       if isinstance(coerced, ToolResult):
           return coerced

   — but the object they test for could never be constructed, so the entire validation-error
   path was dead: an agent passing a malformed `decision`/`schema` got a raw TypeError instead
   of the crafted message. A second bug hid behind the first: `success` DEFAULTS TO TRUE, so
   even had `error=` existed the caller would have returned a SUCCESS result carrying an error
   string. `.fail()` fixes both.

2. `BaseMessage(content=...)` x2 in multi_agent/team_runtime/plan_decision.py

   BaseMessage's field is `payload`. `submit_plan` is an agent-callable tool (agents/base.py:137,
   tool_bundles.py:661) and the orchestrator wires the protocol for real
   (orchestrator.py:612), so this is live. It survived because of the auto-approve branch:

       if not require_approval or len(steps) <= self._auto_approve_threshold:   # threshold 3
           ... return plan                                                      # never messages

   Any plan with 3 or fewer steps short-circuits. Submit FOUR and it raises. Proven directly
   before the fix:

       submit_plan(steps=[...4 items...])
       -> TypeError: BaseMessage.__init__() got an unexpected keyword argument 'content'
"""
import asyncio

import pytest

from utils.tool import ToolResult
from env_generator.llm_generator.tools.hub_tools import _coerce_dict_param as coerce


# --- 1. the validator can now build its rejection ---------------------------------------------

def test_the_class_really_has_no_error_field():
    """The premise. If someone adds `error`, this file's first half becomes moot."""
    with pytest.raises(TypeError):
        ToolResult(error="x")


@pytest.mark.parametrize("bad,why", [
    ("not json at all", "unparseable string"),
    ("[1, 2, 3]", "JSON-list"),
    (42, "int"),
])
def test_a_malformed_argument_returns_a_result_instead_of_raising(bad, why):
    out = coerce(bad, "decision")
    assert isinstance(out, ToolResult)


def test_the_rejection_is_a_FAILURE_not_a_success():
    """`success` defaults to True — the caller returns this object straight to the agent."""
    out = coerce("not json at all", "decision")
    assert out.success is False
    assert out.error_message


def test_the_message_names_the_argument_and_what_arrived():
    """#634: an error that does not say what was wrong costs the agent a round."""
    out = coerce(42, "schema")
    assert "schema" in out.error_message
    assert "int" in out.error_message


def test_None_is_deliberately_passed_through_not_rejected():
    """`if value is None or isinstance(value, dict): return value` — an optional argument."""
    assert coerce(None, "decision") is None


def test_a_good_dict_is_still_passed_through():
    assert coerce({"a": 1}, "decision") == {"a": 1}
    assert coerce('{"a": 1}', "decision") == {"a": 1}


def test_empty_is_still_an_empty_dict_not_a_rejection():
    assert coerce("", "decision") == {}
    assert coerce("   ", "decision") == {}


def test_no_site_still_uses_the_nonexistent_kwarg():
    """Code only — the fix's own comment quotes the broken call to explain it."""
    import inspect
    from env_generator.llm_generator.tools import hub_tools
    code = [l for l in inspect.getsource(hub_tools).splitlines()
            if not l.lstrip().startswith("#")]
    assert not [l for l in code if "ToolResult(error=" in l]


# --- 2. the plan message can now be built --------------------------------------------------------

class _Bus:
    def __init__(self):
        self.sent = []

    async def send(self, msg):
        self.sent.append(msg)


def _protocol():
    from env_generator.llm_generator.multi_agent.team_runtime.plan_decision import (
        PlanDecisionProtocol,
    )
    bus = _Bus()
    return PlanDecisionProtocol(bus, lead_agent_id="orch"), bus


def test_the_class_really_has_no_content_field():
    from utils.message import BaseMessage
    with pytest.raises(TypeError):
        BaseMessage(content={"a": 1})


def test_a_plan_above_the_threshold_no_longer_raises():
    """Four steps against an auto-approve threshold of three — the case that crashed."""
    proto, bus = _protocol()
    plan = asyncio.run(proto.submit_plan(agent_id="a", title="t", description="d",
                                         steps=[{"s": i} for i in range(4)]))
    from env_generator.llm_generator.multi_agent.team_runtime.models import PlanStatus
    assert plan.status is PlanStatus.SUBMITTED
    assert len(bus.sent) == 1


def test_the_message_carries_the_request_on_the_real_field():
    proto, bus = _protocol()
    asyncio.run(proto.submit_plan(agent_id="a", title="t", description="d",
                                  steps=[{"s": i} for i in range(4)]))
    msg = bus.sent[0]
    assert msg.payload["type"] == "plan_decision_request"
    assert msg.payload["plan"]["title"] == "t"
    assert msg.payload["criteria"] is not None or "criteria" in msg.payload


def test_the_threshold_is_what_hid_this():
    """Pins WHY it shipped: every smaller plan short-circuits before building a message."""
    proto, bus = _protocol()
    assert proto._auto_approve_threshold == 3
    asyncio.run(proto.submit_plan(agent_id="a", title="t", description="d",
                                  steps=[{"s": i} for i in range(3)]))
    assert bus.sent == [], "3 steps must still auto-approve without messaging"


def test_require_approval_false_still_short_circuits():
    proto, bus = _protocol()
    from env_generator.llm_generator.multi_agent.team_runtime.models import PlanStatus
    plan = asyncio.run(proto.submit_plan(agent_id="a", title="t", description="d",
                                         steps=[{"s": i} for i in range(9)],
                                         require_approval=False))
    assert plan.status is PlanStatus.APPROVED
    assert bus.sent == []


def test_the_revision_message_was_broken_the_same_way():
    import inspect
    from env_generator.llm_generator.multi_agent.team_runtime import plan_decision
    src = inspect.getsource(plan_decision)
    assert "content={" not in src
    assert src.count('payload={') == 2


def test_the_message_routes_to_the_lead():
    proto, bus = _protocol()
    asyncio.run(proto.submit_plan(agent_id="worker-1", title="t", description="d",
                                  steps=[{"s": i} for i in range(4)]))
    hdr = bus.sent[0].header
    assert hdr.source_agent_id == "worker-1"
    assert hdr.target_agent_id == "orch"


# --- provenance -------------------------------------------------------------------------------

def test_the_reachability_finding_is_recorded():
    import inspect
    from env_generator.llm_generator.multi_agent.team_runtime.plan_decision import (
        PlanDecisionProtocol,
    )
    flat = " ".join(
        inspect.getsource(PlanDecisionProtocol.submit_plan).replace("#", " ").split())
    assert "auto-approve branch" in flat or "auto-approve" in flat
    assert "3" in flat


def test_the_second_bug_behind_the_first_is_recorded():
    import inspect
    from env_generator.llm_generator.tools import hub_tools
    flat = " ".join(inspect.getsource(hub_tools._coerce_dict_param).replace("#", " ").split())
    assert "DEFAULTS TO TRUE" in flat
    assert "IS NOT A FIELD" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
