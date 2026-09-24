"""Adversarial-review follow-up fixes for the flow-coverage gate
(PR 7, 2026-05-30). The 8-angle adversarial review of commit
6fb6a422 surfaced 6 CONFIRMED findings; this suite pins the fixes
for 5 of them (the 6th — ``root.name == 'app'`` mis-resolution when
``output_dir`` itself is named ``"app"`` — is deferred pending a
``compute_deliverability(workspace=...)`` signature change, since
inferring the workspace from a normalized app_root requires more
context than the call site currently passes).

Pinned fixes:

  1. ``Path(app_root)`` lives INSIDE the try/except so an
     ``app_root=None`` from ``DeliverabilityCheckTool`` (which has no
     outer wrapper) degrades to an empty report instead of raising
     ``TypeError`` out of ``compute_deliverability``.

  2. Token canonicalization in ``_validate_delivery_gate`` anchors on
     the FULL prefix (``"ui flow(s) failed"`` / ``"ui flow(s) missing"``)
     and checks failed FIRST, so a flow whose name contains the
     substring ``"missing"`` (e.g. ``recover_missing_password``) doesn't
     get mislabeled as ``deliverability_ui_flow_missing`` when it
     actually failed.

  3. The page ``critical`` flag is coerced through ``_is_truthy_critical``
     which recognizes stringly-typed booleans (``"true"`` / ``"false"`` /
     ``"yes"`` / ``"no"`` / ``"0"`` / ``"1"``) — fixes the truthy-string
     trap where ``"critical": "false"`` was silently flipped TO critical.

  4. A present-but-malformed ``critical_flows[]`` array (every entry
     unparseable) now surfaces as source ``"critical_flows_invalid"``
     and a dedicated blocker, instead of silently falling through to
     page-derived flows. Canonicalized as
     ``deliverability_critical_flows_invalid``.

  5. ``_flow_coverage_summary``'s degraded-path return carries
     ``"source": "degraded"`` and ``"degraded": True`` so operators
     can distinguish "gate broken" from "no flows declared".
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

from multi_agent.runtime.deliverability import (  # noqa: E402
    compute_deliverability,
    _flow_coverage_summary,
)
from multi_agent.runtime.flow_coverage import (  # noqa: E402
    _extract_required_flows,
    _is_truthy_critical,
    compute_flow_coverage,
)
from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402


def _write_spec_ui(crdt, payload: dict) -> None:
    """Populate WorkHub with the frontend section of a kickoff meeting.

    Preserves raw critical_flow entries verbatim (with ``critical=True``
    stamped on) so downstream malformed-entry detection still fires —
    mirrors the helper in ``test_flow_coverage_gate.py``.
    """
    workhub = crdt.workhub
    user_flows: list = []
    for entry in payload.get("critical_flows") or []:
        if isinstance(entry, dict):
            user_flows.append({**entry, "critical": True})
        elif isinstance(entry, str):
            user_flows.append({"name": entry, "critical": True})
    ui_pages = list(payload.get("pages") or [])
    meeting = workhub.create_meeting(
        agenda="kickoff",
        attendees=["frontend"],
        milestone_index=1,
        agent="orchestrator",
    )
    workhub.add_meeting_decision(
        meeting_id=meeting["id"],
        decision={
            "section": "frontend",
            "agent": "frontend",
            "round": 1,
            "content": {"user_flows": user_flows, "ui_pages": ui_pages},
        },
        agent="frontend",
        milestone_index=1,
    )


def _add_retro(crdt: HubRegistry, gen_id: float = 2000.0) -> None:
    crdt.workhub.create_document(
        title="r", agent="orchestrator", kind="retro",
        metadata={"generation_id": gen_id, "plan_vs_reality": [],
                  "lessons": [], "proposed_prompt_changes": []})


def _add_passing_run(crdt: HubRegistry, started_at: float = 2000.0) -> None:
    r = crdt.runhub.record_run(branch="x", generated_dir="/g",
                               agent="orchestrator")
    raw = crdt.runhub.stores.runs.get(r["id"])
    raw["started_at"] = started_at
    raw["status"] = "completed"
    raw["fail_count"] = 0
    raw["probes"] = []
    raw["mcp_probes"] = []
    crdt.runhub.stores.runs.update(
        lambda m: m.set(r["id"], raw, "runhub"),
        change_info={"agent": "runhub"},
    )


def _record_ui_flow(crdt: HubRegistry, flow_name: str, status: str) -> None:
    crdt.record_validation_result(
        task_id=f"ui_flow_{flow_name}",
        status=status,
        agent="task_runner",
        summary=f"flow {flow_name}: {status}",
        execution_mode="browser",
        metadata={"check": "ui_flow", "flow": flow_name},
    )


# -----------------------------------------------------------------------
# Fix 1: Path(app_root) inside try/except — None doesn't crash the gate
# -----------------------------------------------------------------------

class Fix1NoneAppRootDoesNotCrashDeliverability(unittest.TestCase):
    """``DeliverabilityCheckTool.execute`` may pass ``app_root=None`` when
    no workspace is wired. The flow-coverage gate must not raise on
    that input — WorkHub is the source of truth so app_root is
    unused, but the no-crash invariant still matters for tool paths."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="fix1_none_"))
        self.reg = HubRegistry(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_none_app_root_yields_empty_report_not_typeerror(self):
        report_dict, blockers = _flow_coverage_summary(self.reg, None)
        self.assertIsInstance(report_dict, dict)
        self.assertEqual(blockers, [])

    def test_compute_deliverability_with_none_app_root_doesnt_raise(self):
        # Should not raise.
        compute_deliverability(self.reg, None, session_start_ts=0.0)


# -----------------------------------------------------------------------
# Fix 2: elif-order — failed flow with "missing" in name is not
# mislabeled as ui_flow_missing
# -----------------------------------------------------------------------

class Fix2ElifOrderResolvesSubstringCollision(unittest.TestCase):
    """The reviewer found that a critical_flow whose NAME contains the
    substring ``"missing"`` (e.g. ``recover_missing_password``) would
    short-circuit on the ``"missing"`` branch even when the blocker
    was a FAILED prose. The fix anchors on the full unique prefix
    (``"ui flow(s) failed"`` / ``"ui flow(s) missing"``) and checks
    failed FIRST."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="fix2_substr_"))
        self.reg = HubRegistry(self.tmp)
        _add_retro(self.reg)
        _add_passing_run(self.reg, started_at=2000.0)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_failed_flow_named_recover_missing_password_maps_to_failed(self):
        """Concrete trigger from the review."""
        _write_spec_ui(self.reg, {
            "critical_flows": [{"name": "recover_missing_password"}],
        })
        _record_ui_flow(self.reg, "recover_missing_password", "failed")
        from multi_agent.orchestrator import Orchestrator
        orch = Orchestrator.__new__(Orchestrator)
        orch.output_dir = self.tmp
        orch.crdt_workspace = self.reg
        orch.hubs = self.reg
        orch._session_start_ts = 1000.0

        gate = orch._validate_delivery_gate()
        self.assertIn(
            "deliverability_ui_flow_failed", gate["failed_checks"],
            f"failed flow named with 'missing' must map to "
            f"deliverability_ui_flow_failed, not _missing; "
            f"got failed_checks={gate.get('failed_checks')}",
        )
        self.assertNotIn(
            "deliverability_ui_flow_missing", gate["failed_checks"],
            "the missing token must NOT fire when the flow has a "
            "(failing) record",
        )

    def test_failed_token_does_not_mask_missing_token(self):
        """Sanity: a flow that's actually missing still maps to the
        missing token. The reordering doesn't flip the other direction."""
        _write_spec_ui(self.reg, {
            "critical_flows": [{"name": "register"}],
        })
        # no record
        from multi_agent.orchestrator import Orchestrator
        orch = Orchestrator.__new__(Orchestrator)
        orch.output_dir = self.tmp
        orch.crdt_workspace = self.reg
        orch.hubs = self.reg
        # session_start AFTER the setUp run (2000.0) → not functionally-validated
        # → a MISSING ui_flow still maps to the missing token (the relaxation only
        # spares validated apps; this pins the missing↔failed token mapping).
        orch._session_start_ts = 2500.0

        gate = orch._validate_delivery_gate()
        self.assertIn(
            "deliverability_ui_flow_missing", gate["failed_checks"],
        )
        self.assertNotIn(
            "deliverability_ui_flow_failed", gate["failed_checks"],
        )


# -----------------------------------------------------------------------
# Fix 3: truthy-string trap on `critical` flag
# -----------------------------------------------------------------------

class Fix3CriticalFlagTruthyStringHardening(unittest.TestCase):
    """Bare ``if page.get("critical"):`` treats ``"false"`` as truthy.
    The new ``_is_truthy_critical`` helper coerces stringly-typed
    booleans correctly."""

    def test_helper_coerces_string_false_to_false(self):
        for v in ("false", "FALSE", "False", "no", "NO", "0", " false ", ""):
            self.assertFalse(
                _is_truthy_critical(v),
                f"_is_truthy_critical({v!r}) should be False",
            )

    def test_helper_coerces_string_true_to_true(self):
        for v in ("true", "TRUE", "True", "yes", "YES", "1", " true ", "y", "t"):
            self.assertTrue(
                _is_truthy_critical(v),
                f"_is_truthy_critical({v!r}) should be True",
            )

    def test_helper_native_bool(self):
        self.assertTrue(_is_truthy_critical(True))
        self.assertFalse(_is_truthy_critical(False))
        self.assertFalse(_is_truthy_critical(None))
        self.assertTrue(_is_truthy_critical(1))
        self.assertFalse(_is_truthy_critical(0))

    def test_helper_unknown_string_biases_critical(self):
        """Unknown non-empty string -> treat as truthy. Reason: the
        gate's failure mode for "extra blocker" is recoverable
        (designer/verifier fixes the test); the failure mode for
        "silently dropped page" is hidden bugs in production."""
        self.assertTrue(_is_truthy_critical("maybe"))
        self.assertTrue(_is_truthy_critical("required"))

    def test_extract_required_flows_with_stringly_false_critical(self):
        """End-to-end: spec writes "critical": "false" (string) — the
        page must NOT be added to the required flow set."""
        spec = {
            "pages": [
                {"name": "home", "path": "/", "critical": "false"},
                {"name": "login", "path": "/login", "critical": "true"},
            ],
        }
        required, source = _extract_required_flows(spec)
        self.assertEqual(source, "critical_pages")
        self.assertEqual(required, ["login"])


# -----------------------------------------------------------------------
# Fix 4: malformed critical_flows surfaces a blocker, doesn't silently
# fall back to page derivation
# -----------------------------------------------------------------------

class Fix4MalformedCriticalFlowsSurfaces(unittest.TestCase):
    """If ``critical_flows[]`` is present but every entry is
    unparseable (missing both ``name`` and ``id``), the old code
    silently fell through to page derivation, masking the designer's
    bug. The fix surfaces it as source ``"critical_flows_invalid"``
    and a dedicated blocker."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="fix4_invalid_"))
        self.reg = HubRegistry(self.tmp)
        _add_retro(self.reg)
        _add_passing_run(self.reg, started_at=2000.0)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_all_entries_missing_name_yields_invalid_source(self):
        spec = {
            "critical_flows": [
                {"description": "register then post", "steps": ["..."]},
                {"description": "login", "steps": ["..."]},
            ],
        }
        required, source = _extract_required_flows(spec)
        self.assertEqual(required, [])
        self.assertEqual(
            source, "critical_flows_invalid",
            "malformed critical_flows must surface as "
            "'critical_flows_invalid', not silently fall back",
        )

    def test_malformed_does_not_fall_through_to_pages(self):
        """Even if spec ALSO has critical pages, malformed
        critical_flows means the explicit-list-was-attempted intent
        is preserved — we don't silently switch to page-derivation."""
        spec = {
            "critical_flows": [{"description": "no name"}],
            "pages": [{"name": "home", "critical": True}],
        }
        required, source = _extract_required_flows(spec)
        self.assertEqual(required, [])
        self.assertEqual(source, "critical_flows_invalid")

    def test_partial_malformed_uses_valid_entries(self):
        """If SOME entries are valid, those are used and source is
        'critical_flows'. Only when ALL entries are unparseable do
        we surface 'critical_flows_invalid'."""
        spec = {
            "critical_flows": [
                {"description": "no name"},
                {"name": "register"},
            ],
        }
        required, source = _extract_required_flows(spec)
        self.assertEqual(required, ["register"])
        self.assertEqual(source, "critical_flows")

    def test_invalid_source_emits_blocker_in_deliverability(self):
        _write_spec_ui(self.reg, {
            "critical_flows": [{"description": "no name"}],
        })
        report = compute_deliverability(
            self.reg, self.tmp, session_start_ts=1000.0,
        )
        joined = " ".join(report.blockers).lower()
        self.assertIn("critical_flows", joined)
        self.assertIn("unparseable", joined)

    def test_invalid_source_canonicalizes_in_gate(self):
        from multi_agent.orchestrator import Orchestrator
        _write_spec_ui(self.reg, {
            "critical_flows": [{"description": "no name"}],
        })
        orch = Orchestrator.__new__(Orchestrator)
        orch.output_dir = self.tmp
        orch.crdt_workspace = self.reg
        orch.hubs = self.reg
        orch._session_start_ts = 1000.0

        gate = orch._validate_delivery_gate()
        self.assertIn(
            "deliverability_critical_flows_invalid",
            gate["failed_checks"],
        )

    def test_invalid_source_has_suggestion_text(self):
        from multi_agent.orchestrator import Orchestrator
        _write_spec_ui(self.reg, {
            "critical_flows": [{"description": "no name"}],
        })
        orch = Orchestrator.__new__(Orchestrator)
        orch.output_dir = self.tmp
        orch.crdt_workspace = self.reg
        orch.hubs = self.reg
        orch._session_start_ts = 1000.0

        gate = orch._validate_delivery_gate()
        suggestions = orch._delivery_gate_suggestions(gate)
        joined = "\n".join(suggestions).lower()
        self.assertIn("critical_flows", joined)
        self.assertIn("unparseable", joined)


if __name__ == "__main__":
    unittest.main()
