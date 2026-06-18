"""PROPOSAL #10: the orchestrator's goal-less resident wake (resident_message_wakeup
carries no raw_requirements) must render a SHORT current-project header (name +
TRUNCATED goal) so the lane wakes knowing what it coordinates — not "Complete your
assigned task." It is an orientation header, NOT the full spec (that rides the `full`
macro), so the goal is bounded.
"""

import sys
import unittest
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR))
PROMPTS_V3 = AGENT_DIR / "env_generator" / "llm_generator" / "multi_agent" / "prompts" / "v3"
PROMPTS_ROOT = PROMPTS_V3.parent


def _render(name: str, description: str) -> str:
    env = Environment(loader=FileSystemLoader([str(PROMPTS_V3), str(PROMPTS_ROOT)]))
    mod = env.get_template("orchestrator_agent.j2").make_module()
    return mod.resident_task_prompt(name=name, description=description)


class ResidentWakePromptTests(unittest.TestCase):
    def test_renders_name_and_goal_header(self):
        out = _render("YouTube Clone", "Build a YouTube-style video sharing platform.")
        self.assertIn("Current project", out)
        self.assertIn("YouTube Clone", out)            # presence: name
        self.assertIn("video sharing platform", out)   # presence: (part of) goal
        self.assertIn("deliver_project", out)           # still the coordinator framing

    def test_long_goal_is_truncated_bounded(self):
        # boundedness: a long description must be cut (≤160 + ellipsis); a far-tail
        # marker beyond the cut must NOT appear (this is a header, not the full spec).
        desc = "START " + ("x" * 200) + " TAILMARKER"
        out = _render("App", desc)
        self.assertIn("START", out)
        self.assertNotIn("TAILMARKER", out)            # tail beyond [:160] dropped
        self.assertIn("…", out)                    # ellipsis appended
        # the GOAL line specifically must be bounded (the separate "This wake"
        # instruction paragraph is intentionally long — don't check that one).
        goal_line = next(ln for ln in out.splitlines() if "START" in ln)
        self.assertLess(len(goal_line), 180, "goal header line must be bounded (~160 + name + ellipsis)")

    def test_short_goal_not_truncated(self):
        out = _render("App", "A small todo app.")
        self.assertIn("A small todo app.", out)
        self.assertNotIn("…", out)                 # nothing to truncate

    def test_empty_falls_back_to_memory_bank(self):
        out = _render("", "")
        self.assertIn("memory_bank", out)               # graceful fallback, still renders


if __name__ == "__main__":
    unittest.main()
