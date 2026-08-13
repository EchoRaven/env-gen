"""Retro LLM tools (Cutover 16).

Three tools used by orchestrator at end of generation:
- submit_retro: validates structured fields, auto-populates aggregated stats,
                stamps generation_id from session
- list_retros: list retros (optionally filtered by generation_id)
- get_retro_stats: aggregated bug/run/review stats (no LLM input needed)

Note: these tools take an explicit `hub_registry` + `generation_id` in their
constructor for tests; in production the orchestrator's tool wiring supplies
both. SubmitRetroTool and ListRetrosTool reuse the existing WorkHub page surface
for persistence.
"""

from __future__ import annotations

from typing import Any, Optional

from utils.tool import BaseTool, ToolCategory, ToolResult, create_tool_param

from multi_agent.runtime.retro_aggregator import compute_retro_stats


def _validate_list_min(value: Any, name: str, min_len: int) -> Optional[str]:
    """#675: SAY WHAT ARRIVED. Two different mistakes produced ONE message — a value that is not
    a list at all, and a list that is too short — and neither named the value received. The
    agent could only guess which it had done.

    Measured over the 249 run logs: `submit_retro` fails 1348 times, and 1128 of those (84%)
    are this one line for `plan_vs_reality`, concentrated in 23 runs at a median of 40 per run.
    That is the tightest retry loop in the corpus after the chain-reject one (#664). Per #257
    each retry is a whole step re-sending the prompt.

    The per-ITEM errors here were already good ("plan_vs_reality[0].drift_reason must be a
    non-empty string" names the index and the key); only the length/type gate was mute. A
    string is called out specifically because passing the JSON as text is the mistake this
    shape invites, and the fix for it is different from adding entries.
    """
    if not isinstance(value, list):
        got = type(value).__name__
        extra = ""
        if isinstance(value, str):
            extra = (" — it looks like the JSON was passed as TEXT; send a real list, "
                     "not a string containing one")
        return (f"{name} must be a list of >= {min_len} entries; got {got}{extra}")
    if len(value) < min_len:
        return (f"{name} must be a list of >= {min_len} entries; got {len(value)}. "
                f"Add {min_len - len(value)} more and call again.")
    return None


def _validate_pvr(items: Any) -> Optional[str]:
    err = _validate_list_min(items, "plan_vs_reality", 2)
    if err:
        return err
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            return f"plan_vs_reality[{i}] must be a dict"
        for k in ("plan_item", "actual_outcome", "drift_reason"):
            v = item.get(k)
            if not isinstance(v, str) or not v.strip():
                return f"plan_vs_reality[{i}].{k} must be a non-empty string"
    return None


def _validate_lessons(items: Any) -> Optional[str]:
    err = _validate_list_min(items, "lessons", 2)
    if err:
        return err
    for i, v in enumerate(items):
        if not isinstance(v, str) or not v.strip():
            return f"lessons[{i}] must be a non-empty string"
    return None


def _validate_prompt_changes(items: Any) -> Optional[str]:
    err = _validate_list_min(items, "proposed_prompt_changes", 1)
    if err:
        return err
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            return f"proposed_prompt_changes[{i}] must be a dict"
        for k in ("agent_profile", "change_description"):
            v = item.get(k)
            if not isinstance(v, str) or not v.strip():
                return f"proposed_prompt_changes[{i}].{k} must be a non-empty string"
    return None


class _RetroToolBase(BaseTool):
    def __init__(self, *, hub_registry=None, generation_id=None):
        super().__init__(name=self.NAME, category=ToolCategory.KNOWLEDGE)
        self.hub_registry = hub_registry
        # Constructor-arg generation_id is legacy — tool_bundles.py
        # historically defaulted it to time.time() per-assembly, which
        # produced wildly different ids across tool re-assemblies in
        # the same run and broke the retro gate's scoping. Prefer the
        # canonical id pinned on ``hub_registry.generation_id`` (set
        # by orchestrator at run start); fall back to the legacy arg
        # only when the registry isn't wired (test bootstrap).
        self._legacy_generation_id = generation_id

    @property
    def generation_id(self):
        """Return the authoritative generation id for this run.

        Prefer ``hub_registry.generation_id`` (canonical, single-source
        per run) over the constructor argument. The constructor arg
        stays as a fallback for test bootstraps that don't wire a
        full orchestrator."""
        reg_gen = getattr(self.hub_registry, "generation_id", None)
        if reg_gen is not None:
            return reg_gen
        return self._legacy_generation_id


class SubmitRetroTool(_RetroToolBase):
    NAME = "submit_retro"
    DESCRIPTION = ("Submit a generation retro. Required: plan_vs_reality (>=2 entries "
                    "with plan_item/actual_outcome/drift_reason), systematic_failures "
                    "(may be empty list if truly none), lessons (>=2), "
                    "proposed_prompt_changes (>=1 with agent_profile/change_description). "
                    "bug_stats / run_stats / review_stats are auto-populated.")

    @property
    def tool_definition(self):
        return create_tool_param(
            name=self.NAME, description=self.DESCRIPTION,
            parameters={
                "title": {"type": "string",
                          "description": "Short retro title"},
                "plan_vs_reality": {
                    "type": "array", "items": {"type": "object"},
                    "description": "List of {plan_item, actual_outcome, drift_reason} (>=2)",
                },
                "systematic_failures": {
                    "type": "array", "items": {"type": "string"},
                    "description": "Recurring failure patterns (may be empty list)",
                },
                "lessons": {
                    "type": "array", "items": {"type": "string"},
                    "description": "Lessons learned (>=2)",
                },
                "proposed_prompt_changes": {
                    "type": "array", "items": {"type": "object"},
                    "description": "List of {agent_profile, change_description} (>=1)",
                },
            },
            required=["title", "plan_vs_reality", "systematic_failures",
                       "lessons", "proposed_prompt_changes"],
        )

    async def execute(self, *, title: str, plan_vs_reality: list,
                       systematic_failures: list, lessons: list,
                       proposed_prompt_changes: list, **kwargs) -> ToolResult:
        if not isinstance(title, str) or not title.strip():
            return ToolResult(success=False, error_message="title must be non-empty")
        err = (_validate_pvr(plan_vs_reality)
               or _validate_lessons(lessons)
               or _validate_prompt_changes(proposed_prompt_changes))
        if err:
            return ToolResult(success=False, error_message=err)
        if not isinstance(systematic_failures, list):
            return ToolResult(success=False,
                              error_message="systematic_failures must be a list")

        stats = compute_retro_stats(self.hub_registry)
        metadata = {
            "generation_id": self.generation_id,
            "plan_vs_reality": plan_vs_reality,
            "systematic_failures": systematic_failures,
            "lessons": lessons,
            "proposed_prompt_changes": proposed_prompt_changes,
            **stats.to_dict(),
        }
        document = self.hub_registry.workhub.create_document(
            title=title, agent="orchestrator", kind="retro", metadata=metadata)
        return ToolResult(success=True, data={"id": document["id"], "title": document["title"]})


class ListRetrosTool(_RetroToolBase):
    NAME = "list_retros"
    DESCRIPTION = "List all retros on WorkHub (kind='retro')."

    @property
    def tool_definition(self):
        return create_tool_param(
            name=self.NAME, description=self.DESCRIPTION,
            parameters={}, required=[])

    async def execute(self, **kwargs) -> ToolResult:
        retros = self.hub_registry.gate_registry.list_retros()
        return ToolResult(success=True, data={"retros": [
            {"id": r["id"], "title": r["title"],
             "generation_id": (r.get("metadata") or {}).get("generation_id")}
            for r in retros
        ]})


class GetRetroStatsTool(_RetroToolBase):
    NAME = "get_retro_stats"
    DESCRIPTION = ("Compute aggregated bug/run/review stats across hubs. "
                    "Use this before writing your retro to inform the analysis.")

    @property
    def tool_definition(self):
        return create_tool_param(
            name=self.NAME, description=self.DESCRIPTION,
            parameters={}, required=[])

    async def execute(self, **kwargs) -> ToolResult:
        stats = compute_retro_stats(self.hub_registry)
        return ToolResult(success=True, data=stats.to_dict())


_RETRO_TOOLS = [SubmitRetroTool, ListRetrosTool, GetRetroStatsTool]


def create_retro_tools(hub_registry=None, generation_id=None) -> list:
    return [cls(hub_registry=hub_registry, generation_id=generation_id)
            for cls in _RETRO_TOOLS]


__all__ = ["SubmitRetroTool", "ListRetrosTool", "GetRetroStatsTool",
            "create_retro_tools"]
