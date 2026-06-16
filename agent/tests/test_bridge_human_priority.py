import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

import pytest
from unittest.mock import MagicMock
from multi_agent.runtime.eventhub import EventHub
from multi_agent.runtime.hubs.eventhub.bridge import MessageBusBridge
from utils.message import MessagePriority


def test_bridge_maps_human_user_priority_to_urgent(tmp_path):
    """A human_user EventHub event must arrive at agents as URGENT MessagePriority."""
    eh = EventHub(tmp_path)
    bus = MagicMock()
    bridge = MessageBusBridge(bus, eh)

    event = {
        "id": "evt_test",
        "source_hub": "human_user",
        "event_type": "human_message",
        "priority": "human_user",
        "payload": {"text": "hi", "from_user": "haibotong"},
        "thread_id": "thread_test",
        "recipients": ["backend"],
    }

    msg = bridge._to_base_message(event, "backend")
    assert msg.header.priority == MessagePriority.URGENT, (
        "human_user EventHub events must map to MessagePriority.URGENT so they "
        "trigger _check_and_handle_urgent"
    )


def test_bridge_critical_still_maps_to_urgent(tmp_path):
    """Sanity: pre-existing `critical` -> URGENT still holds."""
    eh = EventHub(tmp_path)
    bridge = MessageBusBridge(MagicMock(), eh)
    event = {"id": "x", "source_hub": "h", "event_type": "y", "priority": "critical", "payload": {}, "thread_id": "t", "recipients": ["a"]}
    msg = bridge._to_base_message(event, "a")
    assert msg.header.priority == MessagePriority.URGENT


def test_bridge_normal_still_maps_to_normal(tmp_path):
    """Sanity: pre-existing `normal` -> NORMAL still holds."""
    eh = EventHub(tmp_path)
    bridge = MessageBusBridge(MagicMock(), eh)
    event = {"id": "x", "source_hub": "h", "event_type": "y", "priority": "normal", "payload": {}, "thread_id": "t", "recipients": ["a"]}
    msg = bridge._to_base_message(event, "a")
    assert msg.header.priority == MessagePriority.NORMAL
