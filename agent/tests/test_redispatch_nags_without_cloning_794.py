r"""#794: re-dispatch NAGS a still-failing gate check; it must not clone the task.

Measured, not assumed. Across the corpus, 114 of 151 runs contain duplicate task titles — but
that number is mostly **historical** and mostly **legitimate**, and chasing it without checking
would have built the wrong thing twice over:

  * the worst offender, `"UI does not match reference designs (visual gate, attempt 1)"` ×14, is
    ALREADY FIXED — the current title carries `round {N}; judge attempt {A}/3`, so it is unique
    per round. Those runs (r88/r99/r103) predate that. **Nearly reported a fixed bug as live.**
  * most duplicated titles end `completed` (1156) or `cancelled` (380). Re-filing a check that
    genuinely failed again is correct behaviour, not waste.

What survives both filters is one live shape. r130 holds **13** copies of `"Make business_chain
pass (blocks delivery)"`, created ~4 minutes apart — not per milestone (the `guard[name]` covers
that) but per *decline-counter re-dispatch*, which deliberately nags a still-failing check. The
last **five are simultaneously `in_progress`**.

Two concrete costs:
  * `incomplete_required_tasks` is a delivery-blocker count, and it inflates with clones of one
    problem;
  * an agent claims copy #9 while #10–13 sit unclaimed, looking like unstarted work.

The nag is kept — it exists because a declined check needs chasing. Only the duplicate row goes:
if an identical-title task is still open, re-wake the owner against THAT task. Present in 8 of the
last 22 runs, and the fix is on the shared dispatch table, so it covers every gate-level check
name, not just `business_chain_failing`.
"""
import asyncio
import inspect
import types

import pytest

from env_generator.llm_generator.multi_agent.runtime import remediation_dispatcher as rd


def _src():
    return inspect.getsource(rd)


def test_an_open_duplicate_is_reused_not_recreated():
    s = _src()
    # Anchored on the code site's own sentence, not the bare ticket number: #798's
    # helper docstring cites "#794" and appears EARLIER in the file, so `index("#794")`
    # silently moved to a docstring and this test failed against working code.
    i = s.index("re-dispatch NAGS; it must not clone the task")
    blk = s[i:s.index("_gmsg = _create_message", i)]
    assert "list_tasks()" in blk, "it has to look before it files"
    assert '("pending", "in_progress", "open")' in blk, "only an OPEN twin may suppress a file"
    assert "task = _open794" in blk


def test_the_nag_still_happens():
    """The whole point of re-dispatch is chasing a declined check — suppressing the MESSAGE would
    be a regression, not a fix."""
    # Anchored on the statement that ends the dispatch block, not a character count — the
    # fixed-width-window guard caught the first version of this line, for the ninth time this
    # session. A window that big also silently reaches into the NEXT handler.
    s = _src()
    # Anchored on the code site's own sentence, not the bare ticket number: #798's
    # helper docstring cites "#794" and appears EARLIER in the file, so `index("#794")`
    # silently moved to a docstring and this test failed against working code.
    i = s.index("re-dispatch NAGS; it must not clone the task")
    blk = s[i:s.index("target_agent_id=owner", i)]
    assert "_gmsg = _create_message" in blk, "the nag must still be sent"
    assert "re-waking" in blk


def test_a_completed_twin_does_not_suppress_a_refile():
    """1156 duplicated titles ended `completed`. A check that fails AGAIN after being fixed must
    still file — that is the correct behaviour the measurement identified."""
    s = _src()
    # Anchored on the code site's own sentence, not the bare ticket number: #798's
    # helper docstring cites "#794" and appears EARLIER in the file, so `index("#794")`
    # silently moved to a docstring and this test failed against working code.
    i = s.index("re-dispatch NAGS; it must not clone the task")
    blk = s[i:s.index("_gmsg = _create_message", i)]
    assert '"completed"' not in blk and '"cancelled"' not in blk


def test_it_falls_back_to_filing_on_any_fault():
    """A lookup failure must not swallow the task — losing a P0 is far worse than a duplicate."""
    s = _src()
    # Anchored on the code site's own sentence, not the bare ticket number: #798's
    # helper docstring cites "#794" and appears EARLIER in the file, so `index("#794")`
    # silently moved to a docstring and this test failed against working code.
    i = s.index("re-dispatch NAGS; it must not clone the task")
    blk = s[i:s.index("_gmsg = _create_message", i)]
    assert "except Exception:" in blk
    assert "best-effort: on any fault, file as before" in blk
    assert "_open794 = None" in blk


def test_the_suppression_is_announced():
    """A dispatcher that silently does nothing is indistinguishable from one with nothing to do —
    #769/#770/#790's rule, applied to my own change this time (#793's lesson)."""
    s = _src()
    assert "instead of filing a duplicate P0" in s


# --- #800: the wake message must match the path it was sent on -------------------------------

def test_the_rewake_message_does_not_say_claim():
    """#794 made re-dispatch re-wake an EXISTING task; the wake still said "Claim task X" while
    that task is typically already in_progress and already held by this very agent. An
    instruction the owner cannot follow, on the message it reads FIRST."""
    s = _src()
    i = s.index("#800")
    blk = s[i:s.index("msg_type=\"task_ready\"", i)]
    assert "_open794 is not None else" in blk, "the two paths must send different text"
    assert "STILL blocked" in blk
    assert "which you already hold" in blk


def test_the_first_dispatch_message_is_unchanged():
    """Non-regression: on a genuinely new task, "Claim" is the correct instruction."""
    s = _src()
    i = s.index("#800")
    blk = s[i:s.index("msg_type=\"task_ready\"", i)]
    assert "Claim " in blk and "and fix it NOW, then finish." in blk


def test_the_rewake_says_the_previous_work_did_not_clear_it():
    """The one fact a re-dispatch carries that a first dispatch does not."""
    s = _src()
    assert "has \"\n                         f\"not cleared it" in s or "not cleared it" in s


def test_the_measurement_travels_with_the_fix():
    """So a later reader can tell whether this is load-bearing, and can re-measure it."""
    s = " ".join(_src().replace("#", " ").split())
    assert "r130 accumulated 13 copies" in s
    assert "8 of the last 22 corpus runs" in s


def test_mapping_is_actually_imported():
    """The first cut used `Mapping` without importing it — a NameError on the release path, in a
    branch that only fires when a check has already failed twice, i.e. the worst possible place
    for one."""
    assert "Mapping" in inspect.getsource(rd).split("from typing import")[1].split("\n")[0]
    assert rd.Mapping is not None


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))


# --- #1203pg: reuse-not-clone, DRIVEN ------------------------------------------------------------
#
# 18 of the 19 assertions above read the SOURCE, and a mutation showed that none of them can see
# the decision. All three of these left every asserted string in place and went undetected:
#
#   * inverting `if _open794 is not None:`  -> a twin that EXISTS gets a clone filed anyway
#   * inverting the status filter           -> a `completed` twin suppresses the refile and an
#                                              open one does not, which is the exact behaviour
#                                              the docstring above says must NOT happen
#   * `startswith` -> `==`                  -> no open twin is ever found once titles carry the
#                                              #1202ss instance suffix, so r130's 13 clones return
#
# `RemediationDispatcher` is stateless (`__init__(orch)`), so the dispatch runs against a stub.

_BASE_794 = "Make business_chain pass (blocks delivery)"


class _Workhub:
    def __init__(self, tasks, raises=False):
        self._tasks, self._raises = tasks, raises
        self.created = []

    def list_tasks(self):
        if self._raises:
            raise RuntimeError("the hub hiccuped")
        return self._tasks

    def create_task(self, **kw):
        self.created.append(kw)
        return {"id": "new-%d" % len(self.created), "title": kw.get("title")}


def _dispatch(tasks, raises=False):
    """Run the gate-level dispatch for `business_chain_failing` and report what it did."""
    _noop = lambda *a, **k: None  # noqa: E731
    wakes = []

    class _Bus:
        async def send(self, *a, **k):
            wakes.append((a, k))
            return None

    wh = _Workhub(tasks, raises=raises)
    orch = types.SimpleNamespace(
        hubs=types.SimpleNamespace(workhub=wh, codehub=None, eventhub=None),
        _logger=types.SimpleNamespace(info=_noop, warning=_noop, error=_noop, debug=_noop),
        message_bus=_Bus(), output_dir=".", agents={}, _milestone_index=1,
        _gate_dispatch_guard={}, _gate_decline_counts={})
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(
            rd.RemediationDispatcher(orch).dispatch_gate_level_checks(["business_chain_failing"]))
    finally:
        loop.close()
    return wh.created, wakes


def _task(status, title=_BASE_794):
    return {"id": "t1", "title": title, "status": status}


def test_with_no_open_twin_it_files():
    """Non-vacuity: without this the suppression tests below would pass against a dispatcher
    that never files anything at all."""
    created, _ = _dispatch([])
    assert len(created) == 1, "the P0 was not filed"
    assert created[0]["title"].startswith(_BASE_794)


@pytest.mark.parametrize("status", ["pending", "in_progress", "open"])
def test_an_open_twin_suppresses_the_clone(status):
    created, _ = _dispatch([_task(status)])
    assert created == [], "r130's 13th clone was filed against an open %s twin" % status


@pytest.mark.parametrize("status", ["completed", "cancelled"])
def test_a_closed_twin_does_NOT_suppress_the_refile(status):
    """1156 duplicated titles ended `completed`. A check that fails AGAIN after being fixed must
    still file -- that is the correct behaviour the measurement identified, not waste."""
    created, _ = _dispatch([_task(status)])
    assert len(created) == 1, "a %s twin suppressed a legitimate refile" % status


def test_the_match_is_a_PREFIX_so_an_instanced_title_still_finds_its_twin():
    """#1202ss put the instance set in the title and kept it a PREFIX of the base so this
    lookup still matches. With an exact match the twin is invisible and the clones come back."""
    created, _ = _dispatch([_task("in_progress", _BASE_794 + " [chains: checkout, signup]")])
    assert created == [], "an instanced twin was not recognised"


def test_the_nag_is_still_sent_when_the_clone_is_suppressed():
    """The whole point of re-dispatch is chasing a declined check. Suppressing the MESSAGE
    would be a regression, not a fix -- only the duplicate ROW goes."""
    created, wakes = _dispatch([_task("in_progress")])
    assert created == []
    assert wakes, "the nag was suppressed along with the duplicate"


def test_a_lookup_fault_files_as_before():
    """Losing a P0 is far worse than a duplicate, so any fault falls back to filing."""
    created, _ = _dispatch([], raises=True)
    assert len(created) == 1, "a hub fault swallowed the P0"
