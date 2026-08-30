"""#1171: 40% of a run's bill was unattributable.

At the real rate a run costs $425, and 30.8M of that is UNCACHED input --
$169, 40% of the bill, at 10x the cached rate. The distribution says where to
look: the median call adds only 1,297 uncached tokens, while the top 10% of
calls carry 57% of the total and one carried 220,729 (that single call cost
$1.21). So the money is in a minority of calls with a large payload, and the
payload is a TOOL RESULT -- the one thing no log in the corpus records.

Two candidate causes were ruled out by measurement first, not assumed:
  * the hub pulse is `messages.append`, i.e. at the END -- cache-friendly, not
    a prefix break;
  * calls right after a condensation hit 90.7% against an 88.8% baseline, so
    rewriting the message list is not what costs the hits.
"""
import json
from pathlib import Path

import utils.llm as L
from env_generator.llm_generator.multi_agent.runtime import run_budget as rb
from env_generator.llm_generator.multi_agent.agents.runtime.step_pipeline import tooling


def setup_function(_):
    L._TOOL_RESULT_BYTES.clear()


def test_it_accumulates_per_tool():
    for t, n in (("read", 220_000), ("read", 5_000), ("grep", 1_200)):
        L.record_tool_result_bytes_1171(t, n)
    out = L.tool_result_bytes()
    assert out["read"] == {"calls": 2, "bytes": 225_000, "max": 220_000}
    assert out["grep"]["calls"] == 1


def test_the_biggest_contributor_sorts_first():
    """The question is "which tool put that much in the context", so the head of
    the map has to be the answer."""
    L.record_tool_result_bytes_1171("small", 10)
    L.record_tool_result_bytes_1171("huge", 999_999)
    assert list(L.tool_result_bytes())[0] == "huge"


def test_max_is_kept_not_just_the_total():
    """A tool called 600 times at 300 bytes and one called once at 220K are very
    different problems; the total alone conflates them."""
    for _ in range(600):
        L.record_tool_result_bytes_1171("chatty", 300)
    L.record_tool_result_bytes_1171("whale", 220_000)
    out = L.tool_result_bytes()
    assert out["chatty"]["max"] == 300 and out["whale"]["max"] == 220_000


def test_junk_can_never_raise():
    L.record_tool_result_bytes_1171(None, "x")
    L.record_tool_result_bytes_1171(object(), None)
    assert isinstance(L.tool_result_bytes(), dict)


def test_it_is_recorded_where_every_result_passes():
    """One choke point -- the append into the message list -- or the count is
    partial and therefore misleading."""
    src = Path(tooling.__file__).read_text(encoding="utf-8")
    i = src.index("record_tool_result_bytes_1171(")
    j = src.index("messages.append(Message.tool(result_str, tool_call_id))")
    assert i < j, "must count BEFORE the result enters the context"
    assert src.count("record_tool_result_bytes_1171(") == 1


def test_the_counter_cannot_break_a_tool_call():
    src = Path(tooling.__file__).read_text(encoding="utf-8")
    i = src.index("record_tool_result_bytes_1171(")
    seg = src[src.rindex("try:", 0, i):src.index("messages.append(", i)]
    assert "except Exception" in seg


def test_it_rides_out_with_the_spend_record():
    src = Path(rb.__file__).read_text(encoding="utf-8")
    assert "tool_result_bytes" in src
