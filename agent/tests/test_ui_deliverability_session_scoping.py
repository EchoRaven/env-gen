"""PR 6 reviewer follow-up (2026-05-30): the UI's
``deliverability_report_call`` and ``deliver_project_call`` used
to pass ``session_start_ts=0.0`` to ``compute_deliverability``,
which made ``runhub.last_successful_run_since(0.0)`` equivalent to
"has there ever been a successful run", not "since THIS session".
On ``--no-fresh`` workspaces (reused across runs) a stale
historical successful run could fool the UI into marking the
project complete — same family as the retro-gate generation-scoping
bug we fixed three rounds ago, just on the UI deliver path instead
of the autonomous one.

Fix: read ``<workspace>/run_budget.json::usage.started_at`` (the
orchestrator writes it at the top of ``run()`` and refreshes it
each tick) and pass that to ``compute_deliverability`` from both
UI call sites.

These tests pin:
  * stale pre-session run + fresh run_budget.json → UI says
    "blocked" (the bug-case the reviewer flagged)
  * fresh in-session run → UI says "deliverable" (no regression
    on the green path)
  * missing run_budget.json → falls back to 0.0 (preserves
    historical behaviour for pre-orchestrator-startup UI calls)
  * malformed run_budget.json → same fallback
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402
from live_monitor_server import _session_start_ts_for_project  # noqa: E402


def _add_retro(reg, gen_id: float = 1.0):
    """Minimal retro page so the retro blocker doesn't dominate
    the verdict. Tests of OTHER dimensions need retro present."""
    reg.workhub.create_document(
        title="r", agent="orchestrator", kind="retro",
        metadata={"generation_id": gen_id, "plan_vs_reality": [],
                  "lessons": [], "proposed_prompt_changes": []})


def _record_run(reg, *, started_at: float, status: str = "completed",
                fail_count: int = 0):
    r = reg.runhub.record_run(branch="x", generated_dir="/g",
                              agent="orchestrator")
    raw = reg.runhub.stores.runs.get(r["id"])
    raw["started_at"] = started_at
    raw["status"] = status
    raw["fail_count"] = fail_count
    raw["probes"] = []
    raw["mcp_probes"] = []
    reg.runhub.stores.runs.update(
        lambda m: m.set(r["id"], raw, "runhub"),
        change_info={"agent": "runhub"},
    )


def _write_run_budget(workspace: Path, started_at: float):
    """Mimic what ``Orchestrator._write_run_budget`` writes at the
    top of run(). Only the ``usage.started_at`` field is
    load-bearing for this test."""
    payload = {
        "caps": {"max_wall_sec": 7200.0, "max_ticks": 240,
                 "unlimited": False},
        "usage": {
            "started_at": started_at,
            "elapsed_sec": 0.0,
            "ticks": 0,
            "status": "running",
            "updated_at": started_at,
        },
    }
    (workspace / "run_budget.json").write_text(json.dumps(payload))


class SessionStartHelperReadsRunBudget(unittest.TestCase):
    def test_missing_file_returns_zero(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(_session_start_ts_for_project(Path(td)), 0.0)

    def test_well_formed_file_returns_started_at(self):
        with tempfile.TemporaryDirectory() as td:
            _write_run_budget(Path(td), started_at=5000.0)
            self.assertEqual(
                _session_start_ts_for_project(Path(td)), 5000.0,
            )

    def test_malformed_json_returns_zero(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "run_budget.json").write_text("{not valid json")
            self.assertEqual(_session_start_ts_for_project(Path(td)), 0.0)

    def test_missing_usage_returns_zero(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "run_budget.json").write_text(
                json.dumps({"caps": {}})
            )
            self.assertEqual(_session_start_ts_for_project(Path(td)), 0.0)

    def test_non_numeric_started_at_returns_zero(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "run_budget.json").write_text(
                json.dumps({"usage": {"started_at": "abc"}})
            )
            self.assertEqual(_session_start_ts_for_project(Path(td)), 0.0)

    def test_bool_started_at_returns_zero(self):
        """Defensive: ``isinstance(True, (int, float))`` is True
        in Python — explicitly reject bool so a stray True/False
        doesn't slip through as 1.0/0.0."""
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "run_budget.json").write_text(
                json.dumps({"usage": {"started_at": True}})
            )
            self.assertEqual(_session_start_ts_for_project(Path(td)), 0.0)


class UIDeliverabilityRespectsSessionScope(unittest.TestCase):
    """The reviewer's bug-case: a stale historical successful run
    used to satisfy the UI's deliverability verdict. After the
    fix, a fresh ``run_budget.json`` with started_at AFTER the
    stale run's started_at correctly excludes it."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="ui_deliv_scope_"))
        self.reg = HubRegistry(self.tmp)
        _add_retro(self.reg, gen_id=2000.0)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_stale_pre_session_run_does_not_satisfy_ui_verdict(self):
        """Reviewer's exact bug-case: workspace has a run from
        time=500 (a previous session); the current orchestrator
        session started at time=2000 (written to run_budget.json).
        UI deliverability MUST report blocked — the historical
        run is older than session start, so it doesn't count."""
        # Stale historical run.
        _record_run(self.reg, started_at=500.0)
        # Fresh session began at time=2000.
        _write_run_budget(self.tmp, started_at=2000.0)
        # Probe the deliverability with the session-scoped start.
        from multi_agent.runtime.deliverability import compute_deliverability
        session_start = _session_start_ts_for_project(self.tmp)
        report = compute_deliverability(
            self.reg, self.tmp, session_start_ts=session_start,
        )
        self.assertEqual(
            report.verdict, "blocked",
            f"stale run silently satisfied the UI verdict; "
            f"blockers={report.blockers}",
        )
        # Specifically: the run-since-session blocker should be present.
        joined = " ".join(report.blockers).lower()
        self.assertIn("no successful runhub run since session", joined)

    def test_fresh_in_session_run_satisfies_ui_verdict(self):
        """Counterpart: a run AFTER session_start does count.
        Asserts the fix isn't over-correcting (no regression on
        the green path)."""
        # Fresh session began at time=2000.
        _write_run_budget(self.tmp, started_at=2000.0)
        # Run AFTER session start.
        _record_run(self.reg, started_at=2500.0)
        # Topology so other blockers don't dominate.
        self.reg.registryhub.register_endpoint(
            "GET", "/health", schema={},
            provider="backend", agent="backend", status="implemented",
        )
        self.reg.schema_hub.register_table(
            name="users", schema={"id": "int"},
            provider="backend", agent="backend", status="implemented",
        )
        self.reg.workhub.update_ui_page(
            "home", {"status": "implemented"}, agent="frontend",
        )
        # Pull session_start from the live helper (not the literal)
        # so we test the integration as the UI sees it.
        from multi_agent.runtime.deliverability import compute_deliverability
        session_start = _session_start_ts_for_project(self.tmp)
        report = compute_deliverability(
            self.reg, self.tmp, session_start_ts=session_start,
        )
        # If the runhub-scope check passes, the run-since-session
        # blocker must NOT be in the list. Other dimensions (visual,
        # seed) may still be there — we don't require deliverable
        # verdict; we require the SPECIFIC run-scoping blocker is
        # gone, proving the fix doesn't over-correct.
        joined = " ".join(report.blockers).lower()
        self.assertNotIn(
            "no successful runhub run since session", joined,
            "fresh in-session run was incorrectly rejected; "
            f"blockers={report.blockers}",
        )

    def test_no_run_budget_yet_falls_back_to_historical(self):
        """Edge case: UI calls deliverability BEFORE the
        orchestrator has ever started (no run_budget.json yet).
        Behaviour: fall back to session_start=0.0 → any historical
        run satisfies the runhub dimension. Preserves the
        pre-fix behaviour for this specific edge case so the fix
        is strictly tighter, never looser."""
        # No run_budget.json — but a historical run exists.
        _record_run(self.reg, started_at=500.0)
        from multi_agent.runtime.deliverability import compute_deliverability
        session_start = _session_start_ts_for_project(self.tmp)
        self.assertEqual(session_start, 0.0)
        report = compute_deliverability(
            self.reg, self.tmp, session_start_ts=session_start,
        )
        joined = " ".join(report.blockers).lower()
        self.assertNotIn(
            "no successful runhub run since session", joined,
            "fallback to 0.0 should let a historical run satisfy "
            "the runhub dimension; got an unexpected blocker.",
        )


if __name__ == "__main__":
    unittest.main()
