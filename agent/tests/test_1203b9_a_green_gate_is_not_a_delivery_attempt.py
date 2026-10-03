r"""#1203b9: "the gate was green" is not "a delivery was attempted", and the ledger could not say.

`_persist_gate_948` writes one line per gate EVALUATION. Its only caller,
`_validate_delivery_gate`, is itself called from EIGHT places: two in
`_maybe_framework_deliver` (the delivery path), five in `run` (the main loop asking for its own
reasons) and one in `_final_gate_grace_1202dp`. A green line from `run` means the gate was
asked — not that anything tried to ship.

THE COST IS A WRONG READING OF THE RUN. #1202tk's docstring states "41 runs reach a fully-green
gate and never deliver" off these ledgers; I repeated the shape about r144 ("12 green windows, 0
releases") and counted every green as a missed delivery. r145 broke it: a green tick that added
NO line to `delivery_hold.jsonl`, because nothing attempted delivery on it — and establishing
that took several passes of cross-referencing two ledgers.

The field is resolved from the call stack (so none of the eight call sites changes) and is
ALWAYS present — `"?"` when unresolvable, because a key that quietly vanishes reads as "nobody
evaluated the gate".
"""
import json
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))
sys.path.insert(0, _AGENT)

import logging  # noqa: E402

from multi_agent.orchestrator import _persist_gate_948  # noqa: E402

_KEY = "evaluated_by_1203b9"
_LOG = logging.getLogger("t1203b9")


def _rows(tmp_path):
    p = tmp_path / "logs" / "delivery_gate.jsonl"
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def _validate_delivery_gate(tmp_path, gate):
    """Stands in for the real validator: the frame the writer must SKIP."""
    _persist_gate_948(tmp_path, gate, _LOG)


def test_a_delivery_path_evaluation_is_labelled(tmp_path):
    """★ The distinction the whole ticket is about."""
    def _maybe_framework_deliver():
        _validate_delivery_gate(tmp_path, {"ok": True, "failed_checks": []})
    _maybe_framework_deliver()
    assert _rows(tmp_path)[0][_KEY] == "_maybe_framework_deliver", _rows(tmp_path)[0][_KEY]


def test_a_main_loop_evaluation_is_labelled(tmp_path):
    """Five of the eight call sites are here, and a green from one of them shipped nothing."""
    def run():
        _validate_delivery_gate(tmp_path, {"ok": True, "failed_checks": []})
    run()
    assert _rows(tmp_path)[0][_KEY] == "run"


def test_the_grace_check_is_labelled(tmp_path):
    def _final_gate_grace_1202dp():
        _validate_delivery_gate(tmp_path, {"ok": False, "failed_checks": ["x"]})
    _final_gate_grace_1202dp()
    assert _rows(tmp_path)[0][_KEY] == "_final_gate_grace_1202dp"


def test_the_writer_and_the_validator_are_skipped(tmp_path):
    """Neither of the two frames between the caller and the file may be reported — that would
    label every line identically and answer nothing."""
    def run():
        _validate_delivery_gate(tmp_path, {"ok": True})
    run()
    got = _rows(tmp_path)[0][_KEY]
    assert got not in ("_persist_gate_948", "_validate_delivery_gate"), got


def test_the_key_is_always_present(tmp_path):
    """★ #1202ah's rule applied to an observability field: a key that disappears when
    resolution fails reads as "the gate was never evaluated from anywhere"."""
    _persist_gate_948(tmp_path, {"ok": True}, _LOG)      # called with no caller frame to find
    row = _rows(tmp_path)[0]
    assert _KEY in row, sorted(row)
    assert isinstance(row[_KEY], str) and row[_KEY], row[_KEY]


def test_the_existing_payload_is_unchanged(tmp_path):
    """Additive only — #948's twenty-one fields keep their names and values."""
    gate = {"ok": False, "failed_checks": ["a", "b"], "business_chain": {"x": 1},
            "completeness": [], "verification": {"checklist": {}}}
    def run():
        _validate_delivery_gate(tmp_path, gate)
    run()
    row = _rows(tmp_path)[0]
    for k, v in gate.items():
        assert row[k] == v, (k, row[k], v)
    assert "at" in row


def test_one_line_per_evaluation(tmp_path):
    """The ledger stays append-only and one-line-per-call; the new field must not change that."""
    def run():
        _validate_delivery_gate(tmp_path, {"ok": True})
    for _ in range(3):
        run()
    rows = _rows(tmp_path)
    assert len(rows) == 3
    assert all(r[_KEY] == "run" for r in rows)


def test_the_writer_is_still_the_only_one(tmp_path):
    """★ The field is only meaningful while `_persist_gate_948` has exactly one caller. If a
    second one appears, the frame-skip list is wrong and this test says so rather than letting
    the label silently point at the wrong function."""
    import ast
    import inspect
    import multi_agent.orchestrator as O

    tree = ast.parse(inspect.getsource(O))
    callers = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and (getattr(n.func, "id", "")
                                        or getattr(n.func, "attr", "")) == "_persist_gate_948":
            for f in ast.walk(tree):
                if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                        and f.lineno <= n.lineno <= (f.end_lineno or 0):
                    callers.add(f.name)
    assert callers == {"_validate_delivery_gate"}, sorted(callers)
