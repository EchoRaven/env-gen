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

from multi_agent.tool_surface import validate_stage_allowlists  # noqa: E402


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
    ctx = create_tool_assembly_context(
        agent_type=pid,
        agent_id=pid,
        workspace=Workspace(tempfile.mkdtemp(prefix=f"xval_{pid}_")),
        include_browser=("browser" in cats),
        include_docker=("docker" in cats),
        include_vision=False,  # vision tools need an llm_client; none names them
        llm_client=None,
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
