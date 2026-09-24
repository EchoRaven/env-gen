r"""#1202dv: a resume silently refills the framework-validation and deliver budgets.

`#1202ce` established the right shape for milestone-scoped orchestrator state: save it under
the milestone key, and restore it only when a resume RE-ENTERS that same milestone, so no run
inherits counters that are not its own. It persists nine fields — the page-build and squad
deferral clocks and their attempt counts.

The milestone-boundary reset block in `orchestrator.py` resets **sixteen more** of interest, and the
persisted set is disjoint from them. Every one is a BOUNDED budget:

    _framework_validation_attempts    the "attempt N/6" ceiling
    _fwval_stuck_count                the stuck-loop breaker
    _fwdeliver_stuck_count            the deliver-side breaker
    _fwdeliver_grace_count            #230's per-milestone grace allowance
    _fwval_abort_grace_used           the abort grace
    ...and the signatures/keys those breakers compare against to decide "no progress"

So a resume mid-milestone hands the run a fresh six validation attempts, a fresh stuck
breaker, and fresh graces. The block's own comment says why that is wrong when the milestone
has not changed: it resets them per MILESTONE because "a new milestone's failures are
genuinely new work, not a continuation of the prior stall". Re-entering the same milestone is
the opposite case — the stall IS a continuation, and the breaker that exists to end it starts
over instead.

r44 went through three processes and each one began at `Framework validation attempt 1/6`.
It never exhausted them, so nothing broke; a run that wedges is exactly the run that would.

Two of them are sets (`_fwval_failure_set` is a frozenset, `_fwdeliver_prev_failed` a set).
`json.dumps(..., default=str)` turns a set into the STRING "{'a', 'b'}", which restores as a
string and silently breaks every `==`/`in` the breakers do against it — so the round trip has
to be type-aware, not just JSON-safe.

A seventeenth field, `_silent_lane_nudges`, was in the first version of this list and was
removed after a real mid-milestone resume of netflix-r45 showed it could not survive — see
the last test.
"""
import json
import sys
from pathlib import Path

import pytest

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

from multi_agent.runtime.milestone_resume import (  # noqa: E402
    _FWGATE_FIELDS_1202DV,
    restore_gate_counters_1202ce,
    save_gate_counters_1202ce,
)


class _Orch:
    def __init__(self, output_dir):
        self.output_dir = output_dir
        # the nine #1202ce already covered
        self._pages_gate_attempts = 3
        self._pages_gate_deferred_since = 111.0
        self._tu_squad_passed = True
        self._tu_squad_deferred_since = 222.0
        self._tu_squad_attempts = 2
        self._rc_deferred_since = 333.0
        self._rc_attempts = 1
        self._tu_browser_deferred_since = 444.0
        self._tu_browser_attempts = 4
        # the sixteen this ticket adds
        self._project_delivered = False
        self._framework_validation_attempts = 5
        self._fwval_last_attempt_ts = 1000.5
        self._fwval_healed_sig = "sig-a"
        self._fwval_failure_set = frozenset({"docker_up", "business_chain"})
        self._fwval_stuck_count = 2
        self._fwval_stuck_blocker = "docker_up"
        self._fwdeliver_stuck_count = 3
        self._fwdeliver_stuck_key = "k1"
        self._fwdeliver_first_decline_ts = 900.25
        self._fwdeliver_grace_count = 1
        self._fwdeliver_prev_failed = {"ui_evidence"}
        self._fwdeliver_last_shrink_ts = 800.0
        self._fwval_abort_grace_used = 1
        self._fwval_abort_deliver_reason = "converging"
        self._fwval_abort_progress_sig = "psig"
        self._silent_lane_nudges = {"backend": 3, "frontend": 1}


KEY = "milestone:1:M1@1.0.0"


def test_every_stuck_budget_is_covered(tmp_path):
    """The list is the milestone-reset block; a field missing here refills on resume."""
    for f in ("_framework_validation_attempts", "_fwval_stuck_count",
              "_fwdeliver_stuck_count", "_fwdeliver_grace_count",
              "_fwval_abort_grace_used"):
        assert f in _FWGATE_FIELDS_1202DV, f


def test_re_entering_the_same_milestone_keeps_the_budgets(tmp_path):
    save_gate_counters_1202ce(_Orch(tmp_path), KEY)
    fresh = _Orch(tmp_path)
    for f in _FWGATE_FIELDS_1202DV:          # simulate a new process's defaults
        setattr(fresh, f, 0 if isinstance(getattr(fresh, f), int) else None)
    assert restore_gate_counters_1202ce(fresh, KEY) is True
    assert fresh._framework_validation_attempts == 5
    assert fresh._fwval_stuck_count == 2
    assert fresh._fwdeliver_grace_count == 1
    assert fresh._fwval_abort_grace_used == 1


def test_the_sets_survive_as_sets(tmp_path):
    """`default=str` would restore "{'a', 'b'}" and break every comparison silently."""
    save_gate_counters_1202ce(_Orch(tmp_path), KEY)
    fresh = _Orch(tmp_path)
    fresh._fwval_failure_set = None
    fresh._fwdeliver_prev_failed = None
    restore_gate_counters_1202ce(fresh, KEY)
    assert fresh._fwval_failure_set == frozenset({"docker_up", "business_chain"})
    assert isinstance(fresh._fwval_failure_set, frozenset)
    assert fresh._fwdeliver_prev_failed == {"ui_evidence"}
    assert isinstance(fresh._fwdeliver_prev_failed, set)


def test_a_different_milestone_restores_nothing(tmp_path):
    """#1202ce's invariant: no path inherits state that is not its own."""
    save_gate_counters_1202ce(_Orch(tmp_path), KEY)
    fresh = _Orch(tmp_path)
    fresh._framework_validation_attempts = 0
    assert restore_gate_counters_1202ce(fresh, "milestone:2:M2@1.0.0") is False
    assert fresh._framework_validation_attempts == 0


def test_no_saved_state_restores_nothing(tmp_path):
    fresh = _Orch(tmp_path)
    assert restore_gate_counters_1202ce(fresh, KEY) is False


def test_a_corrupt_file_does_not_raise(tmp_path):
    p = Path(tmp_path) / "design" / "milestone_gates.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{not json", encoding="utf-8")
    assert restore_gate_counters_1202ce(_Orch(tmp_path), KEY) is False


def test_the_nine_1202ce_already_covered_still_round_trip(tmp_path):
    save_gate_counters_1202ce(_Orch(tmp_path), KEY)
    fresh = _Orch(tmp_path)
    fresh._pages_gate_attempts = 0
    fresh._tu_squad_attempts = 0
    restore_gate_counters_1202ce(fresh, KEY)
    assert fresh._pages_gate_attempts == 3
    assert fresh._tu_squad_attempts == 2


def test_the_saved_blob_is_json_and_carries_the_milestone(tmp_path):
    save_gate_counters_1202ce(_Orch(tmp_path), KEY)
    blob = json.loads((Path(tmp_path) / "design" / "milestone_gates.json").read_text())
    assert blob["milestone"] == KEY
    assert sorted(blob["_fwval_failure_set"]) == ["business_chain", "docker_up"]


def test_silent_lane_nudges_is_deliberately_not_persisted():
    """Found by killing netflix-r45 mid-milestone and resuming it.

    8 of 9 non-default fields survived; `_silent_lane_nudges` came back `{}`. Not a restore
    failure — `run()` resets it at the implementation dispatch, ~400 lines after the milestone
    entry where the restore happens, and orchestrator's own note says "init/reset by run()".
    A resume re-spawns the lanes, so the "how long has this lane been silent" ladder restarts
    by design. Persisting it stored a value that could never survive: a dead field.
    """
    assert "_silent_lane_nudges" not in _FWGATE_FIELDS_1202DV
