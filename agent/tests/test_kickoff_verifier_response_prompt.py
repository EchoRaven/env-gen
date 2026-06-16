"""Closed-by-construction tests for verifier_agent.j2::kickoff_response_prompt.

The macro is what the verifier resident agent runs when a `kickoff_request`
event for a meeting lands in its inbox. It must:

  * Render non-empty for any well-formed (meeting_id, milestone_index,
    requirements, expected_section) tuple.
  * Address the verifier section by name (the agent has to know which
    slot it is filling).
  * Name `workhub_add_meeting_decision` — that is the SINGLE hub-write
    the macro instructs the agent to perform.
  * Echo the expected_section keyword the orchestrator passed in so the
    agent's contribution lands in the right slot.
  * Mention the canonical contract-shape vocabulary so the agent does
    not invent a non-conformant draft (predicates carry `flow`;
    backend's decision content carries `response_key`; design's carries
    `user_flows`). These three tokens together are the proof the macro
    is wired to the kickoff/contract.py + cross_check_suite.py shapes.

Each test is sharp: exactly one invariant per case, per workflow
discipline (closed-by-construction, no fallback, no phantom defaults).
"""
from __future__ import annotations

import unittest
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
PROMPTS_V3 = AGENT_DIR / "env_generator" / "llm_generator" / "multi_agent" / "prompts" / "v3"
PROMPTS_ROOT = PROMPTS_V3.parent


def _render(meeting_id: str, milestone_index: int, requirements: str, expected_section: str) -> str:
    env = Environment(loader=FileSystemLoader([str(PROMPTS_V3), str(PROMPTS_ROOT)]))
    tpl = env.get_template("verifier_agent.j2")
    mod = tpl.make_module()
    return mod.kickoff_response_prompt(
        meeting_id=meeting_id,
        milestone_index=milestone_index,
        requirements=requirements,
        expected_section=expected_section,
    )


class KickoffVerifierResponsePromptTests(unittest.TestCase):

    def setUp(self) -> None:
        self.meeting_id = "meeting-abc-123"
        self.milestone_index = 2
        self.requirements = (
            "Build a microblog with critical flows register_to_first_post "
            "and delete_own_post. Backend: REST. Frontend: SPA. Auth: JWT."
        )
        self.expected_section = "verifier"
        self.rendered = _render(
            self.meeting_id,
            self.milestone_index,
            self.requirements,
            self.expected_section,
        )

    def test_rendered_non_empty(self) -> None:
        self.assertTrue(self.rendered.strip(), "macro must render non-empty text")

    def test_addresses_verifier_role(self) -> None:
        self.assertIn("verifier", self.rendered)

    def test_names_workhub_add_meeting_decision(self) -> None:
        self.assertIn("workhub_add_meeting_decision", self.rendered)

    def test_echoes_expected_section_keyword(self) -> None:
        self.assertIn(self.expected_section, self.rendered)

    def test_mentions_meeting_id_and_milestone(self) -> None:
        self.assertIn(self.meeting_id, self.rendered)
        # milestone_index is rendered as both M2 and the raw integer
        # in the workhub_add_meeting_decision call; either is fine,
        # we just need to know the macro consumed the arg.
        self.assertIn(str(self.milestone_index), self.rendered)

    def test_mentions_canonical_contract_user_flows(self) -> None:
        # Design's user_flows shape — verifier predicates reference
        # user_flow ids by `flow:`. The macro must mention user_flow(s)
        # so the agent knows the relationship.
        self.assertIn("user_flow", self.rendered)

    def test_mentions_canonical_contract_response_key(self) -> None:
        # Backend's KickoffEndpoint shape — the macro instructs the
        # verifier to author api_smoke predicates that assert
        # `expect_response_key`, which mirrors KickoffEndpoint.response_key.
        # Verifier must speak the SAME vocabulary so its predicates can
        # be matched against backend's endpoints at validation time.
        self.assertIn("response_key", self.rendered)

    def test_mentions_predicate_form_kinds(self) -> None:
        # Predicate.form.kind vocabulary from the task spec —
        # api_smoke / ui_flow / sql_check / predicate_dsl. The macro
        # MUST list these so the agent does not invent a non-conformant
        # form.kind that fails cross-check.
        for kind in ("api_smoke", "ui_flow", "sql_check", "predicate_dsl"):
            self.assertIn(kind, self.rendered, f"form.kind '{kind}' missing")

    def test_kickoff_register_boundary_is_engine_enforced(self) -> None:
        # Cutover-10-style boundary — orchestrator owns kickoff-time
        # registration. PR3.1.3 moved this from "DO NOT call
        # registryhub_register_endpoint" prose to engine-side enforcement:
        # the verifier profile's stage_tool_allowlist["kickoff:action"]
        # excludes registryhub_register_endpoint (and its siblings) so the
        # LLM never sees them during kickoff. Verify both sides:
        #   (a) the yaml allowlist excludes registryhub_register_endpoint
        #   (b) the macro names the legitimate kickoff tools (positive
        #       instruction) instead of the negative prose
        import yaml  # type: ignore
        from pathlib import Path

        config_path = (
            Path(__file__).resolve().parents[1]
            / "env_generator"
            / "llm_generator"
            / "multi_agent"
            / "agents"
            / "agents_config.yaml"
        )
        cfg = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        verifier_cfg = cfg["profiles"]["verifier"]
        allowlist = (verifier_cfg.get("stage_tool_allowlist") or {}).get(
            "kickoff:action"
        )
        self.assertIsNotNone(
            allowlist,
            "verifier must declare stage_tool_allowlist['kickoff:action']",
        )
        self.assertNotIn(
            "registryhub_register_endpoint",
            allowlist,
            "registryhub_register_endpoint must be excluded from the "
            "kickoff:action allowlist — orchestrator owns kickoff-time "
            "registration.",
        )
        self.assertIn(
            "workhub_add_meeting_decision",
            allowlist,
            "workhub_add_meeting_decision must be IN the allowlist — "
            "it is the canonical kickoff write.",
        )
        # The macro's prose must surface the positive boundary
        # (what IS allowed) so a model that can't see the engine
        # restriction still gets the contract.
        self.assertIn("workhub_add_meeting_decision", self.rendered)

    def test_instructs_single_pass_finish(self) -> None:
        # The macro must end with a finish() instruction so the agent
        # does NOT poll waiting for synthesis.
        self.assertIn("finish()", self.rendered)

    def test_m1_branch_pulls_prior_milestone(self) -> None:
        # When milestone_index > 0, the macro must instruct the agent
        # to pull prior-milestone RegistryHub artifacts so its predicates
        # are consistent. This is the M(N-1) history requirement.
        self.assertIn("registryhub_list_endpoints", self.rendered)
        self.assertIn("registryhub_list_tables", self.rendered)

    def test_m0_branch_skips_prior_milestone_pull(self) -> None:
        # When milestone_index == 0, RegistryHub is empty and the macro
        # should NOT instruct the agent to pull prior-milestone
        # endpoints (those calls would return empty + waste a step).
        m0 = _render(
            "meeting-zero",
            0,
            "Initial milestone: build login + one CRUD entity.",
            "verifier",
        )
        self.assertNotIn("registryhub_list_endpoints", m0)
        self.assertNotIn("registryhub_list_tables", m0)


class KickoffVerifierResponsePromptStopRuleTests(unittest.TestCase):
    """The system prompt's stop_rules MUST teach the agent to invoke
    kickoff_response_prompt on a kickoff_request event."""

    @classmethod
    def setUpClass(cls) -> None:
        env = Environment(loader=FileSystemLoader([str(PROMPTS_V3), str(PROMPTS_ROOT)]))
        tpl = env.get_template("verifier_agent.j2")
        mod = tpl.make_module()
        cls.system = mod.verifier_system_prompt()

    def test_system_prompt_references_kickoff_response_prompt(self) -> None:
        self.assertIn("kickoff_response_prompt", self.system)

    def test_system_prompt_references_kickoff_request_event(self) -> None:
        self.assertIn("kickoff_request", self.system)

    def test_system_prompt_references_kickoff_complete_barrier(self) -> None:
        self.assertIn("kickoff_complete", self.system)


if __name__ == "__main__":
    unittest.main()
