"""
Utilities for auditing and shrinking agent tool surfaces.

This module centralizes:
- profile/tool-surface validation
- runtime tool-surface summaries
- lightweight tool ranking for stage-specific exposure
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from .tool_bundles import TOOL_BUNDLE_REQUIREMENTS


KNOWN_TOOL_CATEGORIES: Set[str] = {
    "file",
    "reasoning",
    "progress",
    "communication",
    "memory",
    "project",
    "analysis",
    "knowledge_read",
    "knowledge_write",
    "knowledge_skill",
    "knowledge",
    # Honest per-family categories (formerly all overloaded onto "knowledge").
    "observability",
    "coverage",
    "visual_review",
    "seed",
    "delivery",
    "mcp_registry",
    "database",
    "data_engine",
    "dependency",
    "logs",
    "runtime",
    "api",
    "api_contract",
    "web",
    "verification",
    "task_definition",
    "docker",
    "browser",
    "vision",
    "reference",
    "image_search",
    "team_spawn",
    "team_lifecycle",
    "team_reasoning",
    "team_planning",
    "codehub",
    "workhub",
    "registryhub",
    "eventhub",
    "hub",
    "run",
    "design",
    "bug",
    "milestone",  # orchestrator-only milestone roadmap tools (milestone_tools bundle)
}


STOPWORDS: Set[str] = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "how",
    "i",
    "if",
    "in",
    "into",
    "is",
    "it",
    "of",
    "on",
    "or",
    "should",
    "that",
    "the",
    "this",
    "to",
    "use",
    "using",
    "with",
    "you",
    "your",
}


def normalize_categories(values: Optional[Sequence[str]]) -> Set[str]:
    return {
        str(value).strip().lower().replace("-", "_")
        for value in (values or [])
        if str(value).strip()
    }


def validate_profile_tool_configuration(
    profile_id: str,
    *,
    tool_categories: Sequence[str],
    tool_bundle_ids: Sequence[str],
) -> List[str]:
    """Return validation errors for one profile's tool-surface config."""
    errors: List[str] = []
    normalized_categories = normalize_categories(tool_categories)
    unknown_categories = sorted(category for category in normalized_categories if category not in KNOWN_TOOL_CATEGORIES)
    if unknown_categories:
        errors.append(f"profile '{profile_id}' has unknown tool_categories: {unknown_categories}")

    for bundle_id in tool_bundle_ids or []:
        required = TOOL_BUNDLE_REQUIREMENTS.get(str(bundle_id))
        if required is None:
            errors.append(f"profile '{profile_id}' references unknown tool bundle: {bundle_id}")
            continue
        missing = sorted(required - normalized_categories)
        if missing:
            errors.append(
                f"profile '{profile_id}' bundle '{bundle_id}' missing required categories: {missing}"
            )
    return errors


def validate_stage_allowlists(
    profile_id: str,
    *,
    stage_tool_allowlist: Optional[Dict[str, Any]],
    granted_tool_names: Set[str],
) -> List[str]:
    """Cross-layer alignment check (TOOL-系统, 2026-06-12): every
    ``stage_tool_allowlist`` entry must name a tool the agent's ASSEMBLED pool
    actually grants.

    A tool reaches an agent only when four layers align (factory → bundle
    include_names → profile bundles/categories → allow/deny); the allowlist can
    only NARROW that set. The allowlists were written "deliberately generous"
    (their own yaml comments treat over-listing as a harmless no-op), so a dead
    entry reads exactly like a granted capability — the 2026-06-12 audit found
    26 of them, including the verifier's canonical failure-routing channel
    ``bug_create`` (TOOL-C1) and its entire browser toolset. One warning string
    per (stage, dead entry); empty list when the config is honest."""
    problems: List[str] = []
    granted = set(granted_tool_names or set())
    for stage, names in (stage_tool_allowlist or {}).items():
        for name in sorted(set(names or [])):
            if name not in granted:
                problems.append(
                    f"profile '{profile_id}' stage '{stage}' allowlists tool "
                    f"'{name}' but the assembled pool does not grant it — the "
                    "entry is DEAD (check factory → bundle include_names → "
                    "profile bundles/categories → allow/deny). Grant the tool "
                    "or delete the entry."
                )
    return problems


def validate_skill_consult_preconditions(
    profile_id: str,
    *,
    stage_tool_preconditions: Optional[Dict[str, Any]],
    granted_tool_names: Set[str],
) -> List[str]:
    """SYS-1 capability-satisfiability guard (PROPOSAL #14 / BUG#5): a
    ``stage_tool_precondition`` whose id ends in ``_consulted`` blocks its tool
    and instructs the agent to call ``get_skill(name=...)`` to clear the gate
    (preconditions._require_skill_consulted). So the profile MUST grant
    ``get_skill`` (the ``knowledge_skill`` category / ``knowledge_skill_tools``
    bundle) — otherwise the gate is UNSATISFIABLE and the agent loops the gated
    tool forever (run #21: 14× deliver_project, killed). Sibling to
    ``validate_stage_allowlists``: one problem string per offending
    (stage, tool) gate; empty list when the config is satisfiable.

    Accepts either the runtime shape ``{stage: {tool: gate_id}}`` or the flat
    ``{tool: gate_id}`` — walks one level of nesting either way."""
    if "get_skill" in (granted_tool_names or set()):
        return []  # satisfiable — nothing to flag
    problems: List[str] = []
    for stage, entry in (stage_tool_preconditions or {}).items():
        items = entry.items() if isinstance(entry, dict) else [(stage, entry)]
        for tool, gate in items:
            if str(gate).endswith("_consulted"):
                problems.append(
                    f"profile '{profile_id}' gates '{tool}' on '{gate}' (a skill-consult "
                    "precondition that instructs the agent to call get_skill) but the "
                    "assembled pool does NOT grant get_skill — the gate is UNSATISFIABLE. "
                    "Grant the 'knowledge_skill' category (or 'knowledge_skill_tools' "
                    "bundle). PROPOSAL #14 / BUG#5."
                )
    return problems


def build_profile_tool_audit(profiles: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Build a static profile-level audit report from config only."""
    report: Dict[str, Any] = {}
    for profile_id, profile in profiles.items():
        categories = sorted(normalize_categories(profile.get("tool_categories", [])))
        bundles = [str(bundle) for bundle in (profile.get("tool_bundles") or [])]
        bundle_status: List[Dict[str, Any]] = []
        for bundle in bundles:
            required = sorted(TOOL_BUNDLE_REQUIREMENTS.get(bundle, set()))
            missing = sorted(set(required) - set(categories))
            bundle_status.append(
                {
                    "bundle": bundle,
                    "required_categories": required,
                    "missing_categories": missing,
                    "status": "dead" if missing else "active",
                }
            )
        report[profile_id] = {
            "tool_categories": categories,
            "bundle_status": bundle_status,
            "allow_tools": list(profile.get("allow_tools") or []),
            "deny_tools": list(profile.get("deny_tools") or []),
            "validation_errors": validate_profile_tool_configuration(
                profile_id,
                tool_categories=profile.get("tool_categories", []),
                tool_bundle_ids=bundles,
            ),
        }
    return report


def summarize_tool_surface(tool_instances: Dict[str, Any]) -> Dict[str, Any]:
    """Summarize a registered tool pool for logging/auditing."""
    by_category: Dict[str, int] = {}
    names = sorted(tool_instances.keys())
    for tool in tool_instances.values():
        categories = sorted(getattr(tool, "_tool_surface_categories", set()) or set())
        if not categories:
            by_category["uncategorized"] = by_category.get("uncategorized", 0) + 1
            continue
        for category in categories:
            by_category[category] = by_category.get(category, 0) + 1
    return {
        "count": len(tool_instances),
        "names": names,
        "by_category": dict(sorted(by_category.items())),
    }


def rank_tool_names(
    *,
    tool_instances: Dict[str, Any],
    candidate_names: Iterable[str],
    query_text: str,
    preferred_categories: Optional[Set[str]] = None,
    limit: int = 10,
    always_include: Optional[Iterable[str]] = None,
) -> List[str]:
    """
    Rank candidate tools for a specific stage/query.

    This is intentionally lightweight and deterministic:
    - prefer tools whose categories match the current stage
    - prefer tools whose name/description tokens overlap the request
    - keep a small top-k visible to the LLM
    """
    preferred_categories = set(preferred_categories or set())
    always_include = [name for name in (always_include or []) if name in set(candidate_names)]
    query_tokens = _tokenize(query_text)

    scored: List[Tuple[float, str]] = []
    for name in candidate_names:
        tool = tool_instances.get(name)
        if tool is None:
            continue
        categories = set(getattr(tool, "_tool_surface_categories", set()) or set())
        description = _get_tool_description(tool)
        name_tokens = _tokenize(name.replace("_", " "))
        desc_tokens = _tokenize(description)

        overlap = len(query_tokens & (name_tokens | desc_tokens))
        prefix_match = sum(1 for token in query_tokens if any(part.startswith(token) for part in name_tokens))
        category_bonus = len(preferred_categories & categories)
        exact_name_bonus = 1 if name in query_text else 0
        score = (category_bonus * 4.0) + (overlap * 2.0) + (prefix_match * 1.0) + exact_name_bonus
        scored.append((score, name))

    ranked = [name for _, name in sorted(scored, key=lambda item: (-item[0], item[1]))]
    result: List[str] = []
    seen = set()
    for name in always_include + ranked:
        if name in seen:
            continue
        seen.add(name)
        result.append(name)
        if len(result) >= max(limit, len(always_include)):
            break
    return result


def _tokenize(text: str) -> Set[str]:
    lowered = str(text or "").lower()
    tokens = {token for token in re.findall(r"[a-z0-9_]{2,}", lowered) if token not in STOPWORDS}
    return tokens


def _get_tool_description(tool: Any) -> str:
    description = getattr(tool, "DESCRIPTION", None)
    if description:
        return str(description)
    try:
        tool_def = tool.tool_definition
        if isinstance(tool_def, dict):
            return str(tool_def.get("description", "") or "")
    except Exception:
        pass
    return ""
