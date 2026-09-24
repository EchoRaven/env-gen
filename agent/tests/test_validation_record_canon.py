"""Guard: FIX #193 — canonical validation-record shape at the read boundary.

Diagnosed on instagram SUCCESS-run80's REAL archive: validation: checks carry
status='success' (writers pass whatever vocabulary the agent used) and the
check kind sits NESTED at evidence.metadata.check — while every reader
(_has_passing_ui_evidence, flow_coverage._index_ui_flow_records, the retry
decider, remediation-task creation, get_validation_summary buckets) compares
status=='passed' and reads metadata.get('check'). Result: ui_flow records were
INVISIBLE to all of them; the UI gates cleared only via the
functionally_validated waiver, and ENVGEN_REQUIRE_UI_EVIDENCE=1 would have
blocked every delivery unconditionally.

Fix: normalize once in hub_registry.get_validation_results (status vocabulary
+ nested-metadata flatten), harden the writer to canonical vocabulary, then
flip ENVGEN_REQUIRE_UI_EVIDENCE default ON.
"""

import sys
import unittest
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402
from multi_agent.runtime.deliverability import _has_passing_ui_evidence  # noqa: E402
from multi_agent.runtime.flow_coverage import _index_ui_flow_records  # noqa: E402


class _FakeCodeHub:
    """Serves run80-SHAPED records: status='success', check nested under
    evidence['metadata']."""

    def __init__(self, checks):
        self._checks = checks

    def list_checks(self):
        return self._checks

    def record_check(self, **kw):
        self.recorded = kw
        return kw


def _hub(checks):
    hr = HubRegistry.__new__(HubRegistry)  # bypass __init__; method needs .codehub only
    hr.codehub = _FakeCodeHub(checks)
    return hr


_RUN80_UI_FLOW = {
    "name": "validation:ui_flow:auth_register_login", "status": "success",
    "agent": "verifier", "updated_at": 1, "pr_id": "main",
    "evidence": {"flow_completed": True,
                 "metadata": {"check": "ui_flow", "flow": "auth_register_login"}},
}


class CanonicalReadTests(unittest.TestCase):
    def test_success_status_reads_as_passed(self):
        recs = _hub([_RUN80_UI_FLOW]).get_validation_results()
        self.assertEqual(recs[0]["status"], "passed")

    def test_failure_status_reads_as_failed(self):
        c = dict(_RUN80_UI_FLOW, status="failure")
        recs = _hub([c]).get_validation_results()
        self.assertEqual(recs[0]["status"], "failed")

    def test_nested_metadata_check_is_flattened(self):
        recs = _hub([_RUN80_UI_FLOW]).get_validation_results()
        self.assertEqual(recs[0]["metadata"].get("check"), "ui_flow")
        self.assertEqual(recs[0]["metadata"].get("flow"), "auth_register_login")

    def test_top_level_keys_win_over_nested(self):
        c = {"name": "validation:x", "status": "success",
             "evidence": {"check": "ui_smoke",
                          "metadata": {"check": "SHOULD_NOT_WIN"}}}
        recs = _hub([c]).get_validation_results()
        self.assertEqual(recs[0]["metadata"].get("check"), "ui_smoke")

    def test_run80_shape_now_counts_as_ui_evidence(self):
        self.assertTrue(_has_passing_ui_evidence(_hub([_RUN80_UI_FLOW])))

    def test_no_ui_records_is_still_no_evidence(self):
        c = {"name": "validation:api_smoke", "status": "success",
             "evidence": {"metadata": {"check": "api_smoke"}}}
        self.assertFalse(_has_passing_ui_evidence(_hub([c])))

    def test_flow_coverage_indexes_run80_shape_as_passed(self):
        idx = _index_ui_flow_records(_hub([_RUN80_UI_FLOW]))
        self.assertEqual(idx.get("auth_register_login"), "passed")


class WriterHardeningTests(unittest.TestCase):
    def test_writer_canonicalizes_status(self):
        hr = _hub([])
        hr.record_validation_result("t1", "success", agent="verifier")
        self.assertEqual(hr.codehub.recorded["status"], "passed")
        hr.record_validation_result("t2", "failure", agent="verifier")
        self.assertEqual(hr.codehub.recorded["status"], "failed")


class RequireUiEvidenceDefaultTests(unittest.TestCase):
    def test_default_is_on(self):
        import os
        from multi_agent.runtime.deliverability import _require_ui_evidence
        os.environ.pop("ENVGEN_REQUIRE_UI_EVIDENCE", None)
        self.assertTrue(_require_ui_evidence())
        os.environ["ENVGEN_REQUIRE_UI_EVIDENCE"] = "0"
        try:
            self.assertFalse(_require_ui_evidence())
        finally:
            os.environ.pop("ENVGEN_REQUIRE_UI_EVIDENCE", None)


if __name__ == "__main__":
    unittest.main()
