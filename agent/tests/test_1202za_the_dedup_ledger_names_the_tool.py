r"""#1202za: the dedup ledger keeps WHICH tool repeated itself, not only how much it saved.

`record_dedup_saved_1191(tool, saved)` has always taken the tool name and always thrown it
away, so the one question its number invites — which tool is being polled for a state that is
not moving — could not be answered from the run record.

The same call site already tells the AGENT the useful thing: "if you keep seeing this line,
the state you are waiting on is not moving and polling it again will not move it." The
ledger kept only a total. r140 recorded 13 deduplicated results worth 105,397 bytes and
could not say whether that was one tool thirteen times or thirteen tools once — and those
two readings call for opposite responses.

★ The split is capped at 8 tools WITH a `_capped_1202za` entry, because a ledger that keeps
a head and does not say so is exactly the defect #1202z7 and #1202z8 had to go and fix in
four other places today. A new one shipping with the same hole would be absurd.
"""
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

import utils.llm as LL  # noqa: E402


def _reset():
    LL._DEDUP_SAVED_1191.update({"calls": 0, "bytes": 0})
    LL._DEDUP_BY_TOOL_1202ZA.clear()


def test_the_total_is_unchanged():
    """Additive: every field a reader already relies on keeps its meaning."""
    _reset()
    LL.record_dedup_saved_1191("check_inbox", 100)
    LL.record_dedup_saved_1191("workhub_list_tasks", 250)
    d = LL.dedup_saved_1191()
    assert d["calls"] == 2 and d["bytes"] == 350


def test_the_tool_is_kept():
    _reset()
    LL.record_dedup_saved_1191("check_inbox", 100)
    LL.record_dedup_saved_1191("check_inbox", 40)
    d = LL.dedup_saved_1191()["by_tool_1202za"]
    assert d["check_inbox"] == {"calls": 2, "bytes": 140}, d


def test_one_tool_thirteen_times_reads_differently_from_thirteen_tools_once():
    """★ The whole point. r140's `13 calls / 105397 bytes` is compatible with both, and they
    call for opposite responses — fix one polling loop, or accept ordinary repetition."""
    _reset()
    for _ in range(13):
        LL.record_dedup_saved_1191("run_validation", 8000)
    a = LL.dedup_saved_1191()
    _reset()
    for i in range(13):
        LL.record_dedup_saved_1191("tool%02d" % i, 8000)
    b = LL.dedup_saved_1191()
    assert a["calls"] == b["calls"] and a["bytes"] == b["bytes"]
    assert a["by_tool_1202za"] != b["by_tool_1202za"]
    assert len(a["by_tool_1202za"]) == 1


def test_the_split_is_ordered_by_bytes():
    """★ Names chosen so alphabetical order CONTRADICTS byte order. The first version used
    "small"/"large", where `large` sorts first either way — it passed with the ordering
    replaced by a plain key sort, which is a test proving nothing."""
    _reset()
    LL.record_dedup_saved_1191("aaa_tiny", 10)
    LL.record_dedup_saved_1191("zzz_huge", 9000)
    keys = list(LL.dedup_saved_1191()["by_tool_1202za"])
    assert keys[0] == "zzz_huge", keys


def test_the_cap_says_what_it_cut():
    """★ #1202z7/#1202z8's rule, applied to the ledger I am adding rather than discovered in
    it a month later."""
    _reset()
    # ascending names, DESCENDING bytes — so a cap applied to the wrong order keeps the
    # wrong eight and the arithmetic assertion below catches it.
    for i in range(12):
        LL.record_dedup_saved_1191("tool%02d" % i, 1000 * (i + 1))
    d = LL.dedup_saved_1191()["by_tool_1202za"]
    assert "_capped_1202za" in d, sorted(d)
    assert d["_capped_1202za"]["dropped"] == 4, d["_capped_1202za"]
    kept = {k: v for k, v in d.items() if k != "_capped_1202za"}
    assert sum(v["bytes"] for v in kept.values()) + d["_capped_1202za"]["bytes"] == \
        LL.dedup_saved_1191()["bytes"]


def test_eight_tools_carry_no_cap_entry():
    _reset()
    for i in range(8):
        LL.record_dedup_saved_1191("tool%02d" % i, 100)
    assert "_capped_1202za" not in LL.dedup_saved_1191()["by_tool_1202za"]


def test_an_unnamed_tool_does_not_lose_the_record():
    """Accounting must never be the reason a record is lost (#792's rule)."""
    _reset()
    LL.record_dedup_saved_1191(None, 500)
    d = LL.dedup_saved_1191()
    assert d["bytes"] == 500
    assert "?" in d["by_tool_1202za"], d["by_tool_1202za"]


def test_a_negative_saving_is_floored_not_subtracted():
    """The existing `max(0, ...)` contract, now also per tool — a mis-sized emit must not
    make another tool's total smaller."""
    _reset()
    LL.record_dedup_saved_1191("t", -50)
    d = LL.dedup_saved_1191()
    assert d["bytes"] == 0 and d["by_tool_1202za"]["t"]["bytes"] == 0
