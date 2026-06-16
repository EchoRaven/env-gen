"""TOOL-系统 (prompt side) — every v3 ``tool_policy`` entry must name a tool the
agent is actually granted.

``test_tool_allowlist_cross_validator`` closed the allowlist↔grant blind spot;
``test_v3_prompts_reference_real_tools`` only checks a tool exists *somewhere*
in the global registry — neither checks that a tool the PROMPT tells THIS agent
to call is in THIS agent's assembled pool. That gap let the verifier prompt
teach ``deliverability_check`` (an orchestrator-only delivery tool) across 10
locations for weeks while the verifier was never granted it (TOOL-C2). The
prompt taught a release_readiness step the verifier physically could not run;
release/delivery is the orchestrator's gate (preconditions.release_readiness_
consulted is wired ONLY on the orchestrator's deliver_project / report_completion).

The high-signal surface is each v3 prompt's structured ``tool_policy=[{"tool":
"...", "when": ...}]`` block — an explicit "tools YOU use" declaration (vs prose
that may mention another role's tools or a forbidden tool). A tool_policy entry
naming an ungranted tool is the prompt half of the same 4-layer drift the
cross-validator catches on the allowlist half.

This is a RATCHET: the union of gaps across all profiles must equal exactly
``KNOWN_PRE_EXISTING_GAPS`` (documented TOOL-C2-class debt in OTHER agents, out
of scope for the 2026-06-12 verifier fix). A NEW gap fails CI; fixing a known
gap requires removing it from the set. The verifier is deliberately absent from
the set — any verifier prompt↔grant drift fails immediately.
"""

from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

PROMPT_DIR = LLM_DIR / "multi_agent" / "prompts"

# Pre-existing prompt↔grant drift in agents NOT touched by the 2026-06-12
# TOOL-C2 verifier fix. Each is a v3 tool_policy entry naming a tool the
# profile's assembled pool does not grant. Tracked in the review backlog
# (TOOL-C2 follow-up); fixing one = grant the tool OR drop the policy entry,
# then delete it here. The verifier is intentionally NOT listed.
KNOWN_PRE_EXISTING_GAPS = frozenset({
    # "wait / sleep / explicit poll" anti-stall phrasing — sleep is a concept,
    # not a registered tool (the real granted tool in that slash-group is `wait`).
    ("orchestrator", "sleep"),
    # knowledge profile lacks codehub/registryhub/workhub/snapshot grants but its
    # tool_policy names read tools for the "broken trigger artifact" fallback.
    ("knowledge", "codehub_get_diff"),
    ("knowledge", "get_example_patterns"),
    ("knowledge", "hub_snapshot"),
    ("knowledge", "registryhub_get_endpoint"),
    ("knowledge", "workhub_get_document"),
    # worker profiles describe reading diffs / PR files / contracts they aren't granted.
    ("analysis_worker", "codehub_get_diff"),
    ("analysis_worker", "codehub_get_file_content"),
    ("review_worker", "codehub_get_diff"),
    ("review_worker", "codehub_get_file_content"),
    ("review_worker", "codehub_list_inline_comments"),
    ("review_worker", "registryhub_get_endpoint"),
    ("review_worker", "registryhub_list_tables"),
    ("worker", "codehub_commit"),
    ("worker", "codehub_open_pr"),
})

_TOOL_RE = re.compile(r'"tool"\s*:\s*"([^"]+)"')
_IDENT_RE = re.compile(r"[a-z_][a-z0-9_]*\Z")


def _playwright_available() -> bool:
    try:
        from tools.browser import PLAYWRIGHT_AVAILABLE
        return bool(PLAYWRIGHT_AVAILABLE)
    except Exception:
        return False


def _tool_policy_tools(template_rel: str) -> set:
    """Extract the tool NAMES declared in a prompt's ``tool_policy`` block.

    A ``"tool"`` value may be slash-grouped (``"docker_up / docker_build"``) or
    carry a parenthetical annotation (``"send_message (to orchestrator)"``).
    Split on ``/``, drop ``(...)``, keep identifier-shaped tokens only.
    """
    text = (PROMPT_DIR / template_rel).read_text()
    names: set = set()
    for raw in _TOOL_RE.findall(text):
        raw = re.sub(r"\([^)]*\)", "", raw)
        for token in raw.split("/"):
            token = token.strip().strip("`").strip()
            if _IDENT_RE.fullmatch(token):
                names.add(token)
    return names


def _assemble_profile(pid: str, profile: dict) -> set:
    from multi_agent.tools import (Workspace, assemble_tool_pool,
                                   create_tool_assembly_context)
    cats = profile.get("tool_categories") or []
    ctx = create_tool_assembly_context(
        agent_type=pid,
        agent_id=pid,
        workspace=Workspace(tempfile.mkdtemp(prefix=f"ppg_{pid}_")),
        include_browser=("browser" in cats),
        include_docker=("docker" in cats),
        include_vision=False,
        llm_client=None,
        allowed_tool_categories=cats,
        allow_tools=profile.get("allow_tools") or [],
        deny_tools=profile.get("deny_tools") or [],
        assembly_mode="agent",
        tool_profile_id=pid,
        tool_bundle_ids=profile.get("tool_bundles") or [],
    )
    return {t.NAME for t in assemble_tool_pool(ctx)}


def _all_gaps() -> set:
    """(profile, tool) pairs where a tool_policy entry is not granted.

    Browser tools self-gate on playwright; absent it they are legitimately not
    in the pool in THIS environment (not config drift), so they are exempt —
    same rule as test_tool_allowlist_cross_validator.
    """
    from multi_agent.agents.configurable_agent import load_config
    pw = _playwright_available()
    profiles = load_config().get("profiles") or {}
    gaps: set = set()
    for pid, profile in profiles.items():
        template = (profile.get("prompts") or {}).get("template")
        if not template:
            continue
        granted = _assemble_profile(pid, profile)
        for tool in _tool_policy_tools(template):
            if tool in granted:
                continue
            if not pw and tool.startswith("browser_"):
                continue
            gaps.add((pid, tool))
    return gaps


# ── the ratchet ─────────────────────────────────────────────────────────────

def test_tool_policy_grant_gaps_equal_known_set():
    """Union of all prompt tool_policy↔grant gaps must equal the documented
    pre-existing set exactly — a NEW gap (any agent) fails; a FIXED gap must be
    removed from KNOWN_PRE_EXISTING_GAPS."""
    gaps = _all_gaps()
    new = sorted(gaps - KNOWN_PRE_EXISTING_GAPS)
    stale = sorted(KNOWN_PRE_EXISTING_GAPS - gaps)
    assert not new, (
        "NEW prompt tool_policy↔grant drift (a prompt tells an agent to call a "
        f"tool it isn't granted): {new}. Grant the tool (category/bundle) or "
        "drop the tool_policy entry.")
    assert not stale, (
        "These KNOWN_PRE_EXISTING_GAPS no longer exist — delete them from the "
        f"set so the ratchet stays tight: {stale}")


# ── the specific TOOL-C2 fix, hard-pinned ─────────────────────────────────────

def test_verifier_tool_policy_fully_granted_and_no_deliverability_check():
    """The verifier is absent from KNOWN_PRE_EXISTING_GAPS — pin that directly:
    every verifier tool_policy entry is granted, and deliverability_check (the
    orchestrator-owned delivery tool the prompt taught for weeks) is gone."""
    from multi_agent.agents.configurable_agent import load_config

    profiles = load_config().get("profiles") or {}
    verifier = profiles["verifier"]
    template = verifier["prompts"]["template"]
    policy = _tool_policy_tools(template)
    granted = _assemble_profile("verifier", verifier)
    pw = _playwright_available()

    missing = sorted(
        t for t in policy
        if t not in granted and not (not pw and t.startswith("browser_")))
    assert missing == [], f"verifier tool_policy names ungranted tools: {missing}"

    assert "deliverability_check" not in policy, (
        "verifier prompt re-introduced deliverability_check — delivery/release "
        "is the orchestrator's gate (TOOL-C2)")
    # the capabilities the cleanup relies on ARE granted + declared:
    assert "bug_create" in granted and "run_validation" in granted
