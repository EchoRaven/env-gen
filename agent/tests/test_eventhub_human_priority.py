import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

import pytest
from multi_agent.runtime.eventhub import EventHub


def test_human_user_is_highest_priority(tmp_path):
    assert EventHub._PRIORITY_RANK["human_user"] > EventHub._PRIORITY_RANK["critical"]


def test_human_user_event_delivered_to_inbox(tmp_path):
    eh = EventHub(tmp_path)
    eh.publish_event(
        source_hub="human_user",
        event_type="human_message",
        payload={"text": "hello backend agent"},
        recipients=["backend"],
        priority="human_user",
    )
    inbox = eh.list_inbox("backend", unread_only=False)
    assert len(inbox) == 1
    assert inbox[0]["priority"] == "human_user"
    assert inbox[0]["payload"]["text"] == "hello backend agent"


def test_human_user_event_passes_critical_floor_subscription(tmp_path):
    """Agents with priority_floor='critical' must still receive human_user events."""
    eh = EventHub(tmp_path)
    eh.subscribe(agent="frontend", source_hub="*", event_type="*", priority_floor="critical")
    eh.publish_event(
        source_hub="human_user",
        event_type="human_message",
        payload={"text": "urgent"},
        recipients=[],   # rely on subscription fan-out
        priority="human_user",
    )
    inbox = eh.list_inbox("frontend", unread_only=False)
    assert len(inbox) == 1


def test_priority_normal_event_does_not_reach_critical_floor(tmp_path):
    """Sanity: confirm priority floor still excludes lower-priority events."""
    eh = EventHub(tmp_path)
    eh.subscribe(agent="frontend", source_hub="*", event_type="*", priority_floor="critical")
    eh.publish_event(
        source_hub="codehub",
        event_type="commit",
        payload={},
        recipients=[],
        priority="normal",
    )
    inbox = eh.list_inbox("frontend", unread_only=False)
    assert inbox == []


def test_publish_human_message_creates_thread(tmp_path):
    eh = EventHub(tmp_path)
    event = eh.publish_human_message(
        text="please add a login button",
        target_agents=["frontend", "backend"],
        from_user="haibotong",
    )
    assert event["priority"] == "human_user"
    assert event["event_type"] == "human_message"
    assert event["source_hub"] == "human_user"
    assert sorted(event["recipients"]) == ["backend", "frontend"]
    assert event["payload"]["text"] == "please add a login button"
    assert event["payload"]["from_user"] == "haibotong"


def test_publish_human_message_reuses_thread_id(tmp_path):
    eh = EventHub(tmp_path)
    e1 = eh.publish_human_message(text="first", target_agents=["backend"], from_user="haibotong")
    e2 = eh.publish_human_message(text="second", target_agents=["backend"], thread_id=e1["thread_id"], from_user="haibotong")
    assert e2["thread_id"] == e1["thread_id"]


def test_publish_agent_reply_to_thread(tmp_path):
    eh = EventHub(tmp_path)
    initial = eh.publish_human_message(text="hello", target_agents=["backend"], from_user="haibotong")
    reply = eh.publish_agent_reply(
        thread_id=initial["thread_id"],
        agent="backend",
        text="acknowledged, working on it",
    )
    assert reply["thread_id"] == initial["thread_id"]
    assert reply["source_hub"] == "backend"
    assert reply["event_type"] == "agent_reply"
    assert reply["payload"]["text"] == "acknowledged, working on it"
    # Reply must go back to the human (recipient "human_user") AND the original
    # participants so other agents can see it.
    assert "human_user" in reply["recipients"]


def test_list_conversations_returns_threads_with_human_events(tmp_path):
    eh = EventHub(tmp_path)
    e1 = eh.publish_human_message(text="task A", target_agents=["backend"], from_user="haibotong")
    e2 = eh.publish_human_message(text="task B", target_agents=["frontend"], from_user="haibotong")
    convos = eh.list_conversations()
    thread_ids = sorted(c["thread_id"] for c in convos)
    assert thread_ids == sorted([e1["thread_id"], e2["thread_id"]])


def test_list_conversations_filters_by_participant(tmp_path):
    eh = EventHub(tmp_path)
    eh.publish_human_message(text="A", target_agents=["backend"], from_user="haibotong")
    eh.publish_human_message(text="B", target_agents=["frontend"], from_user="haibotong")
    backend_convos = eh.list_conversations(participant="backend")
    assert len(backend_convos) == 1
    assert "backend" in backend_convos[0]["participants"]


def test_list_conversations_includes_message_count_and_last_message(tmp_path):
    eh = EventHub(tmp_path)
    initial = eh.publish_human_message(text="first", target_agents=["backend"], from_user="haibotong")
    eh.publish_agent_reply(thread_id=initial["thread_id"], agent="backend", text="ack")
    eh.publish_human_message(text="follow-up", target_agents=["backend"], thread_id=initial["thread_id"], from_user="haibotong")
    convos = eh.list_conversations()
    assert len(convos) == 1
    c = convos[0]
    assert c["message_count"] == 3
    assert c["last_message_text"] == "follow-up"
    assert c["last_message_source"] == "human_user"


def test_publish_human_message_rejects_empty_target_agents(tmp_path):
    eh = EventHub(tmp_path)
    with pytest.raises(ValueError):
        eh.publish_human_message(text="x", target_agents=[])


def test_publish_human_message_rejects_empty_text(tmp_path):
    eh = EventHub(tmp_path)
    with pytest.raises(ValueError):
        eh.publish_human_message(text="", target_agents=["backend"])
