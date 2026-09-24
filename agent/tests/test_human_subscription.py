# agent/tests/test_human_subscription.py
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

import pytest
from multi_agent.runtime.eventhub import EventHub


def test_subscribe_to_human_messages_helper_creates_sub(tmp_path):
    eh = EventHub(tmp_path)
    sub = eh.subscribe_to_human_messages(agent="orchestrator")
    assert sub["agent"] == "orchestrator"
    assert sub["source_hub"] == "human_user"
    assert sub["event_type"] == "human_message"
    assert sub["priority_floor"] == "human_user"


def test_subscribed_agent_receives_human_message_even_if_not_targeted(tmp_path):
    """Orchestrator subscribes once and gets all human chatter for awareness."""
    eh = EventHub(tmp_path)
    eh.subscribe_to_human_messages(agent="orchestrator")
    eh.publish_human_message(text="hello backend", target_agents=["backend"], from_user="test_user")
    inbox = eh.list_inbox("orchestrator", unread_only=False)
    assert len(inbox) == 1
    assert inbox[0]["payload"]["text"] == "hello backend"


def test_subscribe_helper_is_idempotent(tmp_path):
    eh = EventHub(tmp_path)
    eh.subscribe_to_human_messages(agent="orchestrator")
    eh.subscribe_to_human_messages(agent="orchestrator")
    subs = eh.get_subscriptions(agent="orchestrator")
    # subscribe() uses id = "{agent}:{source}:{type}" so the second call replaces
    assert len(subs) == 1
