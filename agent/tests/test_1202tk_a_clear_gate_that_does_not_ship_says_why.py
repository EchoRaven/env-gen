r"""#1202tk: when a clear delivery gate does not ship, the run must record WHICH hold stopped it.

`delivery_gate.jsonl` exists because of `#948` — so a run can be asked afterwards what stopped
it. But the gate is only the FIRST of fourteen conditions in `_maybe_framework_deliver`. Once
`failed_checks` is empty, thirteen more can still hold the release: stale build evidence, the
unbuilt-pages dispatch, the visual gate, its final re-capture, the test-user squad (SIX
separate deferrals), the browser walkthrough, route consolidation, and the fresh pre-cut smoke.

None of them was written anywhere durable. They went to the run log, and a run log is not kept
— tiktok-r130's directory has `delivery_gate.jsonl`, `progress_events.jsonl` and
`preflight.json`, and nothing else.

So "the gate was green and nothing shipped" was unanswerable from a run directory, which is the
most consequential question this system has.

MEASURED over all 77 gate ledgers: 41 runs reach a fully-green gate and never deliver. r130 is
the sharpest — EIGHT green windows totalling ~50 minutes, including 21.7 minutes immediately
before its budget abort, 0 releases cut, 1 milestone snapshot, and no record of which hold
fired. It ran 09-17 22:57, nearly four hours AFTER #1202qu–qx landed (09-17 19:03) for r128's
lost green windows, so that fix did not close this.

★ THIS ALSO CORRECTS MY OWN FRAMING. I set out to find "gates crying wolf" and measured "runs
that went green and did not deliver" as if the gate ledger's `ok` meant deliverable. It does
not: it is one of fourteen. The r128 note put it in three words — *gate green ≠ release* — and
this arrives at the same place from the other end. The ledger was answering a narrower question
than I was asking it.

WHAT THIS IS NOT: a fix for any hold. Every one of the fourteen is a deliberate gate with its
own reasoning, and several are SOFT (they escape after a cap). This only makes the choice
visible, so the next person measuring "why didn't it deliver" has data instead of a gap.

LOCAL-ONLY (gitignored)."""
from __future__ import annotations

import ast
import json
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from multi_agent.orchestrator import _note_delivery_hold_1202tk as note  # noqa: E402

ORCH_PY = LLM_DIR / "multi_agent" / "orchestrator.py"


def _fake(tmp):
    return types.SimpleNamespace(output_dir=str(tmp), _current_milestone_version="1.2.0")


def test_it_writes_one_line_per_hold():
    d = Path(tempfile.mkdtemp())
    note(_fake(d), "squad_defects", "3 P0 defects open")
    note(_fake(d), "fresh_smoke")
    rows = [json.loads(l) for l in
            (d / "logs" / "delivery_hold.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [r["hold"] for r in rows] == ["squad_defects", "fresh_smoke"]
    assert rows[0]["detail"] == "3 P0 defects open"
    assert rows[0]["milestone"] == "1.2.0"
    assert rows[0]["at"] > 0


def test_it_appends_rather_than_overwrites():
    """#948's own lesson, applied: the ledger is a history, not a snapshot."""
    d = Path(tempfile.mkdtemp())
    for i in range(3):
        note(_fake(d), f"hold_{i}")
    assert len((d / "logs" / "delivery_hold.jsonl").read_text().strip().splitlines()) == 3


def test_it_can_never_break_a_delivery():
    """An observability write must not be able to stop the thing it observes."""
    note(None, "x")
    note(types.SimpleNamespace(), None)
    note(types.SimpleNamespace(output_dir="/proc/nonexistent/nope"), "y")


def _deliver_fn():
    """The method as an AST node.

    #1202to reformatted one of the calls across five lines and the previous line-scraping
    versions of the two checks below both broke -- the ratchet was pinned to the FORMATTING,
    not to the property. Parsing states the property directly and cannot be broken by a
    reflow.
    """
    tree = ast.parse(ORCH_PY.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) \
                and node.name == "_maybe_framework_deliver":
            return node
    raise AssertionError("_maybe_framework_deliver is gone")


def _is_note(stmt):
    return (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call)
            and isinstance(stmt.value.func, ast.Name)
            and stmt.value.func.id == "_note_delivery_hold_1202tk")


def _note_calls(fn):
    return [n for n in ast.walk(fn) if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name) and n.func.id == "_note_delivery_hold_1202tk"]


def _gate_line(fn):
    for n in ast.walk(fn):
        if isinstance(n, ast.Name) and n.id == "_gate1202qx":
            return n.lineno
    raise AssertionError("#1202qx's gate call is gone")


def _returns_without_a_hold(body, covered, gate, out):
    """Walk the block tree; a return is covered when a hold was recorded earlier on its path.

    `covered` is True once an unconditional note has run in this block or any enclosing one --
    which is exactly "every path to here recorded a hold", the property the ledger needs. A
    4-line text window only approximated it.
    """
    seen = covered
    for stmt in body:
        if _is_note(stmt):
            seen = True
            continue
        if isinstance(stmt, ast.Return):
            if stmt.lineno > gate and not seen:
                out.append(f"orchestrator.py:{stmt.lineno}")
            continue
        for field in ("body", "orelse", "finalbody"):
            inner = getattr(stmt, field, None)
            if isinstance(inner, list) and inner and isinstance(inner[0], ast.stmt):
                _returns_without_a_hold(inner, seen, gate, out)
        for handler in getattr(stmt, "handlers", []):
            _returns_without_a_hold(handler.body, seen, gate, out)


def test_every_post_gate_return_records_its_hold():
    """The rule, not the instance: a fifteenth hold added tomorrow must say so too."""
    fn = _deliver_fn()
    missing = []
    _returns_without_a_hold(fn.body, False, _gate_line(fn), missing)
    assert missing == [], (
        "these hold the release after a CLEAR gate and record nothing, so a run cannot be "
        "asked why it did not ship: %s" % missing)


def test_the_holds_are_named_distinctly():
    """A ledger of fourteen `hold: "deferred"` lines answers nothing."""
    names = []
    for call in _note_calls(_deliver_fn()):
        assert len(call.args) >= 2, ast.dump(call)
        name = call.args[1]
        assert isinstance(name, ast.Constant) and isinstance(name.value, str), (
            "the hold name must be a literal, or the ledger cannot be read without running "
            "the pipeline: %s" % ast.dump(name))
        names.append(name.value)
    assert len(names) >= 14, names
    assert len(set(names)) == len(names), f"duplicate hold names: {names}"


def test_the_gate_ledger_is_untouched():
    """#948's file keeps its own contract; this is a sibling, not a rewrite."""
    src = ORCH_PY.read_text(encoding="utf-8")
    assert "logs\" / \"delivery_gate.jsonl\"" in src or "delivery_gate.jsonl" in src
    assert "delivery_hold.jsonl" in src
