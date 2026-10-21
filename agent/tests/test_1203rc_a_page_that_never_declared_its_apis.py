"""#1203rc -- the omission note misses the case the gate actually blocks on.

`#1203b0` tells a lane that a re-registration omitting `apis_used` changed nothing, and
`#1203p2` counts those omissions so the churn can be attributed. Both sit inside `if _kept:`,
so they speak only when a PREVIOUS non-empty `apis_used` existed to preserve -- which their
own sentence admits: "the existing %d entry(ies) were KEPT".

A page that has NEVER declared its APIs has nothing to keep. `_kept` is empty, the lane is
told nothing at all -- no note in the tool result, no countable line -- and
`deliverability_page_apis_understated` keeps failing.

netflix-local-r46 is that case end to end, and it is what FALSIFIED #1203p2's own
pre-registered criterion in `scripts/verify_1018.py`:

    registryhub_register_ui_page calls           320
    ...of which named `apis_used`                  0
    page_apis_understated failures                 3
    #1203p2 lines emitted                          0

The logged signature is literally `registryhub_register_ui_page(name,path,route,component`
(88 of them). Corpus-wide the recorder has emitted 0 lines in 455 logs -- and NOT because the
channel is broken: `tools.*` INFO reaches 253 run logs and `hub_tools` appears in 57. The
branch is simply unreachable in a run where no page ever declared an API.

The class is resolved by tool NAME, following #1203b0's own note: the class is
`WorkHubUpdatePageTool` while the name is `registryhub_register_ui_page`, and guessing the
class cost that ticket a red run.
"""
import asyncio
import os
import sys
import types

import pytest

# Same path setup as #1203b0's test: the tool package lives under
# `agent/env_generator/llm_generator`, which is not on the path by default.
_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

import tools.hub_tools as HT  # noqa: E402

_TOOL = next(o for o in vars(HT).values()
             if getattr(o, "NAME", "") == "registryhub_register_ui_page")


def _tool(existing=None):
    """The tool with a workhub stand-in whose stored record is `existing`.

    `existing` is what `update_ui_page` hands back -- i.e. the record as it stands AFTER the
    merge, which is where `_kept` is read from. None means a page with nothing recorded."""
    seen = {}

    class _WH:
        def update_ui_page(self, name, data, agent=""):
            seen["name"] = name
            seen["data"] = dict(data)
            rec = {"id": name, "name": name, **{k: v for k, v in data.items()}}
            if existing:
                rec.update(existing)
            return rec

    t = _TOOL.__new__(_TOOL)
    t._hubs = types.SimpleNamespace(workhub=_WH())
    t._agent_id = "frontend"
    return t, seen


def _run(t, **kw):
    res = asyncio.run(t._run(**kw))
    return res.data if hasattr(res, "data") else res


def _clear_counters():
    HT._APIS_UNCHANGED_SEEN_1203P2.clear()


# ----------------------------------------------------------------- the defect
def test_a_page_with_nothing_recorded_is_told_so():
    """★ r46's case: 320 calls, none naming `apis_used`, and the lane heard nothing."""
    _clear_counters()
    t, _seen = _tool(existing=None)
    data = _run(t, name="landing_page", route="/", component="LandingPage")
    assert "_apis_used_still_empty_1203rc" in data, sorted(data)
    msg = data["_apis_used_still_empty_1203rc"]
    assert "NONE recorded" in msg
    assert "page_apis_understated" in msg, "the lane must be told WHICH blocker this is"


def test_the_message_says_the_call_changed_nothing():
    """#983: naming the field is not enough -- say that this call cannot clear the blocker."""
    _clear_counters()
    t, _seen = _tool(existing=None)
    msg = _run(t, name="p", route="/p", component="P")["_apis_used_still_empty_1203rc"]
    assert "changed nothing" in msg
    assert "pass the full list" in msg


# ------------------------------------------------- what must NOT change
def test_the_existing_kept_note_still_wins_when_there_is_something_to_keep():
    """THE COUNTER-PROOF. With a previous non-empty list, #1203b0's note is the right one and
    the new branch must stay silent -- otherwise this patch would just relabel that case."""
    _clear_counters()
    t, _seen = _tool(existing={"apis_used": ["GET /api/titles"]})
    data = _run(t, name="browse", route="/browse", component="BrowsePage")
    assert "_apis_used_unchanged_1203b0" in data, sorted(data)
    assert "_apis_used_still_empty_1203rc" not in data, (
        "the new branch fired on a page that HAD a list to keep")


def test_passing_apis_used_produces_neither_note():
    """A lane that does the right thing must not be nagged by either channel."""
    _clear_counters()
    t, seen = _tool(existing=None)
    data = _run(t, name="feed", apis_used=["GET /api/feed"])
    assert "_apis_used_still_empty_1203rc" not in data, sorted(data)
    assert "_apis_used_unchanged_1203b0" not in data, sorted(data)
    assert seen["data"].get("apis_used") == ["GET /api/feed"]


def test_an_explicit_empty_list_is_not_an_omission():
    """`apis_used=[]` is a page SAYING it calls nothing (#1203b0 pinned that distinction).
    It is not the same as never passing the field, so neither note applies."""
    _clear_counters()
    t, _seen = _tool(existing=None)
    data = _run(t, name="static", apis_used=[])
    assert "_apis_used_still_empty_1203rc" not in data, sorted(data)


# ------------------------------------------------------------------- the dedup
def test_every_repeat_is_its_own_countable_line(caplog):
    """One line PER OMISSION, carrying the repeat ordinal -- which is the attribution the
    ticket exists to get, not a volume reduction.

    Stated precisely because the first version of this test was named "deduped per page" and
    the claim was wrong: `state_changed_1202ad` suppresses a repeat only when the VALUE it is
    given stops changing, and the ordinal increments on every call, so every call is a change
    and nothing is suppressed. r46's 320 omissions would produce 320 lines -- they would not
    be identical (each carries its own ordinal), and the guard would not collapse them.

    That is the same choice #1203p2 made for the same event class, and its comment says so in
    #1202ad's words ("a count that moves is a change"). What the guard really buys here is
    keying PER PAGE, so two pages cannot silence each other -- which the next test drives."""
    _clear_counters()
    import logging
    caplog.set_level(logging.INFO)
    t, _seen = _tool(existing=None)
    for _ in range(3):
        _run(t, name="same_page", route="/s", component="S")
    lines = [r for r in caplog.records if "#1203rc" in str(r.getMessage())]
    assert lines, "the countable line was never emitted"
    assert len(lines) == 3, (
        "expected one line per repeat (the ordinal moves, so each is a change): %d"
        % len(lines))
    assert "1st" in str(lines[0].getMessage())
    assert "2nd" in str(lines[1].getMessage())


def test_two_pages_do_not_silence_each_other(caplog):
    """The #1203p2 comment's own reason for keying per page."""
    _clear_counters()
    import logging
    caplog.set_level(logging.INFO)
    t, _seen = _tool(existing=None)
    _run(t, name="page_a", route="/a", component="A")
    _run(t, name="page_b", route="/b", component="B")
    msgs = [str(r.getMessage()) for r in caplog.records if "#1203rc" in str(r.getMessage())]
    assert any("page_a" in m for m in msgs), msgs
    assert any("page_b" in m for m in msgs), msgs
