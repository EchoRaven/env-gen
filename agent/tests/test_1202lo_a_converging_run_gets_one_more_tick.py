"""#1202lo — the wall-clock cap aborted a run 56 seconds after its last blocker cleared.

GROUND TRUTH (tiktok-web-r121, 2026-09-13), from its own gate ledger and hub records:

    00:23:36  delivery gate: validation_ui_evidence_failed on 2 record(s)
              (root cause named: ui_signup_modal, ui_smoke)
    00:23:38  codehub validation:ui_flow:ui_signup_modal  -> success
    00:23:42  codehub validation:ui_smoke                 -> success
    00:24:38  wall-clock 7242s exceeded cap 7200s -> ABORT.  $270.47, nothing delivered

The gate evaluates every ~60-75s, so one more evaluation was the whole gap.

Convergence is measured on blocking INSTANCES, never on the failing-check names: r121's
`failed_checks` read `['validation_ui_evidence_failed']` — unchanged — for its last twelve
evaluations, while the instance count underneath went 6 -> 3 -> 4 -> 3 -> 2. A check name is
flat by construction while a lane clears its records one at a time, so keying on the name
would have measured nothing.

★ The criterion was validated on known cases BEFORE being wired, across every corpus run
carrying both a gate ledger and a budget ledger:

    stuck_abort      7 runs   converging: 0 of 7   <- the class that must NEVER get a grace
    budget_exceeded  2 runs   converging: 1 (r121)
    delivered        6 runs   converging: 2        <- harmless; they already shipped

Zero of seven stuck aborts qualify. That is the safety argument: a stuck run's instance count
is flat or rising, and flat is not converging.
"""
import ast
import inspect
import json
import time

import pytest

from env_generator.llm_generator.multi_agent.runtime import run_budget as rb


def _ledger(tmp_path, counts, now=None, step=70.0):
    """Write a gate ledger whose blocking-instance count walks `counts`."""
    now = now if now is not None else time.time()
    d = tmp_path / "logs"
    d.mkdir(parents=True, exist_ok=True)
    lines = []
    n = len(counts)
    for i, c in enumerate(counts):
        lines.append(json.dumps({
            "at": now - step * (n - 1 - i),
            "failed_checks": ["validation_ui_evidence_failed"] if c else [],
            "ui_evidence_failed_records": c,
        }))
    (d / "delivery_gate.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return tmp_path


def test_r121s_own_trace_converges(tmp_path):
    """★ The real sequence from r121's last five minutes."""
    assert rb.converging_at_the_gate_1202lo(_ledger(tmp_path, [6, 3, 4, 3, 2])) is True


@pytest.mark.parametrize("counts,why", [
    ([2, 2, 2, 2], "flat — the shape all seven corpus stuck_aborts have"),
    ([2, 3, 4, 5], "rising"),
    ([6, 3, 0], "already at zero: nothing is blocking, so the cap is not what stopped it"),
    ([4, 4, 6, 4], "ends where it started"),
])
def test_what_must_not_earn_a_grace(tmp_path, counts, why):
    assert rb.converging_at_the_gate_1202lo(_ledger(tmp_path, counts)) is False, why


def test_a_stale_ledger_is_not_convergence(tmp_path):
    """The gate stopped evaluating — nothing is landing, however good the old trend."""
    old = time.time() - 3600
    assert rb.converging_at_the_gate_1202lo(_ledger(tmp_path, [6, 4, 2], now=old)) is False


def test_too_few_evaluations_prove_nothing(tmp_path):
    assert rb.converging_at_the_gate_1202lo(_ledger(tmp_path, [6, 2])) is False


def test_no_ledger_at_all_is_not_convergence(tmp_path):
    assert rb.converging_at_the_gate_1202lo(tmp_path) is False
    assert rb.converging_at_the_gate_1202lo("") is False
    assert rb.converging_at_the_gate_1202lo(None) is False


def test_every_check_family_counts_toward_the_instances():
    """A run converging on chains must qualify as surely as one converging on UI evidence."""
    row = {"ui_evidence_failed_records": 2,
           "business_chain": {"chains": ["a", "b", "c"]},
           "incomplete_required_tasks": ["t1"],
           "unresolved_bugs": {"open_p0_bug_count": 4}}
    assert rb._blocking_instances_1202lo(row) == 10
    assert rb._blocking_instances_1202lo({}) == 0
    assert rb._blocking_instances_1202lo({"business_chain": None}) == 0


def test_a_chain_only_convergence_qualifies(tmp_path):
    d = tmp_path / "logs"
    d.mkdir(parents=True)
    now = time.time()
    rows = []
    for i, k in enumerate((5, 3, 1)):
        rows.append(json.dumps({"at": now - 70 * (2 - i),
                                "failed_checks": ["business_chain_failing"],
                                "business_chain": {"chains": ["c%d" % j for j in range(k)]}}))
    (d / "delivery_gate.jsonl").write_text("\n".join(rows) + "\n", encoding="utf-8")
    assert rb.converging_at_the_gate_1202lo(tmp_path) is True


def test_the_grace_is_bounded_and_smaller_than_the_cap_it_extends():
    assert 60.0 <= rb._WALL_GRACE_SEC_1202LO <= 1800.0
    assert rb._CONVERGENCE_WINDOW_1202LO >= 120.0


# ---------------------------------------------------------------- the wiring

def _wall_check_src():
    """The orchestrator branch that latches the wall-clock overrun."""
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / "env_generator" / "llm_generator"
           / "multi_agent" / "orchestrator.py").read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(src)):
        if (isinstance(node, ast.If)
                and "exceeded cap" in (ast.get_source_segment(src, node) or "")
                and "max_wall_sec" in (ast.unparse(node.test) or "")):
            return node, src
    raise AssertionError("the wall-clock cap check moved — relocate this landmark")


def test_the_grace_is_asked_before_the_abort_latches():
    node, src = _wall_check_src()
    calls = [n.lineno for n in ast.walk(node)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id == "converging_at_the_gate_1202lo"]
    latches = [n.lineno for n in ast.walk(node)
               if isinstance(n, ast.Assign)
               and any(isinstance(t, ast.Name) and t.id == "budget_exceeded"
                       for t in n.targets)]
    assert calls, "the wall-clock abort no longer asks whether the run is converging"
    assert latches, "the abort latch moved"
    assert min(calls) < min(latches), "the question must be asked BEFORE the abort latches"


def test_the_grace_is_granted_at_most_once_per_process():
    node, src = _wall_check_src()
    seg = ast.get_source_segment(src, node) or ""
    assert "_wall_grace_used_1202lo" in seg
    assert seg.count("_wall_grace_used_1202lo") >= 2, (
        "the flag must be both READ (to refuse a second grace) and SET (when granting)")


def test_granting_still_leaves_the_abort_reachable():
    """★ Never a way to hang: the else arm must still latch budget_exceeded."""
    node, src = _wall_check_src()
    inner = [n for n in ast.walk(node)
             if isinstance(n, ast.If) and n.orelse
             and "_grace_1202lo" == getattr(n.test, "id", None)]
    assert inner, "the grace branch is not an if/else — the abort may have become unreachable"
    orelse = "\n".join(ast.unparse(x) for x in inner[0].orelse)
    assert "budget_exceeded" in orelse, "a run that is NOT converging must still abort"
