"""#302 — check_inbox context reduction: READ messages return a PREVIEW (+ id),
UNREAD messages return FULL content (preserves #274). Full body of a read
message is fetchable on demand via search_messages / eventhub_get_thread.

r82: check_inbox re-dumped ~350KB of already-read bodies per inbox every call
(meeting_closed 94KB, task_completed ×126 = 178KB, etc.), the single biggest
context/token sink. All were `read` in steady state.
"""
import sys
from pathlib import Path
THIS = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS.parent / "env_generator" / "llm_generator"))
from tools.communication_tools import CheckInboxTool  # noqa: E402


class _StubAgent:
    agent_id = "orchestrator"

    def __init__(self, msgs):
        self._subscription_inbox = list(msgs)
        self._hubs = None

    def get_inbox_messages(self, limit=999, clear=False):
        return list(self._subscription_inbox)


def _msg(mid, content, read):
    return {"id": mid, "from": "orchestrator", "type": "task_completed",
            "content": content, "tags": [], "priority": "normal",
            "persist": True, "timestamp": "t", "read": read}


def _run(msgs, **kw):
    tool = CheckInboxTool(agent=_StubAgent(msgs))
    return tool.execute(clear=False, **kw).data["messages"]


def test_unread_long_message_is_full():
    big = "U" * 5000
    out = _run([_msg("m1", big, read=False)])
    assert len(out) == 1
    assert out[0]["content"] == big          # #274 preserved: unread never clipped
    assert not out[0].get("preview")


def test_read_long_message_is_previewed():
    big = "R" * 5000
    out = _run([_msg("m1", big, read=True)])
    m = out[0]
    assert m.get("preview") is True
    assert len(m["content"]) < 5000          # previewed, not full
    assert m["id"] == "m1"                    # id kept so full body is fetchable
    assert "R" in m["content"]               # shows a real snippet


def test_read_short_message_stays_full():
    small = "short read note"
    out = _run([_msg("m1", small, read=True)])
    assert out[0]["content"] == small        # nothing to save on a small body
    assert not out[0].get("preview")


def test_mixed_inbox_only_read_previewed():
    out = _run([_msg("u", "N"*4000, read=False), _msg("r", "O"*4000, read=True)])
    by = {m["id"]: m for m in out}
    assert by["u"]["content"] == "N"*4000 and not by["u"].get("preview")
    assert by["r"].get("preview") is True and len(by["r"]["content"]) < 4000


def test_preview_bounded_length():
    out = _run([_msg("m1", "X"*100000, read=True)])
    assert len(out[0]["content"]) < 600      # bounded preview regardless of body size
