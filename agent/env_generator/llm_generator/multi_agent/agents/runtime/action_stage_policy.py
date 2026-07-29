"""Per-role action-stage policy (Orch-F1).

Every agent walks ``ACTION_INTERNAL_STAGES`` (communicate / edit_code /
run_checks / delegate_team / deliver) once per action round, and EACH stage
costs one LLM call. That is right for an implementation lane, wrong for a
coordinator: in the r93 tiktok run the Orchestrator spent 166 of its 1164
responses (14.3% of calls, ~14.9M response-context tokens) answering
``edit_code`` with "no code to edit" / "not an edit_code task". The fast-skip
in ``step_pipeline/action.py`` (``no_stage_tools_available``) never fires for
it because its memory/file/project tools legitimately map to the edit_code
category hint — there ARE tools, the ROLE just never edits code.

This module lets a profile declare which internal stages it runs
(``execution_pipeline.action_stages``) so a disabled stage is skipped without
an LLM call.

The subtlety that makes this more than a one-line filter: the per-stage
category hints feed ``rank_tool_names``' ``category_bonus * 4.0``, so a stage
is also the *home* of its categories. Dropping ``edit_code`` outright would
demote every tool that lived only there — for the orchestrator that is
``read`` (11 calls in r93), ``update_memory_bank`` (10) and
``codehub_get_file_content`` (2) — recreating the "orphan class"
(``tool_surface.detect_orphaned_tool_offerings``): granted, prompt-mandated,
never offered, lane wedges on MALFORMED_FUNCTION_CALL.

So a profile that disables a stage must RE-HOME that stage's categories via
``execution_pipeline.action_stage_categories`` (unioned into an enabled
stage's hints), and ``parse_action_stage_config`` refuses at construction any
config that would strand a category the profile is actually granted. The
failure is a startup ValueError, not a wedged run.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, Optional, Set, Tuple

__all__ = [
    "round_plan_fires_every_round",
    "resolve_enabled_action_stages",
    "resolve_stage_category_hints",
    "stage_category_hints_for",
    "parse_action_stage_config",
]


def resolve_enabled_action_stages(agent: Any) -> Tuple[str, ...]:
    """The internal stages ``agent`` actually runs, in engine order.

    Engine order always wins over the order the profile listed them in — a
    round must still communicate before it delivers. Degrades to the agent's
    declared stages when no allowlist is set (and to ``()`` for an object that
    declares none, so callers can iterate unconditionally).
    """
    declared: Tuple[str, ...] = tuple(
        getattr(agent, "ACTION_INTERNAL_STAGES", ()) or ())
    allowlist = getattr(agent, "_action_stages_allowlist", None)
    if not allowlist:
        return declared
    allowed = set(allowlist)
    return tuple(stage for stage in declared if stage in allowed)


def resolve_stage_category_hints(agent: Any) -> Dict[str, Set[str]]:
    """``ACTION_STAGE_CATEGORY_HINTS`` with the profile's overrides unioned in.

    Union, not replace: an override says "this stage ALSO homes these
    categories", so a profile re-homing ``file``/``memory`` never has to
    restate the stage's built-in categories (and can't silently drop one).
    Returns a fresh dict of fresh sets — the class-level default is shared
    across every agent instance and must not be mutated.
    """
    base: Dict[str, Set[str]] = {
        stage: set(categories or set())
        for stage, categories in (
            getattr(agent, "ACTION_STAGE_CATEGORY_HINTS", {}) or {}).items()
    }
    overrides = getattr(agent, "_action_stage_category_overrides", None) or {}
    for stage, categories in overrides.items():
        base.setdefault(stage, set()).update(categories or set())
    return base


def stage_category_hints_for(agent: Any, stage_name: str) -> Set[str]:
    """Preferred categories for one stage — the ranker's read path."""
    return set(resolve_stage_category_hints(agent).get(stage_name, set()))


def parse_action_stage_config(
    *,
    agent_id: str,
    exec_cfg: Optional[Dict[str, Any]],
    all_stages: Iterable[str],
    base_hints: Dict[str, Set[str]],
    granted_categories: Optional[Set[str]] = None,
) -> Tuple[Optional[Tuple[str, ...]], Dict[str, Set[str]]]:
    """Validate + normalize a profile's action-stage config.

    Returns ``(allowlist_or_None, category_overrides)``. Absent config is a
    no-op so every existing profile keeps today's behavior exactly.

    Fails closed (``ValueError`` at construction, mirroring
    ``stage_tool_preconditions``) on:
      * an unknown stage name in either key — a typo would otherwise silently
        disable nothing (allowlist) or home nothing (overrides);
      * a config that leaves a category the profile is GRANTED without an
        enabled stage to home it — the orphan class this whole guard exists
        to prevent.
    """
    exec_cfg = exec_cfg or {}
    known = tuple(all_stages)
    known_set = set(known)

    raw_overrides = exec_cfg.get("action_stage_categories") or {}
    overrides: Dict[str, Set[str]] = {}
    unknown_override_stages = sorted(
        str(stage) for stage in raw_overrides if str(stage) not in known_set)
    if unknown_override_stages:
        raise ValueError(
            f"agent {agent_id}: execution_pipeline.action_stage_categories "
            f"references unknown action stage(s) {unknown_override_stages}. "
            f"Valid stages: {sorted(known_set)}."
        )
    for stage, categories in raw_overrides.items():
        cats = {str(c) for c in (categories or [])}
        if cats:
            overrides[str(stage)] = cats

    raw_allowlist = exec_cfg.get("action_stages")
    if raw_allowlist is None:
        return None, overrides

    requested = [str(stage) for stage in raw_allowlist]
    unknown = sorted(set(requested) - known_set)
    if unknown:
        raise ValueError(
            f"agent {agent_id}: execution_pipeline.action_stages references "
            f"unknown action stage(s) {unknown}. Valid stages: "
            f"{sorted(known_set)}."
        )
    allowlist = tuple(stage for stage in known if stage in set(requested))

    # Orphan guard. A category is reachable when some ENABLED stage hints it
    # (after overrides). Only categories the profile is actually granted
    # matter — dropping `image_search` from a profile that owns no
    # image_search tool costs nothing.
    reachable: Set[str] = set()
    for stage in allowlist:
        reachable |= set(base_hints.get(stage, set()) or set())
        reachable |= overrides.get(stage, set())
    disabled_categories: Set[str] = set()
    for stage in known:
        if stage not in set(allowlist):
            disabled_categories |= set(base_hints.get(stage, set()) or set())
    stranded = sorted(
        (disabled_categories - reachable) & set(granted_categories or set()))
    if stranded:
        raise ValueError(
            f"agent {agent_id}: execution_pipeline.action_stages disables "
            f"stage(s) that are the only home of granted tool categor(ies) "
            f"{stranded}. Those tools would keep their grant but lose the "
            f"ranker's category bonus in every stage the role still runs "
            f"(the orphan class — granted, never offered, lane wedges). "
            f"Re-home them with execution_pipeline.action_stage_categories, "
            f"e.g. {{'{allowlist[-1] if allowlist else 'run_checks'}': "
            f"{stranded}}}, or drop the categories from tool_categories."
        )
    return allowlist, overrides


def round_plan_fires_every_round(agent: Any) -> bool:
    """Whether the per-round planning call runs on EVERY action round.

    Default False: round 0 plans, later rounds inherit it. The round-plan call
    passes ``tools=[]`` (it cannot act) and appends its own text to
    ``messages``, so from round 1 on it re-derives a plan already sitting in
    the model's context. With ``max_action_rounds_per_step`` at 15 that is up
    to 14 full-context calls per step for no new information -- part of the
    ~30% of all r91/r92/r93 LLM calls that carried an empty tool list.

    A profile may set ``execution_pipeline.action_round_plan: all`` to restore
    the per-round plan. Any other value (including a typo) keeps the cheap
    default rather than silently re-enabling the expensive path.
    """
    cfg = getattr(agent, "_execution_pipeline_cfg", None) or {}
    try:
        value = str(cfg.get("action_round_plan", "") or "").strip().lower()
    except Exception:
        return False
    return value == "all"
