"""TOOL-系统 — startup cross-validator: stage_tool_allowlist ⊆ granted tools.

A tool reaches an agent only when FOUR layers align: factory → bundle
include_names → profile bundles/categories → allow/deny. ``stage_tool_allowlist``
can only NARROW that set — so an allowlist entry naming a tool the profile is
never granted is DEAD, and because the allowlists were written "deliberately
generous" (their own yaml comments), dead entries silently accumulated and
MASKED missing capabilities. Audited 2026-06-12 (this review): 26 dead entries
across backend/frontend/verifier, including

  * verifier ``bug_create`` — the prompt's canonical failure-routing channel,
    never granted (TOOL-C1: detected failures went nowhere),
  * verifier ``browser_*`` ×6 — tool_bundles imported a flag the browser
    package never exported, so the ImportError guard pinned browser tools OFF
    in every environment (ui_flow testing was physically impossible),
  * verifier ``workhub_task`` — allowlisted for claiming (smoke #6 comment)
    while deny_tools killed it, so the verifier could not claim the very P0
    tasks the orchestrator's remediation dispatches tell it to claim,
  * phantom ``think`` ×5 — a tool that has never existed.

This suite pins (a) the validator mechanism, (b) the startup warn wiring,
(c) ZERO violations in the real agents_config.yaml, and (d) the restored
verifier capabilities — so the whole class cannot regress silently.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from multi_agent.tool_surface import (  # noqa: E402
    validate_stage_allowlists, validate_skill_consult_preconditions)


# ── the pure validator ─────────────────────────────────────────────────────────

def test_flags_allowlist_entry_not_granted():
    errs = validate_stage_allowlists(
        "verifier",
        stage_tool_allowlist={"implementation:action": ["run_validation", "bug_create"]},
        granted_tool_names={"run_validation", "read", "finish"},
    )
    assert len(errs) == 1
    assert "bug_create" in errs[0]
    assert "verifier" in errs[0]
    assert "implementation:action" in errs[0]


def test_silent_when_allowlist_is_subset():
    assert validate_stage_allowlists(
        "backend",
        stage_tool_allowlist={"kickoff:action": ["read", "finish"]},
        granted_tool_names={"read", "finish", "write"},
    ) == []


def test_silent_when_no_allowlist():
    assert validate_stage_allowlists(
        "debugger", stage_tool_allowlist={}, granted_tool_names={"read"}) == []
    assert validate_stage_allowlists(
        "debugger", stage_tool_allowlist=None, granted_tool_names={"read"}) == []


# ── startup warn wiring (AgentTooling) ─────────────────────────────────────────

def test_agent_startup_warns_on_dead_allowlist_entries():
    """The validator must actually FIRE at agent startup — pulled unbound off
    AgentTooling and bound to a stub (same pattern as the orchestrator stall
    tests), so the wiring can't silently detach from the class."""
    from multi_agent.agents.runtime.tooling import AgentTooling

    class _Stub:
        agent_id = "verifier"
        _tool_profile_agent_type = "verifier"
        _stage_tool_allowlist = {"implementation:action": frozenset({"bug_create", "read"})}
        _tool_instances = {"read": object()}
        _logger = MagicMock()

    stub = _Stub()
    AgentTooling._validate_stage_allowlists_against_pool(stub)
    warned = "\n".join(str(c.args) for c in stub._logger.warning.call_args_list)
    assert "bug_create" in warned
    assert "read" not in warned.replace("read,", "")  # granted names not flagged

    # clean config → silent
    stub2 = _Stub()
    stub2._stage_tool_allowlist = {"implementation:action": frozenset({"read"})}
    stub2._logger = MagicMock()
    AgentTooling._validate_stage_allowlists_against_pool(stub2)
    stub2._logger.warning.assert_not_called()


# ── the REAL config has zero violations (closed-by-construction) ──────────────

def _assemble_profile(pid: str, profile: dict):
    from multi_agent.tools import (Workspace, assemble_tool_pool,
                                   create_tool_assembly_context)
    cats = profile.get("tool_categories") or []
    # Vision tools (e.g. decompose_reference) are only NAMED into the pool when a
    # non-None llm_client is present — at runtime every vision-category profile has
    # one. Model that faithfully with a stub (tool enumeration never calls it), else
    # a legitimately-granted vision tool reads as a dead allowlist entry (false red).
    _has_vision = "vision" in cats

    class _StubLLM:  # noqa: D401 — presence, not behavior, is what matters
        pass

    ctx = create_tool_assembly_context(
        agent_type=pid,
        agent_id=pid,
        workspace=Workspace(tempfile.mkdtemp(prefix=f"xval_{pid}_")),
        include_browser=("browser" in cats),
        include_docker=("docker" in cats),
        include_vision=_has_vision,
        llm_client=_StubLLM() if _has_vision else None,
        allowed_tool_categories=cats,
        allow_tools=profile.get("allow_tools") or [],
        deny_tools=profile.get("deny_tools") or [],
        assembly_mode="agent",
        tool_profile_id=pid,
        tool_bundle_ids=profile.get("tool_bundles") or [],
    )
    return {t.NAME for t in assemble_tool_pool(ctx)}


def test_real_config_has_no_dead_allowlist_entries():
    """Assemble the REAL tool pool for every profile in agents_config.yaml and
    assert every stage_tool_allowlist entry is actually granted. This is the
    structural gate that makes the 2026-06-12 cleanup permanent: a future
    allowlist entry (or bundle/category/deny change) that breaks the 4-layer
    alignment fails CI instead of silently shipping a capability the prompt
    teaches but the agent lacks."""
    from multi_agent.agents.configurable_agent import load_config

    # browser tools self-gate on playwright; without it they are legitimately
    # absent from the pool in THIS environment, not config drift.
    try:
        from tools.browser import PLAYWRIGHT_AVAILABLE
    except Exception:
        PLAYWRIGHT_AVAILABLE = False
    env_exempt = set() if PLAYWRIGHT_AVAILABLE else {"browser_"}

    profiles = load_config().get("profiles") or {}
    assert profiles, "agents_config.yaml profiles section missing"
    violations = []
    for pid, profile in profiles.items():
        allowlist = profile.get("stage_tool_allowlist") or {}
        if not allowlist:
            continue
        granted = _assemble_profile(pid, profile)
        errs = validate_stage_allowlists(
            pid, stage_tool_allowlist=allowlist, granted_tool_names=granted)
        errs = [e for e in errs
                if not any(marker in e for marker in env_exempt)]
        violations.extend(errs)
    assert violations == [], "\n".join(violations)


# ── SYS-1: skill-consult gates must be satisfiable (PROPOSAL #14 / BUG#5) ──────

def test_skill_consult_validator_flags_missing_get_skill():
    # a *_consulted gate + no get_skill in the pool → UNSATISFIABLE → flagged
    errs = validate_skill_consult_preconditions(
        "orchestrator",
        stage_tool_preconditions={"action": {"deliver_project": "release_readiness_consulted"}},
        granted_tool_names={"read", "deliver_project"})
    assert len(errs) == 1 and "get_skill" in errs[0] and "deliver_project" in errs[0]


def test_skill_consult_validator_silent_when_get_skill_granted():
    assert validate_skill_consult_preconditions(
        "orchestrator",
        stage_tool_preconditions={"action": {"deliver_project": "release_readiness_consulted"}},
        granted_tool_names={"read", "deliver_project", "get_skill"}) == []


def test_skill_consult_validator_silent_when_no_consulted_gate():
    # a non-consulted precondition (e.g. an ask-cap) does NOT require get_skill
    assert validate_skill_consult_preconditions(
        "orchestrator",
        stage_tool_preconditions={"action": {"ask_agent": "orchestrator_ask_cap"}},
        granted_tool_names={"read"}) == []


def test_real_config_skill_consult_gates_are_satisfiable():
    """SYS-1 structural gate (PROPOSAL #14): for EVERY profile in the shipped
    agents_config.yaml, if it gates any tool on a `*_consulted` precondition
    (which instructs the agent to call get_skill), the profile's ASSEMBLED tool
    pool must actually grant get_skill — else the gate is unsatisfiable and the
    agent loops the gated tool forever (run #21's 14× deliver_project = BUG#5).
    This makes the #14 fix permanent: a future `*_consulted` gate added without
    the knowledge_skill grant fails here instead of silently wedging a run."""
    from multi_agent.agents.configurable_agent import load_config
    profiles = load_config().get("profiles") or {}
    assert profiles, "agents_config.yaml profiles section missing"
    violations = []
    for pid, profile in profiles.items():
        pre = profile.get("stage_tool_preconditions") or {}
        # any *_consulted gate? (walk one level of nesting: stage -> {tool: gate})
        has_consulted = any(
            str(g).endswith("_consulted")
            for entry in pre.values()
            for g in (entry.values() if isinstance(entry, dict) else [entry]))
        if not has_consulted:
            continue
        granted = _assemble_profile(pid, profile)
        violations.extend(validate_skill_consult_preconditions(
            pid, stage_tool_preconditions=pre, granted_tool_names=granted))
    assert violations == [], "\n".join(violations)


# ── restored verifier capabilities (the breakages the audit found) ────────────

def test_verifier_granted_set_restores_audited_capabilities():
    """TOOL-C1 (bug_create), the browser-bundle import bug (browser_*), and the
    workhub_task allow/deny self-contradiction — pinned on the REAL config so
    the capabilities can't silently fall out of the verifier's pool again."""
    from multi_agent.agents.configurable_agent import load_config

    profiles = load_config().get("profiles") or {}
    granted = _assemble_profile("verifier", profiles["verifier"])

    assert "bug_create" in granted, "TOOL-C1: verifier lost bug_create again"
    assert "workhub_task" in granted, (
        "verifier cannot claim/complete the P0 tasks the orchestrator's "
        "remediation dispatches assign it")
    assert "report_progress" in granted
    try:
        from tools.browser import PLAYWRIGHT_AVAILABLE
    except Exception:
        PLAYWRIGHT_AVAILABLE = False
    if PLAYWRIGHT_AVAILABLE:
        for name in ("browser_navigate", "browser_screenshot", "browser_click",
                     "browser_fill", "browser_console", "browser_network_errors"):
            assert name in granted, f"browser bundle regressed: {name} missing"
    # delivery stays orchestrator-owned (§7) — the verifier should NOT have
    # gained the delivery write surface in this cleanup.
    assert "deliverability_check" not in granted


def test_backend_granted_set_after_cleanup():
    from multi_agent.agents.configurable_agent import load_config

    profiles = load_config().get("profiles") or {}
    granted = _assemble_profile("backend", profiles["backend"])
    assert "report_progress" in granted
    # never-granted entries were DELETED from the allowlist, not granted:
    # validation/merge authority stays with verifier/orchestrator (§6/§7).
    for name in ("run_validation", "codehub_force_merge", "bug_create",
                 "registryhub_record_contract_test",
                 "registryhub_register_verification_chain"):
        assert name not in granted, f"backend unexpectedly gained {name}"
