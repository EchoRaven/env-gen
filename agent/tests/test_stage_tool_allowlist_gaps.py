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
                    # kickoff_declare_user_flow intentionally NOT required: user_flows
                    # were RETIRED from the frontend kickoff section (user directive
                    # 2026-06-22, see runtime/kickoff/section_substance.py) — critical
                    # flows are DERIVED by the orchestrator from ui_pages + endpoints at
                    # verify time, not authored by the frontend lane.
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

    def test_search_tools_in_implementation_not_kickoff(self):
        # PROPOSAL #6 → #9: file-search tools (glob/grep/list_generated_files) belong
        # only in stages that AUTHOR or INSPECT files — the IMPLEMENTATION stages,
        # where a lane writes code referencing other files (locate-before-read instead
        # of guessing a path; the orchestrator once guessed app/docker-compose.yml when
        # it lives at docker/docker-compose.yml).
        search = {"glob", "grep", "list_generated_files"}
        for profile, stage in (
            ("backend", "implementation:action"),
            ("verifier", "implementation:action"),
        ):
            allow = set(_allowlist(profile, stage))
            self.assertTrue(
                search <= allow,
                f"{profile} {stage} cannot search files: missing {search - allow}",
            )
        # The backend authors code across many files that reference each other,
        # so it also needs symbol lookup (find_definition) in implementation.
        self.assertIn(
            "find_definition", set(_allowlist("backend", "implementation:action"))
        )
        # PROPOSAL #9: NOT in kickoff — nothing is built yet (the lane only DECLARES
        # its contract slice), so search tools have no use there and only widen the
        # surface that kickoff is deliberately minimized to keep declare-focused.
        for profile in ("backend", "frontend", "verifier"):
            allow = set(_allowlist(profile, "kickoff:action"))
            leaked = search & allow
            self.assertFalse(
                leaked,
                f"{profile} kickoff:action must NOT expose search tools, found {leaked}",
            )

    def test_frontend_kickoff_has_reference_image_tools(self):
        # PROPOSAL #12: the frontend's Phase A design REQUIRES inspecting the staged
        # reference screenshots (frontend_agent.j2: list_reference_images then view_image
        # for every path — "never guess the UI from memory"). They must be in the
        # frontend kickoff allowlist or the lane can't see the references it's told to use.
        allow = set(_allowlist("frontend", "kickoff:action"))
        for tool in ("list_reference_images", "view_image"):
            self.assertIn(
                tool, allow,
                f"frontend kickoff:action must expose {tool} (Phase A design input)",
            )
        # copy_reference_image deliberately NOT required (bundled-library use, not the
        # pre-staged screenshots) — reviewer's binding scope cut on #12.


if __name__ == "__main__":
    unittest.main()


class ImplementationStageGapsFoundInR91R93(unittest.TestCase):
    """#349 — tools the lane is TOLD to use in implementation but cannot see.

    A `stage_tool_allowlist` is authoritative: `candidate_names & stage_allow_set`.
    Each of these is listed in the SAME profile's `kickoff:action` (so the pool
    grants it -- an ungranted entry would already be flagged dead there) and
    omitted from `implementation:action`, which is the stage the lane spends the
    run in. The trajectories show the agents discovering this live:

      * verifier `registryhub_list_ui_pages` -- 19 turns spent saying it is not
        in its toolset. flow_coverage derives the REQUIRED ui_flow set from
        `list_ui_pages()`, and `deliverability_ui_flow_missing` (verifier-owned,
        dispatched 18x) cannot be cleared without knowing those names.
      * verifier / backend / frontend `workhub_comment` -- 18 turns. commit_gate
        unconditionally tells every agent this is the progress channel.
      * backend `workhub_get_task` -- 12 turns, while the remediation dispatcher
        wakes it with "Claim task {id} and fix it NOW". Verbatim: "I don't have
        workhub_get_task -- the orchestrator's task assumes a tool exists that
        doesn't."

    Not included: `update_memory_bank`, which the root step_reminders mandate and
    which drew 30 complaints. It appears in NO stage allowlist of any of these
    three profiles, so unlike the five above there is no in-config proof that the
    assembled pool grants it -- adding it could create a dead entry instead of
    fixing a gap. It needs a grant check against a live pool first.
    """

    def _stages(self, profile):
        cfg = yaml.safe_load(_CONFIG.read_text())
        return cfg["profiles"][profile].get("stage_tool_allowlist") or {}

    def _assert_impl_has(self, profile, tool):
        stages = self._stages(profile)
        impl = set(stages.get("implementation:action") or [])
        self.assertTrue(impl, f"{profile} has no implementation:action allowlist")
        # grant proof: the same profile allowlists it in another stage
        other = [s for s, names in stages.items()
                 if s != "implementation:action" and tool in set(names or [])]
        self.assertTrue(
            other, f"{profile} does not allowlist {tool} in ANY other stage — "
                   "grant is unproven, do not add it blindly")
        self.assertIn(tool, impl, f"{profile} implementation:action cannot {tool}")

    def test_verifier_can_list_ui_pages_during_implementation(self):
        self._assert_impl_has("verifier", "registryhub_list_ui_pages")

    def test_verifier_can_comment_during_implementation(self):
        self._assert_impl_has("verifier", "workhub_comment")

    def test_backend_can_comment_during_implementation(self):
        self._assert_impl_has("backend", "workhub_comment")

    def test_frontend_can_comment_during_implementation(self):
        self._assert_impl_has("frontend", "workhub_comment")

    def test_backend_can_read_the_task_it_is_told_to_claim(self):
        self._assert_impl_has("backend", "workhub_get_task")


class MemoryBankToolsReachTheActionSurface(unittest.TestCase):
    """#350 — the allowlist removed the two tools the engine deliberately keeps.

    stages.py states the intent verbatim (Memory-mechanism redesign, 2026-06-08):

        "Keep ``read_memory_bank`` + ``update_memory_bank`` in the ACTION
         surface so the agent can still read/update its Memory Bank ON-DEMAND
         when it genuinely needs to"

    and the ROOT step_reminders mandate both to every profile. But neither
    appears in ANY stage allowlist of the three lane profiles, and the allowlist
    is authoritative for the stages it covers -- so in `implementation:action`,
    where the lanes spend the run, both were unreachable.

    `update_memory_bank` drew 30 "not in my tool list" turns, the most of any
    single tool. r93's orchestrator, verbatim: "I don't actually have
    `update_memory_bank` in my tool list -- checking my available tools, memory
    bank tools aren't exposed."

    The grant is not in doubt for these two: tools.py adds ReadMemoryBankTool and
    UpdateMemoryBankTool with `always=True`, i.e. unconditionally to EVERY
    profile regardless of tool_categories or bundles. That is a stronger proof
    than the cross-stage evidence used for the #349 five.

    (The orchestrator reached the same wall by a different route -- it has no
    stage allowlist, so the RANKER hid the tools; #330 re-homed the `memory`
    category onto a stage it actually runs. Both paths are now closed.)
    """

    ALWAYS_GRANTED = ("read_memory_bank", "update_memory_bank")

    def _impl(self, profile):
        cfg = yaml.safe_load(_CONFIG.read_text())
        stages = cfg["profiles"][profile].get("stage_tool_allowlist") or {}
        return set(stages.get("implementation:action") or [])

    def test_engine_still_keeps_them_in_the_action_surface(self):
        """If this intent is ever reversed, the allowlist entries should go too."""
        src = (AGENT_DIR / "env_generator/llm_generator/multi_agent/agents"
               / "runtime/step_pipeline/stages.py").read_text()
        self.assertIn("read_memory_bank", src)
        self.assertIn("update_memory_bank", src)

    def test_verifier_implementation_can_use_the_memory_bank(self):
        impl = self._impl("verifier")
        for tool in self.ALWAYS_GRANTED:
            self.assertIn(tool, impl)

    def test_backend_implementation_can_use_the_memory_bank(self):
        impl = self._impl("backend")
        for tool in self.ALWAYS_GRANTED:
            self.assertIn(tool, impl)

    def test_frontend_implementation_can_use_the_memory_bank(self):
        impl = self._impl("frontend")
        for tool in self.ALWAYS_GRANTED:
            self.assertIn(tool, impl)
