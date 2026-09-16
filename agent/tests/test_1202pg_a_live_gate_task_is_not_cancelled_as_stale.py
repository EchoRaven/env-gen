"""#1202pg: the orchestrator cannot cancel the framework's gate repair task while the gate fails on it.

`compute_deliverability` tells the orchestrator the app is deliverable without reading the
framework gate's failures, so it judged "Make business_chain pass (blocks delivery)" stale and
cancelled it, and the gate re-dispatched it: 20 of r125's 73 gate-fix tasks and 10 of r126's 30
were cancelled by the orchestrator; r125's log carries 154 GATE-CHECK re-dispatches.
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402


def _run(tmp_path, ledger_row):
    hr = HubRegistry(tmp_path)          # creates <tmp>/shared/hubs itself
    t = hr.workhub.create_task(title="Make business_chain pass (blocks delivery)",
                               description="x", assignee="verifier", agent="orchestrator",
                               priority="P0")
    if ledger_row is not None:
        (tmp_path / "logs").mkdir()
        (tmp_path / "logs" / "delivery_gate.jsonl").write_text(json.dumps(ledger_row) + "\n")
    tid = t.get("id") if isinstance(t, dict) else t
    return hr.workhub.cancel_task(tid, agent="orchestrator", reason="stale expectation drift")


def test_r126_cancel_is_refused_while_the_gate_still_fails_business_chain(tmp_path):
    out = _run(tmp_path, {"at": time.time(), "failed_checks": ["business_chain_failing"],
                          "business_chain": {"chains": ["video_saves_page"]}})
    assert "error" in out and "video_saves_page" in out["error"], out


def test_it_is_allowed_once_the_gate_no_longer_fails_on_it(tmp_path):
    out = _run(tmp_path, {"at": time.time(), "failed_checks": ["validation_ui_evidence_failed"]})
    assert "error" not in out, out


def test_a_stale_or_missing_ledger_never_refuses(tmp_path):
    assert "error" not in _run(tmp_path, None)


def test_a_stale_ledger_never_refuses(tmp_path):
    out = _run(tmp_path, {"at": time.time() - 7200, "failed_checks": ["business_chain_failing"]})
    assert "error" not in out, out
