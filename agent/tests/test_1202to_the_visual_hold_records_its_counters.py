r"""#1202to: the hold that decides most runs recorded no numbers.

`#1202tk` made a clear-gate-that-does-not-ship say WHICH of the fourteen holds stopped it. The
visual hold is the one that matters, measured over the corpus:

    16 of 18 visual releases came from the WALL CLOCK, only 2 from a plateau
    median deferral at release            3448s (~57 min)
    total judgments at release            3-12  (median ~5)
    attempts at release                   0, 1 or 2 -- never the cap of 3

So the cheap escapes barely fire and a visually-imperfect run pays roughly an hour. The soft
plateau needs 4 consecutive no-improvement judgments (floored at 1500s) and the hard one 8 with
no floor -- and the hard escape therefore sits ABOVE the number of judgments most runs ever
make. `#519` already documents why the attempt cap cannot fire: the frontend edits the source
on every visual-fail and the per-source counter resets.

★ WHY THIS RECORDS A NUMBER INSTEAD OF RETUNING ONE. Whether the plateau thresholds should move
turns on how many of those judgments actually showed NO IMPROVEMENT -- and nothing records it.
`verdict.json` is overwritten every round, so the corpus cannot answer it, and neither could I:
reconstructing trajectories from interval snapshots samples time, not rounds. #647 wants a
measured rationale before a constant moves, so the counters go into the ledger and the next run
answers the question directly.

LOCAL-ONLY (gitignored)."""
from __future__ import annotations

import json
import sys
import tempfile
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from multi_agent.orchestrator import _note_delivery_hold_1202tk as note  # noqa: E402

ORCH_PY = LLM_DIR / "multi_agent" / "orchestrator.py"


def test_the_detail_carries_the_four_counters():
    d = Path(tempfile.mkdtemp())
    gate = types.SimpleNamespace(attempts=1, plateau_rounds=3, total_judgments=5,
                                 deferred_since=time.time() - 1800)
    orch = types.SimpleNamespace(output_dir=d, _current_milestone_version="1.0.0",
                                 _vf_gate=gate)
    note(orch, "visual_fidelity",
         "attempts=%s plateau_rounds=%s judged=%s deferred_s=%s" % (
             gate.attempts, gate.plateau_rounds, gate.total_judgments,
             int(time.time() - gate.deferred_since)))
    row = json.loads((d / "logs" / "delivery_hold.jsonl").read_text(encoding="utf-8").strip())
    assert row["hold"] == "visual_fidelity"
    for key in ("attempts=", "plateau_rounds=", "judged=", "deferred_s="):
        assert key in row["detail"], key
    assert "plateau_rounds=3" in row["detail"]


def test_the_call_site_reads_the_gate_not_a_guess():
    """The counters must come from `_vf_gate`; a hard-coded or recomputed number would answer
    a different question than the escape actually asks."""
    # #943: no fixed byte windows. Anchor on the landmarks either side and read what is
    # BETWEEN them -- a window that counts characters silently reaches into the next branch
    # when the code moves, which is the failure #943 exists to stop (and which the first
    # version of this very test committed).
    src = ORCH_PY.read_text(encoding="utf-8")
    start = src.index("_vfg1202to = getattr(self, \"_vf_gate\", None)")
    end = src.index("\n                    return", start)
    block = src[start:end]
    for attr in ("attempts", "plateau_rounds", "total_judgments", "deferred_since"):
        assert f'getattr(_vfg1202to, "{attr}"' in block, attr


def test_a_gate_without_the_attributes_still_records():
    """Best-effort: an observability write must never be able to stop a delivery, and a gate
    object that has not been built yet must not raise here."""
    d = Path(tempfile.mkdtemp())
    orch = types.SimpleNamespace(output_dir=d, _current_milestone_version="1.0.0",
                                 _vf_gate=types.SimpleNamespace())
    note(orch, "visual_fidelity", "attempts=? plateau_rounds=? judged=? deferred_s=0")
    row = json.loads((d / "logs" / "delivery_hold.jsonl").read_text(encoding="utf-8").strip())
    assert row["hold"] == "visual_fidelity"


def test_the_thresholds_this_is_measuring_are_still_what_the_docstring_says():
    """If the plateau constants move, the rationale above needs rereading -- this fails so
    someone does."""
    from multi_agent import orchestrator as orch_mod
    assert orch_mod.VISUAL_PLATEAU_ROUNDS == 4
    assert orch_mod.VISUAL_PLATEAU_HARD_ROUNDS == 8
