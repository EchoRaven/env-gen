"""#1202ob: check_inbox returns UNREAD messages before already-read ones.

tiktok-r126 ab2: the verifier called `check_inbox(limit=20)` over an inbox of 205-258 messages. The
list is in-memory messages (oldest first, and `persist` ones are never cleared) followed by durable
events, then cut to `limit` — so from 15:30 to 15:51 every call led with the same already-read
task_ready (`5bdeb13e…`) and a newer message past position 20 never came back.
"""
import sys
from pathlib import Path

THIS = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS.parent / "env_generator" / "llm_generator"))
from tools.communication_tools import CheckInboxTool  # noqa: E402


class _StubAgent:
    agent_id = "verifier"

    def __init__(self, msgs):
        self._subscription_inbox = list(msgs)
        self._hubs = None

    def get_inbox_messages(self, limit=999, clear=False):
        return list(self._subscription_inbox)


def _msg(mid, read, persist=True):
    return {"id": mid, "from": "orchestrator", "type": "task_ready", "content": f"body {mid}",
            "tags": [], "priority": "normal", "persist": persist, "timestamp": "t", "read": read}


def test_r126_a_new_message_behind_twenty_read_ones_is_returned():
    agent = _StubAgent([_msg(f"old{i}", read=True) for i in range(25)] + [_msg("new", read=False)])
    out = CheckInboxTool(agent=agent).execute(limit=20).data
    ids = [m["id"] for m in out["messages"]]
    assert ids[0] == "new"
    assert len(ids) == 20 and ids[1:] == [f"old{i}" for i in range(19)]


def test_unread_that_do_not_fit_are_counted_and_arrive_on_the_next_call():
    agent = _StubAgent([_msg(f"u{i}", read=False) for i in range(5)])
    first = CheckInboxTool(agent=agent).execute(limit=3).data
    assert [m["id"] for m in first["messages"]] == ["u0", "u1", "u2"]
    assert "2 more UNREAD" in first["info"]
    second = CheckInboxTool(agent=agent).execute(limit=3).data
    assert [m["id"] for m in second["messages"]][:2] == ["u3", "u4"]
    assert "UNREAD" not in second["info"]


def test_an_all_read_inbox_keeps_its_order():
    agent = _StubAgent([_msg(f"r{i}", read=True) for i in range(4)])
    out = CheckInboxTool(agent=agent).execute(limit=10).data
    assert [m["id"] for m in out["messages"]] == ["r0", "r1", "r2", "r3"]
