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


def _method_span(src):
    i = src.index("async def _maybe_framework_deliver")
    j = min(x for x in (src.find("\n    async def ", i + 10), src.find("\n    def ", i + 10))
            if x > 0)
    return src[:i].count("\n") + 1, src[:j].count("\n") + 1


def test_every_post_gate_return_records_its_hold():
    """The rule, not the instance: a fifteenth hold added tomorrow must say so too."""
    src = ORCH_PY.read_text(encoding="utf-8")
    lines = src.split("\n")
    start, end = _method_span(src)
    gate = next(n for n in range(start, end)
                if "_gate1202qx = self._validate_delivery_gate()" in lines[n - 1])
    missing = []
    for n in range(gate, end):
        if not lines[n - 1].strip().startswith("return"):
            continue
        window = "\n".join(lines[max(gate, n - 4):n])
        if "_note_delivery_hold_1202tk" not in window:
            missing.append(f"orchestrator.py:{n}: {lines[n - 1].strip()[:70]}")
    assert missing == [], (
        "these hold the release after a CLEAR gate and record nothing, so a run cannot be "
        "asked why it did not ship: %s" % missing)


def test_the_holds_are_named_distinctly():
    """A ledger of fourteen `hold: "deferred"` lines answers nothing."""
    src = ORCH_PY.read_text(encoding="utf-8")
    start, end = _method_span(src)
    lines = src.split("\n")
    names = [ast.literal_eval(l.strip().split("(self, ")[1].split(")")[0].split(",")[0])
             for l in lines[start:end] if "_note_delivery_hold_1202tk(self," in l]
    assert len(names) >= 14, names
    assert len(set(names)) == len(names), f"duplicate hold names: {names}"


def test_the_gate_ledger_is_untouched():
    """#948's file keeps its own contract; this is a sibling, not a rewrite."""
    src = ORCH_PY.read_text(encoding="utf-8")
    assert "logs\" / \"delivery_gate.jsonl\"" in src or "delivery_gate.jsonl" in src
    assert "delivery_hold.jsonl" in src
