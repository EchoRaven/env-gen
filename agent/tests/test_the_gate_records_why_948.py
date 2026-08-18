r"""#948: the delivery gate returns 21 fields of reasoning and one artifact saw three of them.

`validate_delivery_gate` returns `ok`, `state`, `failed_checks`, `business_chain`, `completeness`,
`deliverability`, `projection_errors`, `build_evidence`, `verification`, `contract_alignment`,
`unresolved_bugs`, `incomplete_required_tasks` and nine more. The only artifact that ever carried
any of it is the progress tick — `ok`, `failed_checks`, `did_not_run`. r154's
`progress_events.jsonl` holds 36 ticks and not one word of WHY.

★ I filed this under "a design question — where does the reasoning belong?" (#947) and that was
wrong. The caller already receives the whole structure and projects three keys out of it: #771b's
fixed-key projection loss, in the function that decides whether to ship. The remedy is the one the
visual ledger already uses — append, never overwrite — and it needs no decision from anyone.

Values are capped individually because `business_chain` can carry every chain's every step, and an
artifact nobody can open is the same as no artifact.
"""
import json
import logging
from pathlib import Path

import pytest

from env_generator.llm_generator.multi_agent import orchestrator as orc


def _write(tmp_path, gate):
    orc._persist_gate_948(tmp_path, gate, logging.getLogger("t948"))
    f = tmp_path / "logs" / "delivery_gate.jsonl"
    return [json.loads(l) for l in f.read_text().splitlines() if l.strip()] if f.is_file() else []


def test_the_reasoning_reaches_an_artifact(tmp_path):
    rows = _write(tmp_path, {"ok": False, "failed_checks": ["business_chain_failing"],
                             "business_chain": {"broken": ["[c1] step 3 -> 500"]},
                             "deliverability": {"blockers": ["ui_flow_missing"]}})
    r = rows[-1]
    assert r["failed_checks"] == ["business_chain_failing"]
    assert r["business_chain"]["broken"] == ["[c1] step 3 -> 500"]
    assert r["deliverability"]["blockers"] == ["ui_flow_missing"]


def test_every_evaluation_is_kept(tmp_path):
    """★ Append, not overwrite. r154 ran 36 evaluations; the interesting one is rarely the last —
    the gate flipped green at 17:56, red at 17:59, green at 18:00 and red again at 18:34."""
    _write(tmp_path, {"ok": False, "failed_checks": ["a"]})
    _write(tmp_path, {"ok": True, "failed_checks": []})
    rows = _write(tmp_path, {"ok": False, "failed_checks": ["b"]})
    assert [r["ok"] for r in rows] == [False, True, False]
    assert [r["failed_checks"] for r in rows] == [["a"], [], ["b"]]


def test_each_row_is_timestamped(tmp_path):
    assert _write(tmp_path, {"ok": True})[-1]["at"] > 0


def test_an_enormous_field_is_capped_not_dropped(tmp_path):
    """★ Capped per VALUE: one huge chain dump must not cost the other twenty fields, and must not
    make the file unopenable either."""
    big = {"steps": [{"i": i, "note": "x" * 200} for i in range(200)]}
    r = _write(tmp_path, {"ok": False, "business_chain": big, "completeness": {"n": 3}})[-1]
    assert r["completeness"] == {"n": 3}, "a big neighbour must not lose a small field"
    assert r["business_chain"]["_truncated_948"] > 4000
    assert "steps" in r["business_chain"]["head"], "the head must still be readable"


def test_an_unserialisable_value_does_not_lose_the_row(tmp_path):
    class Weird:
        def __repr__(self):
            return "<weird>"
    r = _write(tmp_path, {"ok": True, "odd": Weird(), "failed_checks": []})[-1]
    assert r["ok"] is True and r["failed_checks"] == []


def test_an_unwritable_directory_does_not_break_the_gate(tmp_path):
    """Observability must never break what it observes — the gate decides whether to ship."""
    orc._persist_gate_948(tmp_path / "nope" / "\0bad", {"ok": True}, logging.getLogger("t948"))


def test_the_wrapper_persists_before_returning():
    """★ Structural: every call site goes through `_validate_delivery_gate`, so the persist belongs
    there rather than at six call sites — and it must run before the return."""
    import ast
    import inspect
    tree = ast.parse(inspect.getsource(orc))
    fn = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
          and n.name == "_validate_delivery_gate"][0]
    calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call)
             and getattr(n.func, "id", None) == "_persist_gate_948"]
    rets = [n for n in ast.walk(fn) if isinstance(n, ast.Return)]
    assert len(calls) == 1 and len(rets) == 1
    assert calls[0].lineno < rets[0].lineno


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
