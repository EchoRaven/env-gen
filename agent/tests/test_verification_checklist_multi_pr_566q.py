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


import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.delivery_gate import (  # noqa: E402
    _build_status_1203qr, _latest_build_checks_1203qr)


def _reduce_new(build_checks):
    """#1203qr: the REAL reduction, not a copy of it.

    This file used to define the new form here beside `_reduce_old` and assert that the old
    one raises while the new one works -- which proves the ALGORITHM and says nothing about
    what `validate_delivery_gate` runs. Production could drift back to storing the status
    string and every assertion below would still pass. `_reduce_old` stays: it is the
    DEFECT, kept as the contrast that gives the others meaning."""
    by = _latest_build_checks_1203qr(build_checks)
    return {k: _build_status_1203qr(by, k) for k in by}


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


def test_a_component_with_no_record_reads_pending_1203qr():
    """The `_st` half: absent is 'pending', never a silent success."""
    by = _latest_build_checks_1203qr(_MULTI)
    assert _build_status_1203qr(by, "nonexistent") == "pending"
    assert _build_status_1203qr({}, "docker") == "pending"
    assert _build_status_1203qr(None, "docker") == "pending"


def test_the_reduction_keeps_the_DICT_not_the_status_1203qr():
    """#566q's actual defect: storing the status STRING made the next record's
    `prev.get("updated_at")` an AttributeError, swallowed by the gate's outer except, and
    ready_for_delivery stayed False forever."""
    by = _latest_build_checks_1203qr(_MULTI)
    assert isinstance(by["docker"], dict), by["docker"]
    assert by["docker"].get("updated_at") == 200


def test_a_non_dict_record_is_skipped_not_fatal_1203qr():
    by = _latest_build_checks_1203qr([None, "build:docker", 7,
                                      {"name": "build:docker", "status": "success",
                                       "updated_at": 5}])
    assert by == {"docker": {"name": "build:docker", "status": "success", "updated_at": 5}}


def _gate_assignment_1203qp(name):
    """The AST node that assigns `<name> = ...` at any depth in delivery_gate, or None."""
    import ast
    import inspect
    from multi_agent.runtime import delivery_gate as _dg
    for n in ast.walk(ast.parse(inspect.getsource(_dg))):
        if (isinstance(n, ast.Assign) and len(n.targets) == 1
                and isinstance(n.targets[0], ast.Name) and n.targets[0].id == name):
            return n
    return None


def _gate_extend_args_1203qp(func_name):
    """Every `*.extend(<arg>)` whose arg mentions `func_name`, as AST nodes."""
    import ast
    import inspect
    from multi_agent.runtime import delivery_gate as _dg
    out = []
    for n in ast.walk(ast.parse(inspect.getsource(_dg))):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == "extend" and n.args
                and func_name in ast.dump(n.args[0])):
            out.append(n.args[0])
    return out


def test_the_gate_takes_the_reduction_as_given_1203qr():
    """ARRIVAL. `_latest_build_checks_1203qr(build_checks) and {}` keeps the call and the
    name while handing the gate an empty dict, so the assignment's VALUE must be the bare
    call."""
    import ast
    node = _gate_assignment_1203qp("by_component")
    assert node is not None, "nothing assigns by_component in delivery_gate"
    assert isinstance(node.value, ast.Call), ast.dump(node.value)[:200]
    assert isinstance(node.value.func, ast.Name), ast.dump(node.value)[:200]
    assert node.value.func.id == "_latest_build_checks_1203qr", node.value.func.id


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
