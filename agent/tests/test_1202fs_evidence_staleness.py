"""#1202fs -- #401's staleness rule, applied to the OTHER reader of the same evidence.

#401 drops a FAILED ui_flow record older than the newest api_smoke (when the current build
was last validated end to end), because "a flow the frontend has since FIXED keeps its old
FAILURE record for the rest of the run, false-failing the delivery gate". That argument is
about the evidence, not about one consumer -- but only flow_coverage applied it.
`_ui_evidence_breadth_739`, which decides `validation_ui_evidence_failed`, had no notion of
age at all.

tiktok-r96 resume #5 aborted with that as its ONLY failing check, and every one of the 8
records blocking it was 28h+ old, from before two resumes, while every fresh walk that run
had passed. #757 names this outcome exactly: "that is not a gate, it is a latch."

On r96's real ledger the three fixes compose: 6 failing records -> 5 (#1202fq attribution)
-> 1 (#1202fs staleness), and the one that remains is a flow that was re-walked recently
and genuinely still fails.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "env_generator" / "llm_generator"))

from multi_agent.runtime.delivery_gate import (  # noqa: E402
    _ui_evidence_breadth_739, _build_validated_at_1202fs)

BUILD = 5000.0        # the api_smoke moment
OLD, NEW = 1000.0, 9000.0


def _rec(flow, status, at):
    return {"name": f"validation:ui_flow:{flow}", "status": status,
            "metadata": {"check": "ui_flow", "flow": flow},
            "recorded_at": at}


def _smoke(at):
    return {"name": "validation:api_smoke", "status": "success",
            "metadata": {"check": "api_smoke"}, "recorded_at": at}


def test_a_failure_predating_the_build_stops_blocking():
    recs = [_rec("live_discover", "failure", OLD), _smoke(BUILD)]
    assert _ui_evidence_breadth_739(recs)["failed_records"] == 1      # before
    b = _ui_evidence_breadth_739(recs, stale_before=BUILD)
    assert b["failed_records"] == 0, f"stale failure still latched: {b['pages_failed']}"


def test_a_failure_after_the_build_still_blocks():
    """The gate must keep its teeth for evidence about the CURRENT build."""
    recs = [_rec("live_discover", "failure", NEW), _smoke(BUILD)]
    b = _ui_evidence_breadth_739(recs, stale_before=BUILD)
    assert b["failed_records"] == 1


def test_a_stale_PASS_is_never_dropped():
    """#357's regression direction is untouched: a green flow stays green."""
    recs = [_rec("explore_grid", "success", OLD), _smoke(BUILD)]
    b = _ui_evidence_breadth_739(recs, stale_before=BUILD)
    assert b["passed_records"] == 1, "dropped a passing record"


def test_disabled_by_default():
    recs = [_rec("live_discover", "failure", OLD), _smoke(BUILD)]
    assert _ui_evidence_breadth_739(recs)["failed_records"] == 1
    assert _ui_evidence_breadth_739(recs, stale_before=0)["failed_records"] == 1


def test_mixed_ledger_keeps_only_the_current_failures():
    recs = [_rec("old_one", "failure", OLD), _rec("old_two", "failure", OLD),
            _rec("fresh", "failure", NEW), _rec("green", "success", NEW), _smoke(BUILD)]
    b = _ui_evidence_breadth_739(recs, stale_before=BUILD)
    assert sorted(set(b["pages_failed"])) == ["fresh"], b["pages_failed"]


def test_clock_comes_from_the_api_smoke_records():
    """One definition of 'stale', shared with #401 -- not a second one."""
    assert _build_validated_at_1202fs([_smoke(BUILD)]) > 0
    assert _build_validated_at_1202fs([_rec("x", "failure", OLD)]) == 0.0


def test_clock_reuses_flow_coverage_implementation():
    import inspect
    assert "_latest_build_validation_time" in inspect.getsource(_build_validated_at_1202fs)


def test_clock_degrades_audibly_not_silently():
    """#1201/#1202ah: returning 0.0 quietly would restore the latch."""
    import inspect
    src = inspect.getsource(_build_validated_at_1202fs)
    assert "warn_once_1201" in src, "a silent 0.0 would re-latch the gate"


def test_records_without_a_timestamp_are_kept():
    recs = [{"name": "validation:ui_flow:x", "status": "failure",
             "metadata": {"check": "ui_flow", "flow": "x"}}, _smoke(BUILD)]
    b = _ui_evidence_breadth_739(recs, stale_before=BUILD)
    assert b["failed_records"] == 1, "an untimed record must not be assumed stale"
