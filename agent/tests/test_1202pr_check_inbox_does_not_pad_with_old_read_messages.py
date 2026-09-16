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


# #1202pr: unfiltered check_inbox keeps only the most recent read previews.


def test_an_unfiltered_call_keeps_the_five_newest_read_previews():
    agent = _StubAgent([_msg(f"old{i}", read=True) for i in range(30)]
                       + [_msg("u1", read=False), _msg("u2", read=False)])
    out = CheckInboxTool(agent=agent).execute(limit=30).data
    ids = [m["id"] for m in out["messages"]]
    assert ids == ["u1", "u2"] + [f"old{i}" for i in range(25, 30)]
    assert "25 older already-read message(s) not listed" in out["info"]


def test_a_filtered_call_still_sees_every_read_message():
    agent = _StubAgent([_msg(f"old{i}", read=True) for i in range(12)])
    out = CheckInboxTool(agent=agent).execute(limit=30, search="").data
    assert len(out["messages"]) == 5          # empty search is not a filter
    out = CheckInboxTool(agent=agent).execute(limit=30, from_agent="orchestrator").data
    assert len(out["messages"]) == 12 and "older already-read" not in out["info"]


def test_few_read_messages_are_untouched():
    agent = _StubAgent([_msg(f"r{i}", read=True) for i in range(4)])
    out = CheckInboxTool(agent=agent).execute(limit=20).data
    assert [m["id"] for m in out["messages"]] == ["r0", "r1", "r2", "r3"]
    assert "older already-read" not in out["info"]
