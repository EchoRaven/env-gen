"""#1191 — the same hub snapshot was carried through the whole conversation, over and over.

`_mask_old_observations` only trims once the history EXCEEDS the working budget (313,600
chars); below it, it returns the messages untouched. netflix-r22's median request was 195K
chars — under the budget — so nothing was trimmed and every repeated tool result rode along
in full on every later call. Measured over that run:

    313x  workhub_list_tasks status=in_progress
    218x  workhub_list_tasks status=pending
    117x  registryhub_get_endpoint GET /api/titles
    611 of 691 workhub_list_tasks calls were three identical queries

and a lane's conversation reaches ~1,485 messages, so one insertion is re-sent 700-950
times. #1171 attributes 23% of all tool bytes to that single tool.

When the answer is byte-identical to one already in the SAME conversation, the lane has read
it verbatim already. It gets a pointer instead. The saving is counted rather than estimated.
"""
import re
from pathlib import Path

import pytest

from env_generator.llm_generator.multi_agent.agents.runtime.step_pipeline import tooling as T
import utils.llm as L


class _M:
    def __init__(self, role, content):
        self.role, self.content = role, content


BIG = "x" * 4000


@pytest.fixture(autouse=True)
def clean():
    L._DEDUP_SAVED_1191.update(calls=0, bytes=0)
    yield
    L._DEDUP_SAVED_1191.update(calls=0, bytes=0)


def test_it_finds_an_identical_earlier_tool_message():
    msgs = [_M("system", "s"), _M("tool", BIG), _M("assistant", "a")]
    assert T._identical_tool_msg_1191(msgs, BIG) == 1


def test_a_different_body_is_not_matched():
    msgs = [_M("tool", BIG)]
    assert T._identical_tool_msg_1191(msgs, BIG + "!") is None
    assert T._identical_tool_msg_1191(msgs, "y" * 4000) is None


def test_only_tool_messages_count():
    """A user/assistant message that happens to repeat the text is not a tool result the
    model can be pointed at as one."""
    msgs = [_M("user", BIG), _M("assistant", BIG)]
    assert T._identical_tool_msg_1191(msgs, BIG) is None


def test_it_scans_the_conversation_not_a_cache():
    """★ The safety property: a pointer must name a message the model can still see. After
    masking or condensing drops the old copy, the body must be delivered in full again."""
    msgs = [_M("tool", BIG)]
    assert T._identical_tool_msg_1191(msgs, BIG) == 0
    msgs[0].content = "…masked…"                       # what masking would leave
    assert T._identical_tool_msg_1191(msgs, BIG) is None


def test_the_allow_list_is_snapshot_queries_only():
    """#274 is a standing user directive that inbox bodies are never clipped, and a lane
    re-reading a file is usually verifying its own edit — neither may be deduped."""
    assert "check_inbox" not in T._DEDUP_TOOLS_1191
    assert "read" not in T._DEDUP_TOOLS_1191
    assert {"workhub_list_tasks", "registryhub_get_endpoint"} <= T._DEDUP_TOOLS_1191


def test_small_results_are_left_alone():
    assert T._DEDUP_MIN_BYTES_1191 >= 500, "a pointer must be smaller than what it replaces"


def test_the_saving_is_counted():
    L.record_dedup_saved_1191("workhub_list_tasks", 3800)
    L.record_dedup_saved_1191("workhub_list_tasks", 3800)
    assert L.dedup_saved_1191() == {"calls": 2, "bytes": 7600}


def test_the_pointer_says_what_to_do_next():
    """A repeat that keeps coming back means the lane is polling state that is not moving —
    worth saying, because that is the behaviour the 611 identical calls describe."""
    import inspect
    src = inspect.getsource(T)
    # Landmark, not a byte count — #943's ratchet, tenth sighting in this session.
    i = src.index("[#1191] byte-identical")
    msg = src[i:src.index("record_dedup_saved_1191", i)]
    # Join adjacent string literals before asserting: the message is written across several
    # source lines, so a phrase can straddle `" ... "\n  " ... "` and a raw `in` check on the
    # source then fails on text that is perfectly present at runtime.
    joined = re.sub(r'"\s*\n\s*"', "", msg)
    assert "not repeated" in joined and "Read it in full there" in joined
    assert "detect a CHANGE" in joined


def _tool_description(name):
    """The DESCRIPTION the tool itself declares, from wherever it is defined."""
    import glob
    import re
    root = Path(T.__file__).parents[4] / "tools"
    for f in glob.glob(str(root / "**" / "*.py"), recursive=True):
        src = Path(f).read_text(encoding="utf-8", errors="replace")
        i = src.find('NAME = "%s"' % name)
        if i < 0:
            continue
        j = src.find("DESCRIPTION", i)
        if j < 0:
            continue
        # Cut at the next landmark, not at a byte count — #943's ratchet, and it caught
        # this very line on the eleventh sighting in this session.
        end = min((k for k in (src.find("PARAMETERS", j), src.find("\n    def ", j),
                               src.find("NAME = ", j)) if k > j), default=len(src))
        m = re.search(r'"([^"]{4,})"', src[j:end])
        return m.group(1) if m else ""
    return None


def test_every_entry_is_a_tool_that_exists():
    """★ `registryhub_list_chains` was in the first draft and does not exist. A name that can
    never match is dead configuration -- the class this session spent its time removing."""
    for name in sorted(T._DEDUP_TOOLS_1191):
        assert _tool_description(name) is not None, "%s is not a real tool" % name


def test_no_entry_is_a_write_tool():
    """★ `workhub_task` was in the first draft: "Create, claim, claim_all, complete, fail, or
    cancel a WorkHub task" -- 459 calls in r22. Deduping the echo of two identical creates or
    claims would read to the lane as "nothing happened"."""
    WRITE = ("create", "update", "delete", "write", "register", "claim", "complete",
             "cancel", "fail", "assign", "submit", "record")
    READ = ("list", "get", "read", "one-line", "evidence", "scan")
    for name in sorted(T._DEDUP_TOOLS_1191):
        desc = (_tool_description(name) or "").strip().lower()
        assert not desc.startswith(WRITE), "%s looks like a write: %s" % (name, desc[:70])
        assert desc.startswith(READ), "%s: %s" % (name, desc[:70])


def test_a_dangling_pointer_still_carries_the_head_of_the_body():
    """Masking runs at SEND time, after the dedup decision, so an earlier copy can be trimmed
    after a pointer to it was emitted. The prefix keeps that case from being a total loss."""
    import inspect
    src = inspect.getsource(T)
    i = src.index("_head1191 = ")
    assert "result_str[:280]" in src[i:src.index("_emit1191 = (", i)]
    assert "It begins:" in src
