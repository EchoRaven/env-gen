r"""#1202bj: lanes were judged by gates their instructions never named.

Six blockers stopped delivery in the netflix/tiktok logs and NONE of them appeared in any
of the 12 bundled skills. A lane met `validation_ui_evidence_failed` for the first time in
a remediation task, after it had already failed.

Measured across 40 run logs:

    46  validation_ui_evidence_failed
    19  business_chain_failing
    13  deliverability_ui_flow_failed
     4  database_sql_missing

The frequency matters as much as the names: the top one is more than twice the next, so a
lane budgeting attention should start there. And two of the four have causes OUTSIDE the
failing lane — a refused capture is a dead stack, a chain 404 on a valid id is often a thin
contract — which is the difference between fixing it and rewriting working code.
"""
import sys
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
_SKILL = (THIS_DIR.parent / "env_generator" / "llm_generator" / "multi_agent"
          / "bundled_skills" / "release-readiness" / "SKILL.md")


def _text():
    return _SKILL.read_text(encoding="utf-8")


class SkillNamesTheBlockersTests(unittest.TestCase):
    def test_every_measured_blocker_is_named(self):
        s = _text()
        for g in ("validation_ui_evidence_failed", "business_chain_failing",
                  "deliverability_ui_flow_failed", "database_sql_missing"):
            self.assertIn(g, s, f"{g} blocked delivery and is still unnamed")

    def test_the_frequencies_are_there(self):
        """A list without weights tells a lane nothing about where to look first."""
        s = _text()
        self.assertIn("| 46 |", s)
        self.assertIn("| 19 |", s)

    def test_it_says_which_causes_live_outside_the_lane(self):
        """The point that stops a lane rewriting working code."""
        s = _text()
        self.assertIn("stack is down", s)
        self.assertIn("outside the failing lane", s)

    def test_it_keeps_the_existing_checklist(self):
        """The addition must not have displaced what the skill already taught."""
        s = _text()
        self.assertIn("Readiness checklist", s)
        self.assertIn("validation:api_smoke", s)
        self.assertIn("Output expectations", s)


if __name__ == "__main__":
    unittest.main()
