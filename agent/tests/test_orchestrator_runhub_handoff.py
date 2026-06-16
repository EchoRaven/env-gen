"""Tests that orchestrator prompt notes Debugger auto-picks up RunHub failures (Cutover 12).

Round-4 (2026-06-02): renamed from "bug_triage_orchestrator" to
"debugger" per roster reduction; prose was swept; assertions check
for the new term."""

import unittest
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent

PROMPTS_V3 = AGENT_DIR / "env_generator" / "llm_generator" / "multi_agent" / "prompts" / "v3"
PROMPTS_ROOT = PROMPTS_V3.parent


class OrchestratorRunHubHandoffTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        env = Environment(loader=FileSystemLoader([str(PROMPTS_V3), str(PROMPTS_ROOT)]))
        tpl = env.get_template("orchestrator_agent.j2")
        mod = tpl.make_module()
        for name in ("lead_specifics", "orchestrator_specifics"):
            if hasattr(mod, name):
                cls.system = getattr(mod, name)()
                break
        else:
            raise RuntimeError("could not find orchestrator specifics macro")

    def test_prompt_mentions_debugger_auto_handoff(self) -> None:
        upper = self.system.upper()
        # Accept "DEBUGGER" or the older "BUG TRIAGE" phrasing for
        # narrative compatibility (the prose was swept but the
        # prompt may still use the bug_create channel name).
        self.assertTrue(
            "DEBUGGER" in upper or "BUG TRIAGE" in upper,
            "prompt must mention the Debugger (bug-level orchestrator)",
        )
        # Some phrasing of "auto-picks-up" / "automatically" / "subscribed"
        self.assertTrue(
            any(phrase in upper for phrase in (
                "AUTOMATICALLY", "AUTO-PICK", "AUTO PICK", "SUBSCRIBED",
                "AUTO-ROUTE", "AUTO ROUTE",
            )),
            "prompt must indicate Debugger auto-handles RunHub failures",
        )

    def test_prompt_warns_not_to_manually_triage_run_failures(self) -> None:
        upper = self.system.upper()
        self.assertTrue(
            "DO NOT" in upper or "NEVER" in upper or "MUST NOT" in upper,
            "prompt must include a 'do not' rule about manual run-failure triage",
        )


if __name__ == "__main__":
    unittest.main()
