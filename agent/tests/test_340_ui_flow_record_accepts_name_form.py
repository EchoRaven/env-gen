"""#340: the ui_flow gate must accept the record an agent can actually write.

`_index_ui_flow_records` keys ONLY on `record["metadata"]["check"] == "ui_flow"`
plus `metadata["flow"]`. It never looks at the record NAME.

But no agent tool can produce that metadata:
  * `record_validation_result(..., metadata={...})` -- what the gate text told
    agents to call, and what this indexer is shaped for -- is a HubRegistry
    METHOD, not a registered tool. Agents attempted it 35 times across
    r91/r92/r93 and could never call it.
  * `codehub_record_check` IS the agent-facing recorder, and its schema has
    exactly {pr_id, name, status, evidence} -- NO metadata parameter. Its own
    description says "Use the colon-prefixed form the orchestrator delivery
    gate reads", which for ui_flow was simply not true.

So `deliverability_ui_flow_missing` was unsatisfiable by construction. It was
the standing blocker in r91 for ~4 hours and was dispatched 18 times across the
three runs, always to the verifier, which could not clear it with any tool it
held.

Fix the READER, not the tool surface: accept `validation:ui_flow:<flow>` in the
record name as an equivalent identification. The metadata form keeps working
unchanged, so every existing framework-written record is unaffected.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


class _Reg:
    def __init__(self, results):
        self._r = results

    def get_validation_results(self, limit=1000):
        return self._r


def _index(results):
    from multi_agent.runtime.flow_coverage import _index_ui_flow_records
    return _index_ui_flow_records(_Reg(results))


class TheNameFormIsAccepted(unittest.TestCase):
    """What codehub_record_check can actually write."""

    def test_colon_prefixed_name_identifies_the_flow(self):
        self.assertEqual(
            _index([{"name": "validation:ui_flow:fyp_feed", "status": "passed"}]),
            {"fyp_feed": "passed"})

    def test_name_form_failure_is_recorded(self):
        self.assertEqual(
            _index([{"name": "validation:ui_flow:signup", "status": "failed"}]),
            {"signup": "failed"})

    def test_a_flow_name_containing_colons_keeps_its_tail(self):
        self.assertEqual(
            _index([{"name": "validation:ui_flow:a:b", "status": "passed"}]),
            {"a:b": "passed"})

    def test_unrelated_validation_records_are_ignored(self):
        self.assertEqual(
            _index([{"name": "validation:api_smoke", "status": "passed"}]), {})

    def test_empty_flow_tail_is_ignored(self):
        self.assertEqual(
            _index([{"name": "validation:ui_flow:", "status": "passed"}]), {})


class TheMetadataFormStillWorks(unittest.TestCase):
    """Every framework-written record must be unaffected."""

    def test_metadata_form_unchanged(self):
        self.assertEqual(
            _index([{"status": "passed",
                     "metadata": {"check": "ui_flow", "flow": "login_modal"}}]),
            {"login_modal": "passed"})

    def test_metadata_wins_nothing_and_loses_nothing_when_mixed(self):
        got = _index([
            {"status": "passed", "metadata": {"check": "ui_flow", "flow": "a"}},
            {"name": "validation:ui_flow:b", "status": "passed"},
        ])
        self.assertEqual(got, {"a": "passed", "b": "passed"})

    def test_passed_still_wins_over_a_later_failure(self):
        got = _index([
            {"name": "validation:ui_flow:x", "status": "passed"},
            {"name": "validation:ui_flow:x", "status": "failed"},
        ])
        self.assertEqual(got, {"x": "passed"})

    def test_non_ui_flow_metadata_ignored(self):
        self.assertEqual(
            _index([{"status": "passed",
                     "metadata": {"check": "api_smoke", "flow": "z"}}]), {})


if __name__ == "__main__":
    unittest.main()
