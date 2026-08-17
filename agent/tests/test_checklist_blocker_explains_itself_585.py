r"""#585: `verification_checklist_not_ready` has been patched four times (#120, #492, #511,
#566q) for one recurring symptom — the checklist blocking a run whose `build:*` checks are all
success — and every investigation restarted from zero because the gate never reported what it
saw.

Measured across the arc (runs joined against their monitor TERMINAL verdict): of the 11 runs
that ultimately FAILED, 4 carried this blocker in their last decline. Joining the four `build:*`
records' `updated_at` against the timestamp of that decline:

    r107  build:* all success by 02:30:33   blocked at 02:32:43   AFTER
    r130  build:* all success by 22:55:35   blocked at 22:56:36   AFTER
    r124 / r129 / r137                                            before -> transient, fine

So in r107 and r130 the gate blocked ~1 minute AFTER all four components were recorded
`success` on disk. The artifacts do not explain it, and no run can be re-run to find out.

This change does not guess at the cause. It makes the blocker self-describing — the component
statuses the gate actually observed, plus each record's `updated_at` — and stops the bare
`except` from swallowing a computation fault silently. Log-only: the verdict is untouched.
"""
import ast
import inspect

import pytest

from env_generator.llm_generator.multi_agent.runtime import delivery_gate as dg


def _src():
    return inspect.getsource(dg)


def test_the_module_still_parses():
    ast.parse(_src())


def test_the_blocker_now_logs_what_it_observed():
    src = _src()
    i = src.index('failed_checks.append("verification_checklist_not_ready")')
    window = src[i:i + 1200]
    assert "observed %s" in window, window[:400]
    assert "build:* " in window
    assert "logger.warning" in window


def test_the_computation_fault_is_no_longer_swallowed_silently():
    src = _src()
    i = src.index('checklist = {"checklist": {}, "all_required_passing": False')
    window = src[max(0, i - 900):i + 600]
    assert "except Exception as _cl_exc" in window, window[:300]
    assert "logger.warning" in window


def test_by_component_is_bound_before_the_try_so_the_diagnostic_survives_a_fault():
    """On the exception path the old code left `by_component` unbound; the diagnostic would
    then have died of NameError inside its own guard and printed nothing."""
    src = _src()
    i_bind = src.index("by_component: dict = {}")
    i_try = src.index("    try:", i_bind)
    i_use = src.index("(by_component or {}).items()")
    assert i_bind < i_try < i_use


def test_the_diagnostic_can_never_raise():
    """It runs on an already-failing path; a fault while building a log line must not
    escalate into a gate crash."""
    src = _src()
    i = src.index('failed_checks.append("verification_checklist_not_ready")')
    window = src[i:i + 1200]
    assert window.count("try:") >= 1 and "except Exception:" in window


def test_the_verdict_logic_is_unchanged():
    """Log-only: the blocker still fires on exactly the same condition."""
    src = _src()
    assert "if any_recorded and not checklist.get(\"ready_for_delivery\", False):" in src


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
