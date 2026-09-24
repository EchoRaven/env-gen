"""#1202cx — the verifier must not pay for an `edit_code` stage it never uses.

Every agent walks ACTION_INTERNAL_STAGES once per action round and EACH stage costs one
LLM call. Orch-F1 established this for the orchestrator with r93's evidence (166 of 1164
responses answering `edit_code` with "no code to edit", 14.3% of calls) and gave exactly
one role the treatment.

The verifier always had the same symptom; nothing could see it until #1202cr's per-phase
ledger. r42: $10.30 across 161 `edit_code` calls, while `agent/verifier` sits 0 commits
ahead of integration with 0 files different, and integration's authorship reads
frontend 44 / backend 15 / orchestrator 1 / verifier ZERO.

The subtlety that makes this more than deleting a stage: a stage is the HOME of its
categories, so dropping it without re-homing strands the profile's granted tools — the
orphan class (granted, prompt-mandated, never offered, lane wedges on
MALFORMED_FUNCTION_CALL).
"""
from pathlib import Path

import pytest
import yaml

from env_generator.llm_generator.multi_agent.agents.runtime import action_stage_policy as P

CONFIG = Path("env_generator/llm_generator/multi_agent/agents/agents_config.yaml")
ALL_STAGES = ("communicate", "edit_code", "run_checks", "delegate_team", "deliver")
HINTS = {
    "communicate": {"communication", "knowledge_write", "milestone", "progress"},
    "edit_code": {"analysis", "file", "image_search", "memory", "project", "reference"},
    "run_checks": {"api", "api_contract", "browser", "data_engine", "database",
                   "dependency", "docker", "logs", "runtime", "task_definition",
                   "verification", "vision"},
    "delegate_team": set(),
    "deliver": {"progress"},
}


@pytest.fixture(scope="module")
def profiles():
    return yaml.safe_load(CONFIG.read_text())["profiles"]


def _resolve(role, profiles):
    prof = profiles[role]
    allow, hints = P.parse_action_stage_config(
        agent_id=role, exec_cfg=prof.get("execution_pipeline"), all_stages=ALL_STAGES,
        base_hints=HINTS, granted_categories=set(prof.get("tool_categories") or []))
    return prof, (allow or ALL_STAGES), hints


def test_the_verifier_skips_edit_code(profiles):
    """161 calls a run, for a role that has never authored a commit."""
    _, stages, _ = _resolve("verifier", profiles)
    assert "edit_code" not in stages


def test_the_implementation_lanes_keep_it(profiles):
    """frontend authored 44 of integration's commits and backend 15. The saving must not
    be taken from the roles that actually write the app."""
    for role in ("frontend", "backend"):
        _, stages, _ = _resolve(role, profiles)
        assert "edit_code" in stages, role


def test_no_profile_strands_a_granted_category(profiles):
    """The orphan class is a WEDGE, not a slowdown: a tool that is granted and
    prompt-mandated but never offered takes the lane down on MALFORMED_FUNCTION_CALL.
    This holds for every profile, so the next role to drop a stage is covered too."""
    stranded = {}
    for role, prof in profiles.items():
        if not isinstance(prof, dict) or "execution_pipeline" not in prof:
            continue
        _, stages, hints = _resolve(role, profiles)
        covered = set().union(*[hints.get(s, set()) for s in stages]) if stages else set()
        granted = set(prof.get("tool_categories") or [])
        missing = sorted((granted & set().union(*HINTS.values())) - covered
                         - {c for s in ALL_STAGES if s in stages for c in HINTS[s]})
        if missing:
            stranded[role] = missing
    assert stranded == {}, f"granted categories with no home: {stranded}"


def test_the_verifier_rehomes_what_edit_code_hosted(profiles):
    """It holds 4 of edit_code's 6 categories; image_search and reference are not
    granted, so they are deliberately not re-homed."""
    prof, stages, hints = _resolve("verifier", profiles)
    granted = set(prof.get("tool_categories") or [])
    assert {"file", "project", "analysis"} <= hints["run_checks"]
    assert "memory" in hints["communicate"]
    assert not ({"image_search", "reference"} & granted)
