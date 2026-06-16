"""Closed-by-construction tests for the ``kickoff_response_prompt`` macro
in ``prompts/v3/frontend_agent.j2``.

The macro is the SINGLE-PASS instruction the frontend agent runs when it
wakes on a ``kickoff_request`` event. It MUST:

  * render to a non-empty string,
  * name the agent role (``frontend``) so the runtime can verify the
    right macro was selected,
  * instruct the agent to call ``workhub_add_meeting_decision`` (the
    only legal write during kickoff — see run_kickoff.py:35-44),
  * surface the ``expected_section`` keyword the orchestrator passed in,
    so an operator reading the prompt can confirm the agent is wired to
    author the right section,
  * mention the canonical contract vocabulary (``response_key`` for the
    backend KickoffEndpoint shape; ``user_flows`` for the design
    section) so a drift in the contract module would surface here as a
    failing test rather than as a silent prompt regression.

The kickoff macros are pure Jinja — no LLM call, no hub coupling — so
these tests render the macro in-process via a ``jinja2.Environment``
rooted at ``prompts/``.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
PROMPTS_DIR = (
    AGENT_DIR
    / "env_generator"
    / "llm_generator"
    / "multi_agent"
    / "prompts"
)

# Sibling-module convention: tests prepend the LLM-generator dir so
# ``multi_agent`` imports resolve. The macro itself is template-only,
# but keeping the path active matches the rest of the kickoff suite.
sys.path.insert(
    0,
    str(AGENT_DIR / "env_generator" / "llm_generator"),
)


def _render_kickoff_response_prompt(
    *,
    meeting_id: str = "kickoff-m1-abc123",
    milestone_index: int = 1,
    requirements: str = "Build a tiny social feed: login + home feed.",
    expected_section: str = "frontend",
) -> str:
    """Render the macro in isolation via a ``{% import %}`` shim template.

    Closed-by-construction: any rename / signature drift in the macro
    will raise ``jinja2.exceptions.UndefinedError`` here, surfaced as a
    test error rather than a silent production regression.
    """
    env = Environment(
        loader=FileSystemLoader(str(PROMPTS_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.from_string(
        "{% import 'v3/frontend_agent.j2' as fe %}"
        "{{ fe.kickoff_response_prompt("
        "  meeting_id, milestone_index, requirements, expected_section"
        ") }}"
    )
    return template.render(
        meeting_id=meeting_id,
        milestone_index=milestone_index,
        requirements=requirements,
        expected_section=expected_section,
    )


class KickoffResponsePromptRenderTests(unittest.TestCase):
    """Each test pins one invariant the macro promises."""

    def test_renders_nonempty(self) -> None:
        out = _render_kickoff_response_prompt()
        self.assertTrue(out.strip(), "macro must render to a non-empty string")

    def test_mentions_frontend_role(self) -> None:
        out = _render_kickoff_response_prompt()
        self.assertIn(
            "frontend",
            out,
            "macro must name the 'frontend' role so an operator can "
            "verify the right agent macro was selected",
        )

    def test_instructs_add_meeting_decision_call(self) -> None:
        out = _render_kickoff_response_prompt()
        self.assertIn(
            "workhub_add_meeting_decision",
            out,
            "kickoff response MUST instruct the agent to record its "
            "section via workhub_add_meeting_decision — the only legal "
            "write during kickoff (see run_kickoff.py:35-44)",
        )

    def test_surfaces_expected_section_keyword(self) -> None:
        # Use a sentinel that would only appear via the caller-passed
        # ``expected_section`` argument (NOT the literal "frontend"
        # which the macro hardcodes elsewhere).
        out = _render_kickoff_response_prompt(
            expected_section="frontend-sentinel-xyz",
        )
        self.assertIn(
            "frontend-sentinel-xyz",
            out,
            "macro must render the caller-passed expected_section so "
            "the agent knows which section to author",
        )

    def test_surfaces_meeting_id_and_milestone_index(self) -> None:
        out = _render_kickoff_response_prompt(
            meeting_id="meet-sentinel-42",
            milestone_index=7,
        )
        self.assertIn("meet-sentinel-42", out)
        self.assertIn("7", out)

    def test_mentions_canonical_contract_vocab(self) -> None:
        """Drift-guard against runtime/kickoff/contract.py + run_kickoff.py.

        The cross-section vocabulary the macro names ("response_key" for
        backend's KickoffEndpoint, "user_flows" for design's section) is
        load-bearing — if it drifts from the contract module, the agent
        would author a shape the cross-check suite rejects. Pinning the
        vocabulary in the prompt makes that drift a failing test here.
        """
        out = _render_kickoff_response_prompt()
        self.assertIn(
            "response_key",
            out,
            "macro must name the backend KickoffEndpoint vocabulary "
            "('response_key') so frontend's api_calls align with the "
            "shape backend authors",
        )
        self.assertIn(
            "user_flows",
            out,
            "macro must name the design section vocabulary "
            "('user_flows') so frontend's per-screen user_flow refs "
            "resolve to a flow design has authored",
        )

    def test_milestone_history_branch_only_when_index_gt_one(self) -> None:
        """M1 has no prior milestone — the history-reading branch must
        only fire when ``milestone_index > 1``."""
        out_m1 = _render_kickoff_response_prompt(milestone_index=1)
        self.assertNotIn(
            "Milestone history:",
            out_m1,
            "M1 has no prior milestone — history-reading branch must "
            "not render",
        )
        out_m2 = _render_kickoff_response_prompt(milestone_index=2)
        self.assertIn(
            "Milestone history:",
            out_m2,
            "M2+ must instruct the agent to read prior-milestone "
            "artifacts",
        )

    def test_kickoff_registration_boundary_is_engine_enforced(self) -> None:
        """Cutover-10-style boundary — orchestrator owns endpoint
        registration during kickoff, NOT the agents. PR1.3 moved this
        from prose ('DO NOT call registryhub_register_endpoint') to
        engine-side enforcement: frontend's
        stage_tool_allowlist['kickoff:action'] excludes
        registryhub_register_endpoint (and write/edit, so 'no frontend code
        during kickoff' is also engine-enforced). Verify both sides:
          (a) yaml allowlist excludes registryhub_register_endpoint + write
          (b) workhub_add_meeting_decision IS in the allowlist
          (c) the macro names the positive boundary it can carry
        """
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
        frontend_cfg = cfg["profiles"]["frontend"]
        allowlist = (frontend_cfg.get("stage_tool_allowlist") or {}).get(
            "kickoff:action"
        )
        self.assertIsNotNone(
            allowlist,
            "frontend must declare stage_tool_allowlist['kickoff:action']",
        )
        for forbidden in (
            "registryhub_register_endpoint",
            "registryhub_register_consumer",
            "write",
            "edit",
            "apply_patch",
        ):
            self.assertNotIn(
                forbidden,
                allowlist,
                f"{forbidden} must be excluded from kickoff:action — "
                "registration owned by orchestrator; code writes "
                "are Phase A AFTER kickoff_complete.",
            )
        self.assertIn(
            "workhub_add_meeting_decision",
            allowlist,
            "workhub_add_meeting_decision must be IN the allowlist.",
        )
        # The macro's prose must surface the positive boundary.
        out = _render_kickoff_response_prompt()
        self.assertIn("workhub_add_meeting_decision", out)

    def test_includes_finish_call_instruction(self) -> None:
        """Single-pass discipline: macro must instruct ``finish()`` so
        the agent does not loop / poll for synthesis."""
        out = _render_kickoff_response_prompt()
        self.assertIn(
            "finish()",
            out,
            "macro must instruct finish() — single-pass kickoff "
            "response, NOT a polling loop",
        )


if __name__ == "__main__":
    unittest.main()
