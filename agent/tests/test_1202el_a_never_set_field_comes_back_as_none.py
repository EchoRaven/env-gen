r"""#1202el: resume resurrects never-set attributes as None, and a counter then raises.

`save_gate_counters_1202ce` read every persisted field with `getattr(orch, f, None)`.
That cannot tell "the run set this to None" from "the run never touched it", and it
stored None for both. `restore_gate_counters_1202ce` then wrote that None back onto the
orchestrator -- over the value a fresh milestone had just initialised.

Caught on a live run, googlemaps-r16. Its gate_state.json holds:

    "_fwdeliver_stuck_count": null

and after the resume the log carries, four times:

    framework delivery raised (non-fatal): '>=' not supported between instances of
    'NoneType' and 'int'

which is `self._fwdeliver_stuck_count >= FWVAL_STUCK_ABORT_AFTER` (orchestrator.py:4201).
Zero occurrences in the SAME run before the resume, and zero in netflix-r44, netflix-r45
and tiktok-r96 -- the signature of a resume-only defect. That counter is an int
everywhere it is written (0, 1, or incremented via `getattr(..., 0) + 1`); it is never
legitimately None.

The fix is a sentinel rather than a None-check, because `_pages_gate_deferred_since` and
`_tu_squad_deferred_since` ARE legitimately None -- it means "not deferred" -- and
dropping those would lose real state.
"""
import json
import logging
import sys
from pathlib import Path

import pytest

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

from multi_agent.runtime.milestone_resume import (  # noqa: E402
    _MISSING_1202EL, restore_gate_counters_1202ce, save_gate_counters_1202ce,
)

KEY = "milestone:1:M1@1.0.0"


class _Orch:
    def __init__(self, tmp):
        self.output_dir = tmp


def _saved(tmp):
    """The orchestrator's gate counters live in design/milestone_gates.json.

    NOT design/visual_gate/gate_state.json -- that is the VISUAL gate's own state
    (_STATE_FIELDS_1202CE in visual_fidelity.py), a different mechanism. My first version
    of this test read that file, found the key absent, and passed vacuously.
    """
    p = tmp / "design" / "milestone_gates.json"
    assert p.is_file(), "save wrote nothing -- the test would pass on absence"
    return json.loads(p.read_text(encoding="utf-8"))


def test_a_never_set_counter_is_not_persisted_as_null(tmp_path):
    """googlemaps-r16's milestone_gates.json carried twelve nulls, among them
    `_rc_attempts`, `_tu_browser_attempts` and `_fwdeliver_grace_count` -- counters that
    are ints everywhere they are written."""
    o = _Orch(tmp_path)
    o._pages_gate_attempts = 1          # something must be set, or nothing is written
    save_gate_counters_1202ce(o, KEY)
    blob = _saved(tmp_path)
    for never_set in ("_rc_attempts", "_tu_browser_attempts", "_fwdeliver_grace_count"):
        assert never_set not in blob, f"{never_set} was resurrected as null"


def test_the_getattr_default_guard_survives_a_resume(tmp_path):
    """THE HARM, reproduced. The codebase guards these counters as

        self._rc_attempts = getattr(self, "_rc_attempts", 0) + 1

    which protects against the attribute being ABSENT. A restored None makes it PRESENT,
    so the default never applies and the guard is silently defeated."""
    o = _Orch(tmp_path)
    o._pages_gate_attempts = 1
    save_gate_counters_1202ce(o, KEY)
    o2 = _Orch(tmp_path)
    restore_gate_counters_1202ce(o2, KEY)
    o2._rc_attempts = getattr(o2, "_rc_attempts", 0) + 1     # must not raise
    assert o2._rc_attempts == 1


def test_restore_leaves_a_fresh_default_alone(tmp_path):
    """The restored None must not replace the value a fresh milestone just set."""
    _o = _Orch(tmp_path); _o._pages_gate_attempts = 1
    save_gate_counters_1202ce(_o, KEY)
    o2 = _Orch(tmp_path)
    o2._fwdeliver_stuck_count = 0          # what a fresh milestone sets
    restore_gate_counters_1202ce(o2, KEY)
    assert o2._fwdeliver_stuck_count == 0
    assert o2._fwdeliver_stuck_count >= 3 or True     # the comparison must not raise


def test_a_deliberate_none_still_round_trips(tmp_path):
    """`_pages_gate_deferred_since = None` means NOT DEFERRED -- real state, not absence."""
    o = _Orch(tmp_path)
    o._pages_gate_deferred_since = None
    o._pages_gate_attempts = 2
    save_gate_counters_1202ce(o, KEY)
    blob = _saved(tmp_path)
    assert "_pages_gate_deferred_since" in blob and blob["_pages_gate_deferred_since"] is None
    o2 = _Orch(tmp_path)
    o2._pages_gate_deferred_since = 12345.0
    restore_gate_counters_1202ce(o2, KEY)
    assert o2._pages_gate_deferred_since is None, "a stored None must overwrite"
    assert o2._pages_gate_attempts == 2


def test_a_real_value_still_round_trips(tmp_path):
    o = _Orch(tmp_path)
    o._fwdeliver_stuck_count = 4
    o._pages_gate_attempts = 1
    save_gate_counters_1202ce(o, KEY)
    o2 = _Orch(tmp_path)
    o2._fwdeliver_stuck_count = 0
    restore_gate_counters_1202ce(o2, KEY)
    assert o2._fwdeliver_stuck_count == 4


def test_the_sentinel_is_not_none(tmp_path):
    """A None sentinel would reintroduce the bug it exists to prevent."""
    assert _MISSING_1202EL is not None


def test_the_comparison_that_raised_is_reachable_again(tmp_path):
    """End to end: save empty, restore over a fresh int, run r16's comparison."""
    _o = _Orch(tmp_path); _o._pages_gate_attempts = 1
    save_gate_counters_1202ce(_o, KEY)
    o2 = _Orch(tmp_path)
    o2._fwdeliver_stuck_count = 0
    restore_gate_counters_1202ce(o2, KEY)
    assert (o2._fwdeliver_stuck_count >= 3) is False
