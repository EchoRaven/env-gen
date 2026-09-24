r"""#1202n: a declined heal states its cause when the cause CHANGES, not once per tick.

#1149 exists so that a heal which declines says why, and every cause it reports is correct —
each reads "the defect this heal exists for is not present" (`no custom_routes.py`,
`no placeholder get_current_user`, `already present`). What it does not do is notice that the
state it describes barely moves.

Measured across r22-r26: each run emits 27 to 135 copies of this line for exactly TWO distinct
cause-sets. r26 is 134 identical lines and 2 states.

Repeating an unchanged line 134 times is its own way of hiding a signal — the inverse of the
silence #1102 is about, and the same reason #1201 reports once per site. Every distinct state
is still logged, and a transition BACK to a state already seen is logged again, so nothing
that moved is lost; only the standing still is quiet.
"""

import logging
import sys
import types
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))


class _Orch:
    def __init__(self, logger):
        self._logger = logger


def _emit(orch, cause):
    """The shape of the guarded emission, exercised directly."""
    if getattr(orch, "_heal_decline_cause_1202n", None) != cause:
        orch._heal_decline_cause_1202n = cause
        orch._logger.info("#1149 backend heals declined (no-op) with cause: %s", cause)


def test_an_unchanged_cause_is_said_once(caplog):
    log = logging.getLogger("heal_1202n_a")
    orch = _Orch(log)
    with caplog.at_level(logging.INFO, logger=log.name):
        for _ in range(50):
            _emit(orch, "router_prologue=router already defined")
    assert caplog.text.count("#1149") == 1


def test_each_distinct_state_is_reported(caplog):
    log = logging.getLogger("heal_1202n_b")
    orch = _Orch(log)
    with caplog.at_level(logging.INFO, logger=log.name):
        _emit(orch, "router_prologue=router already defined")
        _emit(orch, "router_prologue=no custom_routes.py")
    assert caplog.text.count("#1149") == 2


def test_returning_to_an_earlier_state_is_reported_again(caplog):
    """A flap back is movement, and movement is the thing worth seeing."""
    log = logging.getLogger("heal_1202n_c")
    orch = _Orch(log)
    with caplog.at_level(logging.INFO, logger=log.name):
        _emit(orch, "A")
        _emit(orch, "B")
        _emit(orch, "A")
    assert caplog.text.count("#1149") == 3


def test_the_guard_is_in_the_pipeline():
    src = (THIS_DIR.parent
           / "env_generator/llm_generator/multi_agent/runtime/heal_pipeline.py"
           ).read_text(encoding="utf-8")
    at = src.index("#1149 backend heals declined")
    # Landmark, not a byte window (#943): the guard is the last `if` opened before the call.
    guard = src.rindex("if ", 0, at)
    assert "_heal_decline_cause_1202n" in src[guard:at]
