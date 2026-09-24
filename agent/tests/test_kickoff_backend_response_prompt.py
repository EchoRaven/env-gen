"""Tests for the `kickoff_response_prompt` Jinja macro in backend_agent.j2.

Round-7-followup: the backend agent must respond to a `kickoff_request`
event with a single-pass meeting decision in the canonical
`KickoffEndpoint` shape defined by `runtime/kickoff/contract.py`. This
test renders the macro with sample arguments and asserts the rendered
instruction text contains the load-bearing signals: the agent's section
name, the `workhub_add_meeting_decision` tool call, and the canonical
contract vocabulary (`response_key`).

Closed-by-construction: a sharp test per invariant — the macro must
exist, render non-empty text, name the section/tool, and mention the
canonical kickoff vocabulary the agent will be graded on.
"""

import unittest
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent

PROMPTS_V3 = (
    AGENT_DIR / "env_generator" / "llm_generator" / "multi_agent"
    / "prompts" / "v3"
)
PROMPTS_ROOT = PROMPTS_V3.parent
TEMPLATE = "backend_agent.j2"


class KickoffBackendResponsePromptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        env = Environment(
            loader=FileSystemLoader([str(PROMPTS_V3), str(PROMPTS_ROOT)])
        )
        tpl = env.get_template(TEMPLATE)
        mod = tpl.make_module()
        cls.module = mod
        cls.rendered = mod.kickoff_response_prompt(
            meeting_id="mtg_abc123",
            milestone_index=1,
            requirements="Users can register, log in, and create + list posts.",
            expected_section="backend",
        )

    def test_macro_renders_nonempty(self) -> None:
        self.assertIsInstance(self.rendered, str)
        self.assertGreater(
            len(self.rendered.strip()), 200,
            "kickoff_response_prompt must render a substantive briefing",
        )

    def test_mentions_backend_section(self) -> None:
        self.assertIn("backend", self.rendered.lower())

    def test_mentions_workhub_add_meeting_decision(self) -> None:
        self.assertIn("workhub_add_meeting_decision", self.rendered)

    def test_mentions_expected_section_argument(self) -> None:
        # The macro must echo the expected_section into the instruction
        # text so the agent knows which key to set on its decision dict.
        self.assertIn("backend", self.rendered)

    def test_mentions_canonical_contract_shape_response_key(self) -> None:
        # `response_key` is the load-bearing field on KickoffEndpoint that
        # frontend's service-layer generator depends on. The prompt MUST
        # mention it so the agent knows to set it on every endpoint.
        self.assertIn("response_key", self.rendered)

    def test_mentions_finish_call(self) -> None:
        # Single-pass discipline: after add_meeting_decision, call finish()
        # — do NOT poll for synthesis.
        self.assertIn("finish", self.rendered.lower())

    def test_includes_negative_example_no_registryhub_register_endpoint(self) -> None:
        # Negative-example invariant: orchestrator synthesizes + registers
        # endpoints after quorum; backend MUST NOT call registryhub_register_endpoint
        # during kickoff.
        self.assertIn("registryhub_register_endpoint", self.rendered)
        lowered = self.rendered.lower()
        self.assertTrue(
            ("do not" in lowered or "do **not**" in lowered or "do NOT" in self.rendered),
            "prompt must explicitly forbid registryhub_register_endpoint during kickoff",
        )

    def test_meeting_id_and_milestone_index_substituted(self) -> None:
        self.assertIn("mtg_abc123", self.rendered)
        self.assertIn("M1", self.rendered)

    def test_milestone_history_branch_present_for_m_gt_1(self) -> None:
        # When milestone_index > 1, the agent must read prior-milestone
        # artifacts from RegistryHub. Render with M=3 and verify the prompt
        # surfaces the M(N-1) instruction.
        rendered_m3 = self.module.kickoff_response_prompt(
            meeting_id="mtg_xyz",
            milestone_index=3,
            requirements="Add comments to existing posts.",
            expected_section="backend",
        )
        self.assertIn("registryhub_list_endpoints", rendered_m3)
        self.assertIn("M2", rendered_m3)

    def test_system_prompt_stop_rule_mentions_kickoff_request(self) -> None:
        # The system prompt's stop_rules section must also instruct the
        # agent to invoke this macro on kickoff_request.
        system = self.module.backend_system_prompt()
        self.assertIn("kickoff_request", system)
        self.assertIn("kickoff_response_prompt", system)
        self.assertIn("kickoff_complete", system)


if __name__ == "__main__":
    unittest.main()
