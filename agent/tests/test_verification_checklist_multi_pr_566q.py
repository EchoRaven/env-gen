r"""#566q (netflix r124/r126 verification_checklist wedge): validate_delivery_gate builds the build-
checklist from codehub.list_checks() WITHOUT a pr_id, so it sees build:* across ALL PRs (one per
milestone) → a component gets >1 record. The old reduction stored the STATUS STRING in by_component then
called prev.get("updated_at") on it → AttributeError on the 2nd record → swallowed by the gate's outer
except → ready_for_delivery=False FOREVER → verification_checklist_not_ready wedged M1 despite every
build:* being success. Fix: store the check DICT (compare updated_at), extract status at the end.

This locks the reduction algorithm: (a) the OLD form AttributeErrors on >1 record/component; (b) the NEW
form picks the LATEST status per component across all records and never crashes.
"""
import pytest


def _reduce_old(build_checks):
    by = {}
    for c in build_checks:
        comp = c.get("name", "").removeprefix("build:")
        prev = by.get(comp)
        if prev is None or c.get("updated_at", 0) > prev.get("updated_at", 0):
            by[comp] = c.get("status", "pending")   # BUG: stores a string
    return by


def _reduce_new(build_checks):
    by = {}
    for c in build_checks:
        comp = c.get("name", "").removeprefix("build:")
        prev = by.get(comp)
        if prev is None or c.get("updated_at", 0) > prev.get("updated_at", 0):
            by[comp] = c
    return {k: (v or {}).get("status", "pending") for k, v in by.items()}


# two PRs each recorded build:docker — the earlier FAILED, the later SUCCEEDED
_MULTI = [
    {"name": "build:docker", "status": "failure", "updated_at": 100},   # PR1 (older)
    {"name": "build:docker", "status": "success", "updated_at": 200},   # PR2 (newer)
    {"name": "build:backend", "status": "success", "updated_at": 150},
    {"name": "build:frontend", "status": "success", "updated_at": 150},
    {"name": "build:database", "status": "success", "updated_at": 150},
]


def test_old_reduction_crashes_on_multiple_records_per_component():
    with pytest.raises(AttributeError):
        _reduce_old(_MULTI)


def test_new_reduction_picks_latest_status_no_crash():
    by = _reduce_new(_MULTI)
    assert by["docker"] == "success"      # latest (updated_at=200) wins, not the older failure
    assert by["backend"] == "success"
    all_passing = all(by.get(c) == "success" for c in ("docker", "backend", "frontend", "database"))
    assert all_passing is True            # → ready_for_delivery → verification_checklist clears


def test_new_reduction_latest_failure_blocks():
    checks = [
        {"name": "build:docker", "status": "success", "updated_at": 100},
        {"name": "build:docker", "status": "failure", "updated_at": 300},   # latest = failure
    ]
    assert _reduce_new(checks)["docker"] == "failure"   # a real latest-failure still blocks


def test_new_reduction_single_record_unchanged():
    by = _reduce_new([{"name": "build:docker", "status": "success", "updated_at": 1}])
    assert by == {"docker": "success"}


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
