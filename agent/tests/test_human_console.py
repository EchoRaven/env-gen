import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

import pytest
from multi_agent.runtime.hub_registry import HubRegistry


def test_hub_registry_exposes_human_console(tmp_path):
    reg = HubRegistry(tmp_path, project_name="X", human_user_id="alice@test")
    assert reg.human_console is not None


def test_start_conversation_returns_thread_id(tmp_path):
    reg = HubRegistry(tmp_path, project_name="X", human_user_id="alice@test")
    convo = reg.human_console.start_conversation(
        target_agents=["backend"],
        text="please scaffold the API",
    )
    assert "thread_id" in convo
    assert convo["participants"] == ["backend"]
    assert convo["first_message_text"] == "please scaffold the API"


def test_send_message_appends_to_existing_thread(tmp_path):
    reg = HubRegistry(tmp_path, project_name="X", human_user_id="alice@test")
    convo = reg.human_console.start_conversation(target_agents=["backend"], text="hi")
    tid = convo["thread_id"]
    reg.human_console.send_message(thread_id=tid, text="follow-up question")
    messages = reg.human_console.list_messages(thread_id=tid)
    assert len(messages) == 2
    assert messages[1]["text"] == "follow-up question"


def test_list_conversations_returns_summaries(tmp_path):
    reg = HubRegistry(tmp_path, project_name="X", human_user_id="alice@test")
    reg.human_console.start_conversation(target_agents=["backend"], text="A")
    reg.human_console.start_conversation(target_agents=["frontend"], text="B")
    convos = reg.human_console.list_conversations()
    assert len(convos) == 2
    assert {c["last_message_text"] for c in convos} == {"A", "B"}


def test_list_messages_returns_ordered_by_time(tmp_path):
    reg = HubRegistry(tmp_path, project_name="X", human_user_id="alice@test")
    convo = reg.human_console.start_conversation(target_agents=["backend"], text="first")
    reg.hubs.eventhub.publish_agent_reply(thread_id=convo["thread_id"], agent="backend", text="ack")
    reg.human_console.send_message(thread_id=convo["thread_id"], text="third")
    messages = reg.human_console.list_messages(thread_id=convo["thread_id"])
    texts = [m["text"] for m in messages]
    assert texts == ["first", "ack", "third"]


def test_mark_resolved_updates_thread_status(tmp_path):
    reg = HubRegistry(tmp_path, project_name="X", human_user_id="alice@test")
    convo = reg.human_console.start_conversation(target_agents=["backend"], text="task")
    reg.human_console.mark_resolved(thread_id=convo["thread_id"])
    resolved = reg.human_console.list_conversations(status="resolved")
    assert len(resolved) == 1
    open_convos = reg.human_console.list_conversations(status="open")
    assert open_convos == []


def test_send_message_to_unknown_thread_raises(tmp_path):
    reg = HubRegistry(tmp_path, project_name="X", human_user_id="alice@test")
    with pytest.raises(ValueError):
        reg.human_console.send_message(thread_id="nope", text="x")


def test_start_conversation_with_no_agents_raises(tmp_path):
    reg = HubRegistry(tmp_path, project_name="X", human_user_id="alice@test")
    with pytest.raises(ValueError):
        reg.human_console.start_conversation(target_agents=[], text="x")
