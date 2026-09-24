r"""#1202bi: the frontend lane is told about the projector only after it loses work.

#914/#1020 keeps a page that imports `../components/` and replaces one that does not, and
that is a fact only the framework holds. Nothing told the lane. It learns by losing:
#1202at fires after the THIRD clobber, and #1202bc after the drift has already shipped.

netflix-r32's 138-line GenresPage was replaced by a 66-line projection three times and now
survives in neither worktree nor on any branch — checked, not assumed.

Neither frontend-design nor ui-bootstrap mentioned projection, overwriting or clobbering
before this. The rule is the same action #1202at and #1202bc ask for after the fact, moved
to where it costs nothing.
"""
import sys
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
_SKILLS = (THIS_DIR.parent / "env_generator" / "llm_generator" / "multi_agent"
           / "bundled_skills")


def _skill():
    return (_SKILLS / "frontend-design" / "SKILL.md").read_text(encoding="utf-8")


class SkillSaysHowAPageSurvivesTests(unittest.TestCase):
    def test_the_rule_is_present(self):
        self.assertIn("../components/", _skill())

    def test_it_names_the_mechanism_not_just_the_advice(self):
        """A rule without its reason gets ignored the first time it is inconvenient."""
        s = _skill()
        self.assertIn("#914/#1020", s)
        self.assertIn("every scaffold pass", s)

    def test_it_carries_the_measurement(self):
        """The other rules in this file quote what they cost; this one should too."""
        s = _skill()
        self.assertIn("138-line", s)
        self.assertIn("66-line", s)

    def test_it_ties_the_action_to_the_drift_finding(self):
        """One action fixes COMPONENT DRIFT and survives the projector — say so."""
        self.assertIn("COMPONENT DRIFT", _skill())

    def test_the_prop_rule_still_quotes_a_current_number(self):
        """152 in 47 of 117 — re-measured with the current detector, still exact."""
        s = _skill()
        self.assertIn("152", s)
        self.assertIn("47 of them", s)


if __name__ == "__main__":
    unittest.main()
