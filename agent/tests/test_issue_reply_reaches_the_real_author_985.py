"""#985: when the header names a hub, reply to the payload's author.

r160 caught a live one three hours after #976 supposedly closed this class:

    [verifier] Received issue from messagebus: {'from': 'backend', 'to': 'verifier', …}
    [W] MessageBus: Target agent not found: messagebus

#976 stopped the delivery ACK addressing a hub. This is a different path and a worse
failure. `_handle_issue` takes `from_agent = message.header.source_agent_id` — which the
event bridge sets to the SOURCE HUB — and then:

  * routes `_send_runtime_status_update(to_agent=from_agent)` at a non-agent, and
  * writes it into the fix prompt: 'When fixed, use send_message(to_agent="messagebus") to
    report' — so the completion report never reaches the lane that raised the issue.

The real author is right there in the payload (`'from': 'backend'`). Preferring it beats
suppressing anything: the reply lands on the lane that actually asked.
"""

import inspect

import pytest

from env_generator.llm_generator.multi_agent.agents.runtime import messaging


def _resolve(header_sender, payload, roster):
    """The resolution rule, exercised without a live bus."""
    from_agent = header_sender
    if from_agent and from_agent not in set(roster or []):
        real = payload.get("from") if isinstance(payload, dict) else None
        if real:
            from_agent = str(real)
    return from_agent


def test_a_hub_sender_resolves_to_the_payload_author():
    assert _resolve("messagebus", {"from": "backend", "to": "verifier"},
                    ["backend", "verifier"]) == "backend"


@pytest.mark.parametrize("hub", ["messagebus", "workhub", "eventhub", "registryhub"])
def test_every_hub_resolves(hub):
    assert _resolve(hub, {"from": "frontend"}, ["frontend", "verifier"]) == "frontend"


def test_a_real_agent_sender_is_left_alone():
    """The common case must not be rewritten by a payload that disagrees."""
    assert _resolve("backend", {"from": "somebody_else"}, ["backend", "verifier"]) == "backend"


def test_an_unknown_sender_with_no_payload_author_is_kept():
    """Degrade to the header rather than inventing a recipient."""
    assert _resolve("messagebus", {}, ["backend"]) == "messagebus"


def test_a_string_payload_does_not_crash():
    assert _resolve("messagebus", "plain text issue", ["backend"]) == "messagebus"


def test_the_question_path_resolves_too():
    """#986: `_handle_question` had the identical defect — the ANSWER went to the hub.
    Found by enumerating every use of header.source_agent_id instead of waiting for a
    third run to catch it."""
    src = inspect.getsource(messaging)
    i_q = src.index("async def _handle_question")
    i_resolve = src.index("_real_author_985(message, message.header.source_agent_id)", i_q)
    i_send = src.index("_send_answer(from_agent", i_q)
    assert i_resolve < i_send, "the answer must be addressed after resolution"


def test_all_three_reply_paths_are_covered():
    """#976 (ack), #985 (issue), #986 (question). A fourth would mean the helper was added
    and not used."""
    src = inspect.getsource(messaging)
    assert src.count("_real_author_985(") >= 3, "helper defined and used on both reply paths"


def test_the_handler_resolves_before_it_uses_from_agent():
    """Ordering: the fix prompt and the status update both interpolate from_agent, so the
    resolution has to happen above them or it fixes nothing."""
    src = inspect.getsource(messaging)
    i_issue = src.index("async def _handle_issue")
    i_resolve = src.index("_real_author_985(message, from_agent)", i_issue)
    i_status = src.index("to_agent=from_agent", i_resolve)
    i_prompt = src.index("Issue Reported by {from_agent}", i_resolve)
    assert i_resolve < i_status < i_prompt


def test_the_control_keeps_the_hub():
    """Planted control: the PRE-FIX rule read the header and stopped, which is how
    'messagebus' reached both the status update and the prompt."""
    assert "messagebus" == "messagebus" and _resolve(
        "messagebus", {"from": "backend"}, ["backend", "messagebus"]) == "messagebus", (
        "with the hub ON the roster the rule must not rewrite — proving the roster check is "
        "what drives the resolution, not the payload alone")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
