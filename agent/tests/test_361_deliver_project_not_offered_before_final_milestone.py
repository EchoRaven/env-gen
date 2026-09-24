"""#361: stop offering deliver_project when the framework knows it will refuse it.

`deliver_project` is force-offered every round, and its body then rejects the
call when the run is not on its last milestone:

    "deliver_project is the FINAL delivery and ENDS the run, but this is NOT
     the last milestone. Do NOT call deliver_project yet"

That condition is known BEFORE the tool is offered -- the runtime stamps
`_is_final_milestone` onto the agent per milestone, which is the very attribute
the guard reads. Across r91/r92/r93 there were 53 deliver_project attempts and
ZERO successes; 41 of the rejections were this guard alone (r91 21, r92 10,
r93 4). Offering a tool whose refusal is predetermined trains the model to
retry it.

The framework already gates this tool on a DIFFERENT axis at offer time --
`_KICKOFF_DEFER_TOOLS` withholds the delivery/validation set until the run is
validation-ready. This adds the milestone axis to the same place rather than
inventing a second mechanism.

Fail-open on purpose: `_is_final_milestone` defaults to True when unstamped,
exactly as the guard itself defaults, so an agent the runtime has not stamped
keeps the tool. Getting that backwards would hide delivery forever and no run
could ever finish.
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

DELIVERY = {"deliver_project", "submit_retro", "report_completion"}


def _withhold(agent):
    from multi_agent.agents.runtime.step_pipeline.tooling import (
        withhold_delivery_before_final_milestone)
    return withhold_delivery_before_final_milestone(agent)


class _Agent:
    def __init__(self, final=None):
        if final is not None:
            self._is_final_milestone = final


class BeforeTheFinalMilestone(unittest.TestCase):

    def test_delivery_is_withheld(self):
        self.assertTrue(_withhold(_Agent(final=False)))


class OnTheFinalMilestone(unittest.TestCase):

    def test_delivery_is_offered(self):
        self.assertFalse(_withhold(_Agent(final=True)))


class FailOpenWhenUnknown(unittest.TestCase):
    """Hiding delivery on a bad signal would make the run unfinishable."""

    def test_unstamped_agent_keeps_the_tool(self):
        self.assertFalse(_withhold(_Agent()))

    def test_matches_the_guards_own_default(self):
        """The guard reads getattr(agent, '_is_final_milestone', True)."""
        from tools import agent_interaction_tools
        src = Path(agent_interaction_tools.__file__).read_text()
        self.assertIn('getattr(self.agent, "_is_final_milestone", True)', src)

    def test_a_junk_signal_is_treated_as_final(self):
        a = _Agent()
        a._is_final_milestone = "yes"     # not a bool
        self.assertFalse(_withhold(a))


class ItIsWiredIntoTheOfferPath(unittest.TestCase):

    def test_the_stage_tooling_calls_it(self):
        from multi_agent.agents.runtime.step_pipeline import tooling
        src = Path(tooling.__file__).read_text()
        self.assertIn("withhold_delivery_before_final_milestone", src)

    def test_the_withheld_set_is_the_delivery_flow(self):
        from multi_agent.agents.runtime.step_pipeline.tooling import (
            _DELIVERY_UNTIL_FINAL_MILESTONE)
        self.assertIn("deliver_project", _DELIVERY_UNTIL_FINAL_MILESTONE)

    def test_it_does_not_withhold_unrelated_tools(self):
        from multi_agent.agents.runtime.step_pipeline.tooling import (
            _DELIVERY_UNTIL_FINAL_MILESTONE)
        for keep in ("finish", "check_inbox", "run_validation", "workhub_task"):
            self.assertNotIn(keep, _DELIVERY_UNTIL_FINAL_MILESTONE)


if __name__ == "__main__":
    unittest.main()
