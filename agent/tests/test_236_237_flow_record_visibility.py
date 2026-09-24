"""#236/#237 (tiktok r26 no-convergence abort, live): the verifier recorded 35
SUCCESS checks named exactly ``validation:ui_flow:<required_flow>`` — and every
one was INVISIBLE to flow_coverage because the records carried bare evidence
(no metadata.check/.flow), which is the only thing the reader trusted. The gate
held a fully-green run on ``deliverability_ui_flow_missing`` to the 122-min
abort. Plus: the page-derived required set carried suffix TWINS
(``explore`` + ``explore_page``) doubling the endgame burden to 31 flows, and a
post-abort failed record under one spelling could mask its passed twin.

Offline replay of the r26 hubs with these fixes: required 31→23,
missing 31→0, passed 23/23 — the run would have delivered at 00:33.
"""
from __future__ import annotations

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

from multi_agent.runtime.flow_coverage import (  # noqa: E402
    _extract_required_flows,
    _flow_key,
    compute_flow_coverage,
)
from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402


def _write_pages_spec(crdt: HubRegistry, page_names: list) -> None:
    meeting = crdt.workhub.create_meeting(
        agenda="kickoff", attendees=["frontend"], milestone_index=1,
        agent="orchestrator")
    crdt.workhub.add_meeting_decision(
        meeting_id=meeting["id"],
        decision={"section": "frontend", "agent": "frontend", "round": 1,
                  "content": {"user_flows": [],
                              "ui_pages": [{"name": n} for n in page_names]}},
        agent="frontend", milestone_index=1)


def _bare_check(crdt: HubRegistry, name: str, status: str, evidence=None) -> None:
    """The r26 writer shape: name carries everything, evidence is bare."""
    crdt.codehub.record_check(pr_id="main", name=name, status=status,
                              evidence=evidence or {}, agent="verifier")


class HubFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.hub = HubRegistry(Path(self.tmp))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class T236NameDerivedMetadata(HubFixture):
    def test_bare_ui_flow_check_becomes_gate_visible(self):
        _bare_check(self.hub, "validation:ui_flow:explore", "success")
        recs = self.hub.get_validation_results(limit=100)
        ui = [r for r in recs if r["metadata"].get("check") == "ui_flow"]
        self.assertEqual(len(ui), 1)
        self.assertEqual(ui[0]["metadata"].get("flow"), "explore")
        self.assertEqual(ui[0]["status"], "passed")   # 'success' canon

    def test_explicit_metadata_wins_over_name(self):
        _bare_check(self.hub, "validation:ui_flow:explore", "success",
                    evidence={"metadata": {"check": "ui_flow", "flow": "custom"}})
        recs = self.hub.get_validation_results(limit=100)
        ui = [r for r in recs if r["metadata"].get("check") == "ui_flow"]
        self.assertEqual(ui[0]["metadata"].get("flow"), "custom")

    def test_two_segment_name_gets_check_only(self):
        _bare_check(self.hub, "validation:api_smoke", "success")
        recs = self.hub.get_validation_results(limit=100)
        smoke = [r for r in recs if r["metadata"].get("check") == "api_smoke"]
        self.assertEqual(len(smoke), 1)
        self.assertNotIn("flow", smoke[0]["metadata"])


class T237SuffixTwins(HubFixture):
    def test_flow_key_normalizes_suffixes(self):
        self.assertEqual(_flow_key("explore_page"), "explore")
        self.assertEqual(_flow_key("explore_screen"), "explore")
        self.assertEqual(_flow_key("Explore"), "explore")
        self.assertEqual(_flow_key("_page"), "_page")       # never empty
        self.assertEqual(_flow_key("messages"), "messages")  # untouched

    def test_required_set_dedupes_suffix_twins(self):
        spec = {"pages": [{"name": "explore"}, {"name": "explore_page"},
                          {"name": "messages"}]}
        names, source = _extract_required_flows(spec)
        self.assertEqual(source, "pages")
        self.assertEqual(names, ["explore", "messages"])

    def test_record_under_either_spelling_satisfies_flow(self):
        _write_pages_spec(self.hub, ["for_you_feed", "explore"])
        _bare_check(self.hub, "validation:ui_flow:for_you_feed_page", "success")
        _bare_check(self.hub, "validation:ui_flow:explore", "success")
        rep = compute_flow_coverage(self.hub, None)
        self.assertEqual(rep.missing, [])
        self.assertEqual(sorted(rep.passed), ["explore", "for_you_feed"])

    def test_passed_twin_beats_failed_exact(self):
        # r26: for_you_feed FAILED at 00:41 (post-abort noise) while its
        # for_you_feed_page twin PASSED at 00:32 — the journey is green.
        _write_pages_spec(self.hub, ["for_you_feed"])
        _bare_check(self.hub, "validation:ui_flow:for_you_feed", "failure")
        _bare_check(self.hub, "validation:ui_flow:for_you_feed_page", "success")
        rep = compute_flow_coverage(self.hub, None)
        self.assertEqual(rep.passed, ["for_you_feed"])
        self.assertEqual(rep.failed, [])

    def test_failed_flow_still_fails_without_passing_twin(self):
        _write_pages_spec(self.hub, ["for_you_feed"])
        _bare_check(self.hub, "validation:ui_flow:for_you_feed", "failure")
        rep = compute_flow_coverage(self.hub, None)
        self.assertEqual(rep.failed, ["for_you_feed"])
        self.assertEqual(rep.passed, [])


if __name__ == "__main__":
    unittest.main()
