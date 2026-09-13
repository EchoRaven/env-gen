"""#1202lu — a resume inherits an exhausted lane-time clock and dies on its first tick.

GROUND TRUTH (tiktok-web-r121, resume #2, 2026-09-13):

    10:28:43  Resuming from checkpoint (phase=agent_workflow, resumes=2)
    10:38:30  gate: ['deliverability_no_successful_run', 'deliverability_dead_artifacts',
                     'deliverability_ui_flow_missing', 'business_chain_failing']
    10:38:30  DELIVERY-GATE NO-CONVERGENCE ABORT: delivery never SUCCEEDED in 86min of lane
              time ... STUCK — aborted without delivery after 1 coordination ticks
    10:39:04  registryhub: GET /__noop__                            -> deprecated
    10:39:05  registryhub: GET /__noop_orchestrator_read_not_allowed__ -> deprecated

744s, $20.17, and the gate had been evaluated twice. Two of the four blockers could not have
been anything else that early:

  * `deliverability_no_successful_run` — the deliverability block reads
    `run_within_session: False`, which is DEFINITIONALLY true at process start; only a
    run_start in THIS process clears it.
  * `deliverability_dead_artifacts` — the two `/__noop*` registrations were still `defined`;
    their `_updated_at` records the lane deprecating them THIRTY-FOUR SECONDS after the
    abort. (`scan_dead_endpoints` already exempts `deprecated`, so they were correctly dead
    at 10:38:30 — this is not a missing exemption, it is a clock that did not wait.)

The third time this one run was stopped just short: 56s on the wall-clock cap (#1202lo), 39s
on the previous resume's no-convergence abort (#1202ls), 34s here.
"""
import ast
import inspect
import os
import re
from pathlib import Path

import pytest

_ORCH = (Path(__file__).resolve().parent.parent / "env_generator" / "llm_generator"
         / "multi_agent" / "orchestrator.py")


def _src():
    return _ORCH.read_text(encoding="utf-8")


def _abort_if():
    """The `if` that latches the no-convergence abort, located by AST."""
    src = _src()
    for n in ast.walk(ast.parse(src)):
        if (isinstance(n, ast.If)
                and "FWVAL_NO_DELIVER_ABORT_S" in (ast.unparse(n.test) or "")):
            return n, src
    raise AssertionError("the no-convergence abort condition moved")


def test_the_floor_is_a_conjunct_of_the_abort():
    node, src = _abort_if()
    test = ast.unparse(node.test)
    assert "_MIN_GATE_EVALS_BEFORE_ABORT_1202LU" in test, (
        "the abort can still fire on a process that has barely evaluated the gate")
    assert "_gate_evals_1202lu" in test


def test_the_counter_is_incremented_in_the_same_function_that_reads_it():
    """★ Reachability: a counter published elsewhere could be ABSENT on some path, and
    `0 >= 6` would then disable the abort forever — a far worse failure than the one this
    fixes. It must be incremented in the same block."""
    src = _src()
    tree = ast.parse(src)
    holder = None
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        seg = ast.get_source_segment(src, fn) or ""
        if "FWVAL_NO_DELIVER_ABORT_S" in seg and "_gate_evals_1202lu" in seg:
            holder = fn
            break
    assert holder is not None, "the abort and its counter are no longer in one function"
    assigns = [ast.unparse(n) for n in ast.walk(holder)
               if isinstance(n, ast.Assign)
               and any(isinstance(t, ast.Attribute) and t.attr == "_gate_evals_1202lu"
                       for t in n.targets)]
    assert assigns, "the counter is never incremented where it is read"
    assert any("+ 1" in a for a in assigns), assigns


def test_the_increment_precedes_the_abort_check():
    src = _src()
    tree = ast.parse(src)
    inc = [n.lineno for n in ast.walk(tree)
           if isinstance(n, ast.Assign)
           and any(isinstance(t, ast.Attribute) and t.attr == "_gate_evals_1202lu"
                   for t in n.targets)]
    node, _ = _abort_if()
    assert inc and min(inc) < node.lineno, (
        "the first evaluation must already be counted when the abort is considered")


def test_the_floor_is_small_and_overridable():
    src = _src()
    m = re.search(r'_MIN_GATE_EVALS_BEFORE_ABORT_1202LU = int\(\s*'
                  r'os\.environ\.get\("ENVGEN_MIN_GATE_EVALS_BEFORE_ABORT", "(\d+)"\)\)', src)
    assert m, "the floor is no longer a named, overridable constant"
    n = int(m.group(1))
    assert 2 <= n <= 20, (
        "the floor must cover a validate-and-re-gate cycle without becoming a second budget")


def test_the_floor_carries_its_measurement():
    """#647's rule, and the reason this number is 6 rather than a guess."""
    src = _src()
    i = src.index("_MIN_GATE_EVALS_BEFORE_ABORT_1202LU = int(")
    head = "\n".join(src[:i].splitlines()[-14:])
    assert "60-75s" in head or "60-75" in head, head[-400:]
    assert "1202lu" in head.lower()


def test_it_does_not_touch_the_fresh_run_path():
    """★ Non-regression by construction: the floor is a CONJUNCT added to an existing
    condition, so nothing that used to abort can now abort earlier."""
    node, src = _abort_if()
    assert isinstance(node.test, ast.BoolOp) and isinstance(node.test.op, ast.And)
    parts = [ast.unparse(v) for v in node.test.values]
    assert any("FWVAL_NO_DELIVER_ABORT_S" in p for p in parts)
    assert any("_fwval_abort_reason" in p for p in parts), (
        "the once-only latch must still be a conjunct")
