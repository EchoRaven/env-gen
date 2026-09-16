"""#1202pn: deliverability_check states the delivery gate's latest verdict, so the
orchestrator cannot read "deliverable" while the gate is refusing and cancel the gate's
repair tasks as stale (r125 20/73, r126 10/30)."""
import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "env_generator" / "llm_generator"))

import tools.deliverability_tools as dt  # noqa: E402


class _Report:
    verdict = "deliverable"
    blockers = []

    def to_dict(self):
        return {"verdict": "deliverable", "blockers": []}


def _run(tmp_path, monkeypatch, line):
    run = tmp_path / "run"
    (run / "app" / "backend").mkdir(parents=True)
    (run / "logs").mkdir()
    if line is not None:
        (run / "logs" / "delivery_gate.jsonl").write_text(
            json.dumps({"ok": True, "failed_checks": [], "at": time.time() - 5000}) + "\n"
            + json.dumps(line) + "\n")
    monkeypatch.setattr(dt, "compute_deliverability", lambda *a, **k: _Report())
    tool = dt.DeliverabilityCheckTool(app_root=str(run / "app"))
    return asyncio.run(tool.execute()).data


def test_a_fresh_failing_gate_is_stated(tmp_path, monkeypatch):
    data = _run(tmp_path, monkeypatch,
                {"ok": False, "failed_checks": ["business_chain_failing"], "at": time.time() - 30})
    assert data["delivery_gate_latest"]["ok"] is False
    assert "business_chain_failing" in data["delivery_gate_note"]
    assert "do not cancel" in data["delivery_gate_note"]


def test_a_passing_gate_adds_no_note(tmp_path, monkeypatch):
    data = _run(tmp_path, monkeypatch, {"ok": True, "failed_checks": [], "at": time.time()})
    assert data["delivery_gate_latest"]["ok"] is True
    assert "delivery_gate_note" not in data


def test_a_stale_or_missing_ledger_says_nothing(tmp_path, monkeypatch):
    stale = _run(tmp_path, monkeypatch,
                 {"ok": False, "failed_checks": ["x"], "at": time.time() - 99999})
    assert "delivery_gate_latest" not in stale
    missing = _run(tmp_path / "b", monkeypatch, None)
    assert "delivery_gate_latest" not in missing
