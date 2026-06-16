"""
Claude-style tool runtime scaffolding for env generation agents.

Phase 1 goal:
- Introduce a unified tool assembly context instead of hard-wiring every caller
  directly to role-specific helper functions.
- Keep existing BaseTool implementations intact.
- Let legacy get_agent_tools()/get_all_tools() wrappers delegate into one shared
  pool assembly path.
"""

from dataclasses import dataclass, field
from typing import Any, Iterable, List, Optional, Sequence, Set

from utils.tool import BaseTool


def normalize_category_filter(values: Optional[Sequence[str]]) -> Optional[Set[str]]:
    """Normalize category filters to a stable lowercase set."""
    if not values:
        return None
    normalized = {
        str(value).strip().lower().replace("-", "_")
        for value in values
        if str(value).strip()
    }
    return normalized or None


def normalize_tool_name_filter(values: Optional[Sequence[str]]) -> Optional[Set[str]]:
    """Normalize tool name filters to a stable lowercase set."""
    if not values:
        return None
    normalized = {
        str(value).strip()
        for value in values
        if str(value).strip()
    }
    return normalized or None


def category_enabled(allowed: Optional[Set[str]], *keys: str) -> bool:
    """Check whether any requested category key is enabled."""
    if allowed is None:
        return True
    return any(str(key).strip().lower().replace("-", "_") in allowed for key in keys)


def dedupe_tools_by_name(tools: Sequence[BaseTool]) -> List[BaseTool]:
    """Deduplicate tools by final exposed name while preserving order."""
    deduped: List[BaseTool] = []
    seen = set()
    for tool in tools:
        name = getattr(tool, "NAME", None) or getattr(tool, "name", None)
        if not name or name in seen:
            continue
        seen.add(name)
        deduped.append(tool)
    return deduped


def filter_tools_by_name(
    tools: Sequence[BaseTool],
    *,
    allow_tools: Optional[Set[str]] = None,
    deny_tools: Optional[Set[str]] = None,
) -> List[BaseTool]:
    """Filter a tool pool by explicit allow/deny name lists."""
    filtered: List[BaseTool] = []
    for tool in tools:
        name = getattr(tool, "NAME", None) or getattr(tool, "name", None)
        if not name:
            continue
        if deny_tools and name in deny_tools:
            continue
        if allow_tools is not None and name not in allow_tools:
            continue
        filtered.append(tool)
    return filtered


@dataclass(frozen=True)
class ToolPermissionContext:
    """Minimal Claude-style permission/filter context for tool exposure."""

    allowed_categories: Optional[Set[str]] = None
    allow_tools: Optional[Set[str]] = None
    deny_tools: Optional[Set[str]] = None
    mode: str = "default"
    should_avoid_permission_prompts: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolAssemblyContext:
    """Unified assembly context shared by all tool pool builders."""

    agent_type: str
    workspace: Any
    agent_id: Optional[str] = None
    include_browser: bool = False
    include_docker: bool = False
    include_vision: bool = False
    llm_client: Any = None
    hub_workspace: Any = None
    permission_context: ToolPermissionContext = field(default_factory=ToolPermissionContext)
    assembly_mode: str = "agent"
    tool_profile_id: Optional[str] = None
    tool_bundle_ids: List[str] = field(default_factory=list)


class ToolPoolBuilder:
    """Collect tools through one shared assembly/filter pipeline."""

    def __init__(self, context: ToolAssemblyContext):
        self.context = context
        self._tools: List[BaseTool] = []

    def add(
        self,
        tools: Iterable[BaseTool],
        *categories: str,
        always: bool = False,
        when: bool = True,
    ) -> None:
        if not when:
            return
        normalized_categories = {
            str(category).strip().lower().replace("-", "_")
            for category in categories
            if str(category).strip()
        }
        if not always and not category_enabled(
            self.context.permission_context.allowed_categories,
            *normalized_categories,
        ):
            return
        for tool in tools:
            if normalized_categories:
                existing = set(getattr(tool, "_tool_surface_categories", set()) or set())
                setattr(tool, "_tool_surface_categories", existing | normalized_categories)
            self._tools.append(tool)

    def build(self) -> List[BaseTool]:
        tools = dedupe_tools_by_name(self._tools)
        return filter_tools_by_name(
            tools,
            allow_tools=self.context.permission_context.allow_tools,
            deny_tools=self.context.permission_context.deny_tools,
        )

