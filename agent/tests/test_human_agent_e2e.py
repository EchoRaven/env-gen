# agent/tests/test_human_agent_e2e.py
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

import pytest

from multi_agent.runtime.hub_registry import HubRegistry


def test_e2e_one_human_message_to_one_agent_and_reply(tmp_path):
    reg = HubRegistry(tmp_path, project_name="X", human_user_id="test_user")

    # 1. Human starts conversation with backend
    convo = reg.human_console.start_conversation(
        target_agents=["backend"],
        text="please add /api/users",
    )
    tid = convo["thread_id"]

    # 2. Backend sees it in its inbox at human_user priority
    inbox = reg.eventhub.list_inbox("backend", unread_only=False)
    assert len(inbox) == 1
    assert inbox[0]["priority"] == "human_user"
    assert inbox[0]["payload"]["text"] == "please add /api/users"

    # 3. Backend replies into the thread
    reg.eventhub.publish_agent_reply(
        thread_id=tid,
        agent="backend",
        text="endpoint added; tests pass",
    )

    # 4. Human (via list_messages) sees both messages in order
    messages = reg.human_console.list_messages(thread_id=tid)
    assert [m["text"] for m in messages] == ["please add /api/users", "endpoint added; tests pass"]
    assert [m["source"] for m in messages] == ["human_user", "backend"]


def test_e2e_one_human_message_to_multiple_agents(tmp_path):
    reg = HubRegistry(tmp_path, project_name="X", human_user_id="test_user")
    convo = reg.human_console.start_conversation(
        target_agents=["backend", "frontend", "database"],
        text="add a login page end-to-end",
    )
    tid = convo["thread_id"]
    for agent in ["backend", "frontend", "database"]:
        inbox = reg.eventhub.list_inbox(agent, unread_only=False)
        assert any(item["thread_id"] == tid for item in inbox), f"{agent} missing"


def test_e2e_conversation_persists_across_hub_registry_restart(tmp_path):
    reg1 = HubRegistry(tmp_path, project_name="X", human_user_id="test_user")
    convo = reg1.human_console.start_conversation(
        target_agents=["backend"], text="persistent message",
    )
    reg1.eventhub.publish_agent_reply(thread_id=convo["thread_id"], agent="backend", text="ack")
    del reg1

    reg2 = HubRegistry(tmp_path, human_user_id="test_user")
    convos = reg2.human_console.list_conversations()
    assert len(convos) == 1
    assert convos[0]["message_count"] == 2

    messages = reg2.human_console.list_messages(thread_id=convo["thread_id"])
    assert [m["text"] for m in messages] == ["persistent message", "ack"]


def test_e2e_mark_resolved_hides_from_open_list_but_keeps_history(tmp_path):
    reg = HubRegistry(tmp_path, project_name="X", human_user_id="test_user")
    convo = reg.human_console.start_conversation(target_agents=["backend"], text="done?")
    reg.eventhub.publish_agent_reply(thread_id=convo["thread_id"], agent="backend", text="yes")
    reg.human_console.mark_resolved(thread_id=convo["thread_id"])

    open_convos = reg.human_console.list_conversations(status="open")
    assert open_convos == []
    resolved = reg.human_console.list_conversations(status="resolved")
    assert len(resolved) == 1
    # History still readable
    assert len(reg.human_console.list_messages(thread_id=convo["thread_id"])) == 2


def test_e2e_orchestrator_awareness_via_subscription(tmp_path):
    reg = HubRegistry(tmp_path, project_name="X", human_user_id="test_user")
    reg.eventhub.subscribe_to_human_messages(agent="orchestrator")
    reg.human_console.start_conversation(target_agents=["backend"], text="task A")
    reg.human_console.start_conversation(target_agents=["frontend"], text="task B")
    orchestrator_inbox = reg.eventhub.list_inbox("orchestrator", unread_only=False)
    assert len(orchestrator_inbox) == 2
