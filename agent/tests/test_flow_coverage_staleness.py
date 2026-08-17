"""#401 (netflix r3 FAIL-FAST): a ui_flow FAILURE verdict is verifier-driven and lags the
build — a flow the frontend has since FIXED kept its old failure record for the rest of the
run, false-failing the delivery gate to a STUCK abort (browse_home/player recorded fail at
23:31, fixed minutes later, never re-checked, aborted at 00:49). The staleness-invalidation
drops a FAILED/ERROR ui_flow record older than the latest build validation so the flow re-reads
as MISSING (→ re-verify) instead of a permanent hard-fail. A PASSING record is never dropped,
and a SAME-PASS failure (within the grace margin) is preserved. This locks that in.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

_FC = (Path(__file__).resolve().parents[1] / "env_generator" / "llm_generator" /
       "multi_agent" / "runtime" / "flow_coverage.py")


def _load():
    spec = importlib.util.spec_from_file_location("_flowcov_under_test", _FC)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class _Hub:
    def __init__(self, results):
        self._r = results

    def get_validation_results(self, status=None, agent=None, limit=100):
        return self._r


def _uiflow(flow, status, at):
    return {"name": "validation:ui_flow:" + flow, "status": status, "recorded_at": at}


def _apismoke(at):
    return {"name": "validation:api_smoke", "status": "passed", "recorded_at": at,
            "metadata": {"check": "api_smoke"}}


def test_latest_build_validation_time_uses_apismoke_minus_grace():
    fc = _load()
    hub = _Hub([_apismoke(10_000.0), _apismoke(12_000.0)])
    # newest api_smoke (12000) minus the 300s grace
    assert fc._latest_build_validation_time(hub) == 12_000.0 - fc._UI_FLOW_STALE_GRACE_S


def test_stale_failure_dropped_when_older_than_build():
    fc = _load()
    # failure recorded at t=1000; a later build validation at t=9999 (>> grace) → stale → dropped
    hub = _Hub([_uiflow("browse_home_ui", "failed", 1000.0)])
    idx = fc._index_ui_flow_records(hub, stale_before=9000.0)
    assert "browse_home_ui" not in idx, idx  # dropped → flow reads as MISSING downstream


def test_samepass_failure_preserved():
    fc = _load()
    # failure at t=9500, build validation grace-floor at 9000 → NOT older → kept as failed
    hub = _Hub([_uiflow("player_ui", "failed", 9500.0)])
    idx = fc._index_ui_flow_records(hub, stale_before=9000.0)
    assert idx.get("player_ui") == "failed"


def test_passing_record_never_dropped_even_if_old():
    fc = _load()
    hub = _Hub([_uiflow("landing_ui", "passed", 1000.0)])
    idx = fc._index_ui_flow_records(hub, stale_before=9000.0)
    assert idx.get("landing_ui") == "passed"  # a green flow stays green


def test_default_disables_staleness():
    fc = _load()
    hub = _Hub([_uiflow("browse_home_ui", "failed", 1000.0)])
    # no stale_before (default 0.0) → old behaviour: failure retained
    assert fc._index_ui_flow_records(hub).get("browse_home_ui") == "failed"


def test_latest_wins_still_holds_with_staleness():
    fc = _load()
    # a later PASS must still clear an earlier fail (regression-gate #357 direction preserved),
    # and staleness must not resurrect the fail
    hub = _Hub([_uiflow("browse_home_ui", "failed", 1000.0),
                _uiflow("browse_home_ui", "passed", 2000.0)])
    assert fc._index_ui_flow_records(hub, stale_before=1500.0).get("browse_home_ui") == "passed"


def test_end_to_end_r3_scenario_demotes_to_reverify():
    # the exact r3 shape: browse_home/player failed early, landing passed, many later api_smoke
    fc = _load()
    hub = _Hub([
        _uiflow("browse_home_ui", "failed", 1000.0),
        _uiflow("player_ui", "failed", 1005.0),
        _uiflow("landing_ui", "passed", 1010.0),
        _apismoke(1000.0), _apismoke(3000.0), _apismoke(5000.0),  # rebuilt+revalidated since
    ])
    sb = fc._latest_build_validation_time(hub)   # 5000 - 300 = 4700
    idx = fc._index_ui_flow_records(hub, stale_before=sb)
    assert "browse_home_ui" not in idx and "player_ui" not in idx  # stale fails → re-verify
    assert idx.get("landing_ui") == "passed"                       # green stays green


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
