"""Guard: per-stage tool allowlists must include the tools that stage's PROMPT
and the delivery GATE actually require.

A `stage_tool_allowlist` entry RESTRICTS the lane's tool surface in that stage to
exactly the listed tools — so an allowlist that omits a tool the prompt tells the
lane to call (or the gate reads evidence from) silently wedges the lane: it is
told to do something it physically cannot. Three such gaps were found and fixed:

  * kickoff:action exposed only the generic workhub_add_meeting_decision — the
    dedicated flat-param kickoff_declare_* tools were excluded, so lanes were
    forced into the nested-array decision Gemini nulls out (ui_pages:[null,...])
    → substance guard rejects → frontend looped on a null array. (FATAL)
  * backend implementation:action excluded mcp_registry_register_* though
    backend_agent.j2 says it MUST register the MCP server + tools (Cutover-22).
  * verifier implementation:action excluded codehub_record_check though
    verifier_agent.j2 tells it to record build:/validation: checks.

Only profiles with a restrictive implementation:action allowlist are guarded
(frontend implementation is intentionally unrestricted; orchestrator has none).
"""

import sys
import unittest
from pathlib import Path

import yaml

AGENT_DIR = Path(__file__).resolve().parent.parent
_CONFIG = (
    AGENT_DIR
    / "env_generator/llm_generator/multi_agent/agents/agents_config.yaml"
)


def _allowlist(profile: str, stage: str) -> list:
    cfg = yaml.safe_load(_CONFIG.read_text())
    return cfg["profiles"][profile]["stage_tool_allowlist"][stage]


class StageToolAllowlistGapTests(unittest.TestCase):
    def test_kickoff_lanes_have_dedicated_declare_tools(self):
        # Each lane's kickoff must expose its dedicated flat-param declare tool,
        # not just the null-prone generic workhub_add_meeting_decision.
        for profile, required in (
            ("backend", {"kickoff_declare_endpoint", "kickoff_declare_table"}),
            (
                "frontend",
                {
                    "kickoff_declare_ui_page",
                    "kickoff_declare_ui_component",
                    "kickoff_declare_user_flow",
                },
            ),
            ("verifier", {"kickoff_declare_predicate"}),
        ):
            allow = set(_allowlist(profile, "kickoff:action"))
            self.assertTrue(
                required <= allow,
                f"{profile} kickoff missing {required - allow}",
            )

    def test_backend_implementation_can_register_mcp(self):
        # backend_agent.j2: MUST mcp_registry_register_server + _register_tool
        # for each tool when it implements an MCP server (Cutover-22 dead-code).
        allow = set(_allowlist("backend", "implementation:action"))
        for tool in ("mcp_registry_register_server", "mcp_registry_register_tool"):
            self.assertIn(tool, allow, f"backend impl cannot {tool}")

    def test_verifier_implementation_can_record_checks(self):
        # verifier_agent.j2 tells it to make build:/validation: check records;
        # codehub_record_check is the only tool that emits them.
        allow = set(_allowlist("verifier", "implementation:action"))
        self.assertIn("codehub_record_check", allow)

    def test_backend_implementation_can_register_contract_and_commit(self):
        # Sanity: the backend can still register its contract + commit code.
        allow = set(_allowlist("backend", "implementation:action"))
        for tool in (
            "registryhub_register_endpoint",
            "registryhub_register_table",
            "codehub_commit",
            "write",
            "edit",
        ):
            self.assertIn(tool, allow)

    def test_verifier_implementation_has_primary_validation_path(self):
        # The gate's primary evidence path is run_validation -> functionally
        # validated; the verifier must retain it (+ contract test recording).
        allow = set(_allowlist("verifier", "implementation:action"))
        for tool in (
            "run_validation",
            "registryhub_record_contract_test",
            "registryhub_register_verification_chain",
        ):
            self.assertIn(tool, allow)


if __name__ == "__main__":
    unittest.main()
