"""#359: the kickoff facilitation prompt offers actions that cannot be chosen.

`kickoff_facilitation_prompt` presents consensus / request_revision / escalate,
and states request_revision's precondition inline:

    * `{{ current_round }} < {{ max_rounds }}`

`facilitate.py` sets `KICKOFF_MAX_ROUNDS: int = 1`, so at the only round that
exists this renders as the literal `1 < 1` -- always false. escalate's FIRST
bullet is likewise unreachable: it requires a conflict that "persisted across
rounds", which needs at least two rounds.

So the chair is asked to pick from three options, one of which states its own
precondition is false, and burns its highest-value reasoning turn resolving the
contradiction. r92's orchestrator, verbatim:

    "Round budget is 1/1, so request_revision won't fit another round ...
     Re-reading the briefing more carefully: 'pick this when ... `1 < 1`' --
     that's literally false, so request[_revision]..."

Both runs then fell through to synthesize_fallback, i.e. the run's whole
contract came from the fallback path rather than the facilitator.

`current_round` and `max_rounds` are already macro parameters, so this needs no
new plumbing: render only what is reachable. escalate itself STAYS -- its other
two conditions (contradictory requirements, validation_failed) are reachable at
any round; only its cross-round bullet is hidden.

Noted while here, not changed: facilitate.py's own docstring says
"Up to KICKOFF_MAX_ROUNDS (default 3)" while the constant is 1.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

PROMPTS_ROOT = LLM_DIR / "multi_agent" / "prompts"
PROMPTS_V3 = PROMPTS_ROOT / "v3"


def _render(current_round, max_rounds):
    env = Environment(loader=FileSystemLoader([str(PROMPTS_V3), str(PROMPTS_ROOT)]))
    mod = env.get_template("orchestrator_agent.j2").make_module()
    return mod.kickoff_facilitation_prompt(
        "doc_1", 1, current_round, max_rounds, "needs_revision", [], {})


class AtTheFinalRoundRevisionIsNotOffered(unittest.TestCase):
    """KICKOFF_MAX_ROUNDS is 1, so this is what every real run renders."""

    def test_request_revision_is_absent(self):
        out = _render(1, 1)
        self.assertNotIn('* `"request_revision"` — pick this when', out)

    def test_the_impossible_inline_condition_is_gone(self):
        self.assertNotIn("1 < 1", _render(1, 1))

    def test_the_cross_round_escalate_bullet_is_absent(self):
        self.assertNotIn("persisted across rounds", _render(1, 1))


class TheReachableActionsStayOffered(unittest.TestCase):

    def test_consensus_is_offered(self):
        self.assertIn('"consensus"', _render(1, 1))

    def test_escalate_is_still_offered(self):
        self.assertIn('* `"escalate"` — pick this when', _render(1, 1))

    def test_escalates_other_conditions_survive(self):
        out = _render(1, 1)
        self.assertIn("requirements themselves contradict", out)
        self.assertIn("validation_failed", out)


class WithABiggerRoundBudgetEverythingIsOffered(unittest.TestCase):
    """The macro must not hard-code today's KICKOFF_MAX_ROUNDS."""

    def test_revision_returns_when_rounds_remain(self):
        out = _render(1, 3)
        self.assertIn('* `"request_revision"` — pick this when', out)

    def test_cross_round_escalate_returns_when_rounds_remain(self):
        self.assertIn("persisted across rounds", _render(1, 3))

    def test_at_the_last_of_several_rounds_revision_is_dropped(self):
        self.assertNotIn('* `"request_revision"` — pick this when', _render(3, 3))


class TheBriefingStillRenders(unittest.TestCase):

    def test_non_empty_and_names_the_meeting(self):
        out = _render(1, 1)
        self.assertIn("doc_1", out)
        self.assertGreater(len(out), 500)


if __name__ == "__main__":
    unittest.main()
