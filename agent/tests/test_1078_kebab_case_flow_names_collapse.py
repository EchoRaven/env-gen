"""#1078 — a kebab-case flow name is truncated to its FIRST word, so distinct journeys
share one key and the passed-wins collapse erases a real failure.

`_flow_key` truncates at the first non-`[a-z0-9_]` character. That rule arrived with #1049
for a good reason — `codehub_record_check` takes free-text and the verifier writes SENTENCES
into it (`"landing navigation"`), and the leading token IS the journey when the tail is
prose. But a HYPHEN is not prose: `view-profile` is ONE identifier in kebab-case, and
truncating it yields `view`.

Measured on the 67-run corpus (371 `validation:ui_flow` records, 182 distinct names), 12
names are kebab-case, and in tiktok-r51 they collapse wholesale:

    view-activity  view-explore  view-for-you-feed
    view-live      view-messages view-profile          -> ALL key to `view`
    interact-follow  interact-video-comments  interact-video-like  -> ALL key to `interact`
    saved-lists_page                                    -> keys to `saved`

`compute_flow_coverage` then folds records into `by_key` with a PASSED-WINS rule (r26: a
passing `for_you_feed_page` must clear its failing `for_you_feed` twin — correct for two
spellings of ONE journey). Applied across SIX different journeys it does the opposite of
what it was built for: one passing record marks all six covered, and a genuine failure
disappears. That is the exact direction #357 exists to protect — *"a later FAILING record
could never clear an earlier pass … which is the entire purpose of a regression gate"*.

The fix is one normalization, not a heuristic: `-` is an identifier separator, so fold it to
`_` BEFORE the prose truncation. Keys become strictly MORE distinct — the change can never
merge two journeys, only stop merging them. #1049's prose rule is untouched because prose is
separated by SPACES, which still truncate (`Browse For-You feed logged out` -> `browse`).

SCOPE, stated because the corpus makes it easy to overclaim: this does NOT make r51's
records satisfy r51's requirements. Those are page-derived (`activity`, `explore`,
`profile`) while the verifier wrote `view-activity`, `view-explore`, `view-profile` — a
LEADING-VERB mismatch that no separator rule can bridge. Stripping a verb would need a word
list, which is the shape this project has rejected before (`_AGG`, 0 triggers in 201 runs),
and the evidence for it is one run. What is fixed here is the collision and the false green
it can produce.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime.flow_coverage import _flow_key, compute_flow_coverage  # noqa: E402
from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402


def _write_spec_ui(crdt, critical_flows) -> None:
    workhub = crdt.workhub
    meeting = workhub.create_meeting(agenda="kickoff", attendees=["frontend"],
                                     milestone_index=1, agent="orchestrator")
    workhub.add_meeting_decision(
        meeting_id=meeting["id"],
        decision={"section": "frontend", "agent": "frontend", "round": 1,
                  "content": {"user_flows": [{"name": n, "critical": True}
                                             for n in critical_flows],
                              "ui_pages": []}},
        agent="frontend", milestone_index=1)


def _record(crdt, flow_name: str, status: str) -> None:
    crdt.record_validation_result(
        task_id=f"ui_flow_{flow_name}", status=status, agent="task_runner",
        summary=f"flow {flow_name}: {status}", execution_mode="browser",
        metadata={"check": "ui_flow", "flow": flow_name})


class AHyphenIsASeparatorNotProse(unittest.TestCase):

    def test_kebab_and_snake_are_the_same_journey(self):
        self.assertEqual(_flow_key("view-profile"), _flow_key("view_profile"))

    def test_the_six_r51_journeys_keep_six_keys(self):
        """The measured collapse: all six read `view` today."""
        names = ["view-activity", "view-explore", "view-for-you-feed",
                 "view-live", "view-messages", "view-profile"]
        keys = {_flow_key(n) for n in names}
        self.assertEqual(len(keys), 6, f"distinct journeys share a key: {sorted(keys)}")

    def test_the_three_interact_journeys_keep_three_keys(self):
        names = ["interact-follow", "interact-video-comments", "interact-video-like"]
        self.assertEqual(len({_flow_key(n) for n in names}), 3)

    def test_suffix_folding_still_applies_across_the_hyphen(self):
        """#237/#285 fold `_page`/`_screen`/`_ui`; a kebab name must reach them."""
        self.assertEqual(_flow_key("saved-lists_page"), "saved_lists")
        self.assertEqual(_flow_key("explore-grid-page"), "explore_grid")
        self.assertEqual(_flow_key("live-discover-page-ui"), "live_discover")


class ProseTruncationIsUntouched(unittest.TestCase):
    """#1049's rule keys off SPACES, which still truncate."""

    def test_a_sentence_still_yields_its_leading_token(self):
        self.assertEqual(_flow_key("Browse For-You feed logged out"), "browse")
        self.assertEqual(_flow_key("landing navigation"), "landing")
        self.assertEqual(_flow_key("browse_home after landing/login"), "browse_home")

    def test_the_established_suffix_cases_still_hold(self):
        self.assertEqual(_flow_key("explore_page"), "explore")
        self.assertEqual(_flow_key("following_suggested_creators_page_ui"),
                         "following_suggested_creators")
        self.assertEqual(_flow_key("profiles_guarded"), "profiles_guarded")


class AFailureCannotHideBehindASibling(unittest.TestCase):
    """The consequence at the gate — this is what the collapse costs."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="flow_1078_"))
        self.reg = HubRegistry(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_failing_kebab_flow_is_reported_failed_not_passed(self):
        _write_spec_ui(self.reg, ["view-profile", "view-live"])
        _record(self.reg, "view-profile", "passed")
        _record(self.reg, "view-live", "failed")
        report = compute_flow_coverage(self.reg, self.tmp)
        self.assertEqual(report.passed, ["view-profile"])
        self.assertEqual(report.failed, ["view-live"],
                         "a passing sibling cleared a different journey's failure")
        self.assertFalse(report.is_clean)

    def test_a_kebab_record_still_clears_its_own_requirement(self):
        _write_spec_ui(self.reg, ["view-profile"])
        _record(self.reg, "view-profile", "passed")
        report = compute_flow_coverage(self.reg, self.tmp)
        self.assertEqual(report.passed, ["view-profile"])
        self.assertTrue(report.is_clean)

    def test_a_snake_requirement_is_cleared_by_a_kebab_record(self):
        """The two spellings of ONE journey must still meet."""
        _write_spec_ui(self.reg, ["view_profile"])
        _record(self.reg, "view-profile", "passed")
        report = compute_flow_coverage(self.reg, self.tmp)
        self.assertEqual(report.passed, ["view_profile"])


if __name__ == "__main__":
    unittest.main()
