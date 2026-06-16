"""Structured knowledge tools - ADR / Runbook / Postmortem (Cutover 15).

Wraps the existing KnowledgeStore with shape-validated submit + list helpers
for engineering documents. Free-form `store_knowledge` continues to work
for ad-hoc notes; these tools enforce structure for the 3 document types.

The underlying KnowledgeStore schema does not have a dedicated
`structured_fields` column, so we stash the structured payload as a JSON
blob inside the existing `content` column under a sentinel prefix. The
list helpers parse it back so callers see the structured dict.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

from utils.tool import BaseTool, ToolCategory, ToolResult, create_tool_param

from .knowledge_tools import _get_store

logger = logging.getLogger(__name__)


_ADR_STATUS = ("proposed", "accepted", "deprecated", "superseded")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_STRUCTURED_PREFIX = "__structured_fields__:"


def _import_types():
    from multi_agent.knowledge.types import Knowledge, KnowledgeCategory
    return Knowledge, KnowledgeCategory


def _encode_structured(fields: Dict[str, Any]) -> str:
    """Serialise structured_fields into the `content` column."""
    return _STRUCTURED_PREFIX + json.dumps(fields, ensure_ascii=False)


def _decode_structured(knowledge) -> Dict[str, Any]:
    """Recover structured_fields from a Knowledge loaded from the store.

    Prefers the in-memory `structured_fields` attribute when populated
    (e.g. fresh objects), otherwise parses the sentinel JSON from `content`.
    """
    fields = getattr(knowledge, "structured_fields", None) or {}
    if fields:
        return fields
    content = getattr(knowledge, "content", "") or ""
    if content.startswith(_STRUCTURED_PREFIX):
        try:
            return json.loads(content[len(_STRUCTURED_PREFIX):])
        except json.JSONDecodeError:
            return {}
    return {}


def _validate_nonempty_str(value: Any, name: str) -> Optional[str]:
    if not isinstance(value, str) or not value.strip():
        return f"{name} must be a non-empty string"
    return None


def _validate_str_list_min(value: Any, name: str, min_len: int) -> Optional[str]:
    if not isinstance(value, list) or len(value) < min_len:
        return f"{name} must be a list of length >= {min_len}"
    bad = [i for i, v in enumerate(value) if not isinstance(v, str) or not v.strip()]
    if bad:
        return f"{name} entries at index {bad} are empty or non-string"
    return None


class SubmitADRTool(BaseTool):
    """Submit an Architecture Decision Record."""

    NAME = "submit_adr"
    DESCRIPTION = (
        "Submit an Architecture Decision Record. Required: title, decision, "
        "context, alternatives (list, >=1), consequences, status "
        "(proposed | accepted | deprecated | superseded)."
    )

    def __init__(self):
        super().__init__(name=self.NAME, category=ToolCategory.KNOWLEDGE)

    @property
    def tool_definition(self) -> dict:
        return create_tool_param(
            name=self.NAME,
            description=self.DESCRIPTION,
            parameters={
                "title": {"type": "string", "description": "Short ADR title"},
                "decision": {"type": "string", "description": "The decision that was made"},
                "context": {"type": "string", "description": "Why the decision was needed"},
                "alternatives": {
                    "type": "array", "items": {"type": "string"},
                    "description": "Alternatives considered (at least 1)",
                },
                "consequences": {"type": "string", "description": "Consequences of the decision"},
                "status": {
                    "type": "string", "enum": list(_ADR_STATUS),
                    "description": "ADR status (default: accepted)",
                },
                "tags": {
                    "type": "array", "items": {"type": "string"},
                    "description": "Optional tags",
                },
            },
            required=["title", "decision", "context", "alternatives", "consequences"],
        )

    async def execute(
        self,
        title: str,
        decision: str,
        context: str,
        alternatives: List[str],
        consequences: str,
        status: str = "accepted",
        tags: Optional[List[str]] = None,
        **kwargs,
    ) -> ToolResult:
        for value, name in [
            (title, "title"), (decision, "decision"),
            (context, "context"), (consequences, "consequences"),
        ]:
            err = _validate_nonempty_str(value, name)
            if err:
                return ToolResult.fail(err)
        err = _validate_str_list_min(alternatives, "alternatives", 1)
        if err:
            return ToolResult.fail(err)
        if status not in _ADR_STATUS:
            return ToolResult.fail(
                f"status must be one of {list(_ADR_STATUS)}"
            )

        Knowledge, KnowledgeCategory = _import_types()
        fields = {
            "decision": decision,
            "context": context,
            "alternatives": alternatives,
            "consequences": consequences,
            "status": status,
        }
        k = Knowledge(
            title=title,
            category=KnowledgeCategory.ADR,
            summary=decision,
            content=_encode_structured(fields),
            tags=list(tags or []),
            source="agent",
            structured_fields=fields,
        )
        try:
            knowledge_id = _get_store().add(k)
        except Exception as e:
            logger.error(f"Failed to store ADR: {e}")
            return ToolResult.fail(f"Store failed: {e}")
        return ToolResult.ok({"id": knowledge_id, "title": k.title})


class SubmitRunbookTool(BaseTool):
    """Submit an operational runbook."""

    NAME = "submit_runbook"
    DESCRIPTION = (
        "Submit a Runbook. Required: title, trigger, steps (list, >=3), "
        "verification, rollback."
    )

    def __init__(self):
        super().__init__(name=self.NAME, category=ToolCategory.KNOWLEDGE)

    @property
    def tool_definition(self) -> dict:
        return create_tool_param(
            name=self.NAME,
            description=self.DESCRIPTION,
            parameters={
                "title": {"type": "string", "description": "Short runbook title"},
                "trigger": {"type": "string", "description": "When to run this"},
                "steps": {
                    "type": "array", "items": {"type": "string"},
                    "description": "Ordered procedure steps (>=3)",
                },
                "verification": {"type": "string", "description": "How to confirm success"},
                "rollback": {"type": "string", "description": "Rollback procedure"},
                "tags": {
                    "type": "array", "items": {"type": "string"},
                    "description": "Optional tags",
                },
            },
            required=["title", "trigger", "steps", "verification", "rollback"],
        )

    async def execute(
        self,
        title: str,
        trigger: str,
        steps: List[str],
        verification: str,
        rollback: str,
        tags: Optional[List[str]] = None,
        **kwargs,
    ) -> ToolResult:
        for value, name in [
            (title, "title"), (trigger, "trigger"),
            (verification, "verification"), (rollback, "rollback"),
        ]:
            err = _validate_nonempty_str(value, name)
            if err:
                return ToolResult.fail(err)
        err = _validate_str_list_min(steps, "steps", 3)
        if err:
            return ToolResult.fail(err)

        Knowledge, KnowledgeCategory = _import_types()
        fields = {
            "trigger": trigger,
            "steps": steps,
            "verification": verification,
            "rollback": rollback,
        }
        k = Knowledge(
            title=title,
            category=KnowledgeCategory.RUNBOOK,
            summary=trigger,
            content=_encode_structured(fields),
            tags=list(tags or []),
            source="agent",
            structured_fields=fields,
        )
        try:
            knowledge_id = _get_store().add(k)
        except Exception as e:
            logger.error(f"Failed to store runbook: {e}")
            return ToolResult.fail(f"Store failed: {e}")
        return ToolResult.ok({"id": knowledge_id, "title": k.title})


class SubmitPostmortemTool(BaseTool):
    """Submit an incident postmortem."""

    NAME = "submit_postmortem"
    DESCRIPTION = (
        "Submit a Postmortem. Required: title, incident_date (YYYY-MM-DD), "
        "impact, timeline (list, >=3 entries), root_cause, "
        "action_items (list, >=1)."
    )

    def __init__(self):
        super().__init__(name=self.NAME, category=ToolCategory.KNOWLEDGE)

    @property
    def tool_definition(self) -> dict:
        return create_tool_param(
            name=self.NAME,
            description=self.DESCRIPTION,
            parameters={
                "title": {"type": "string", "description": "Short postmortem title"},
                "incident_date": {
                    "type": "string",
                    "description": "Incident date in YYYY-MM-DD format",
                },
                "impact": {"type": "string", "description": "What broke and for whom"},
                "timeline": {
                    "type": "array", "items": {"type": "string"},
                    "description": "Timeline entries (>=3)",
                },
                "root_cause": {"type": "string", "description": "Why it happened"},
                "action_items": {
                    "type": "array", "items": {"type": "string"},
                    "description": "Action items (>=1)",
                },
                "tags": {
                    "type": "array", "items": {"type": "string"},
                    "description": "Optional tags",
                },
            },
            required=[
                "title", "incident_date", "impact", "timeline",
                "root_cause", "action_items",
            ],
        )

    async def execute(
        self,
        title: str,
        incident_date: str,
        impact: str,
        timeline: List[str],
        root_cause: str,
        action_items: List[str],
        tags: Optional[List[str]] = None,
        **kwargs,
    ) -> ToolResult:
        for value, name in [
            (title, "title"), (impact, "impact"), (root_cause, "root_cause"),
        ]:
            err = _validate_nonempty_str(value, name)
            if err:
                return ToolResult.fail(err)
        if not isinstance(incident_date, str) or not _DATE_RE.match(incident_date):
            return ToolResult.fail("incident_date must be YYYY-MM-DD")
        err = _validate_str_list_min(timeline, "timeline", 3)
        if err:
            return ToolResult.fail(err)
        err = _validate_str_list_min(action_items, "action_items", 1)
        if err:
            return ToolResult.fail(err)

        Knowledge, KnowledgeCategory = _import_types()
        fields = {
            "incident_date": incident_date,
            "impact": impact,
            "timeline": timeline,
            "root_cause": root_cause,
            "action_items": action_items,
        }
        k = Knowledge(
            title=title,
            category=KnowledgeCategory.POSTMORTEM,
            summary=impact,
            content=_encode_structured(fields),
            tags=list(tags or []),
            source="agent",
            structured_fields=fields,
        )
        try:
            knowledge_id = _get_store().add(k)
        except Exception as e:
            logger.error(f"Failed to store postmortem: {e}")
            return ToolResult.fail(f"Store failed: {e}")
        return ToolResult.ok({"id": knowledge_id, "title": k.title})


def _list_by_category(
    category,
    status_filter: Optional[str] = None,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """Helper: query KnowledgeStore for entries of a given category."""
    store = _get_store()
    # KnowledgeStore.list_all fetches every entry; we filter by category in
    # Python so we stay portable across both sqlite and postgres backends.
    fetch_cap = max(limit * 4, 100)
    try:
        all_entries = list(store.list_all(limit=fetch_cap))
    except TypeError:
        all_entries = list(store.list_all())

    out: List[Dict[str, Any]] = []
    for k in all_entries:
        if getattr(k, "category", None) != category:
            continue
        fields = _decode_structured(k)
        if status_filter and fields.get("status") != status_filter:
            continue
        created_at = getattr(k, "created_at", None)
        out.append({
            "id": k.id,
            "title": k.title,
            "structured_fields": fields,
            "tags": list(getattr(k, "tags", []) or []),
            "created_at": created_at.isoformat() if hasattr(created_at, "isoformat") else str(created_at),
        })
        if len(out) >= limit:
            break
    return out


class ListADRsTool(BaseTool):
    """List Architecture Decision Records, optionally filtered by status."""

    NAME = "list_adrs"
    DESCRIPTION = "List Architecture Decision Records, optionally filtered by status."

    def __init__(self):
        super().__init__(name=self.NAME, category=ToolCategory.KNOWLEDGE)

    @property
    def tool_definition(self) -> dict:
        return create_tool_param(
            name=self.NAME,
            description=self.DESCRIPTION,
            parameters={
                "status": {
                    "type": "string", "enum": list(_ADR_STATUS),
                    "description": "Optional ADR status filter",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum results (default 20)",
                },
            },
            required=[],
        )

    async def execute(
        self,
        status: Optional[str] = None,
        limit: int = 20,
        **kwargs,
    ) -> ToolResult:
        _Knowledge, KnowledgeCategory = _import_types()
        adrs = _list_by_category(KnowledgeCategory.ADR, status, limit)
        return ToolResult.ok({"adrs": adrs})


class ListRunbooksTool(BaseTool):
    """List operational runbooks."""

    NAME = "list_runbooks"
    DESCRIPTION = "List Runbooks."

    def __init__(self):
        super().__init__(name=self.NAME, category=ToolCategory.KNOWLEDGE)

    @property
    def tool_definition(self) -> dict:
        return create_tool_param(
            name=self.NAME,
            description=self.DESCRIPTION,
            parameters={
                "limit": {
                    "type": "integer",
                    "description": "Maximum results (default 20)",
                },
            },
            required=[],
        )

    async def execute(self, limit: int = 20, **kwargs) -> ToolResult:
        _Knowledge, KnowledgeCategory = _import_types()
        return ToolResult.ok({
            "runbooks": _list_by_category(KnowledgeCategory.RUNBOOK, None, limit),
        })


class ListPostmortemsTool(BaseTool):
    """List incident postmortems."""

    NAME = "list_postmortems"
    DESCRIPTION = "List Postmortems."

    def __init__(self):
        super().__init__(name=self.NAME, category=ToolCategory.KNOWLEDGE)

    @property
    def tool_definition(self) -> dict:
        return create_tool_param(
            name=self.NAME,
            description=self.DESCRIPTION,
            parameters={
                "limit": {
                    "type": "integer",
                    "description": "Maximum results (default 20)",
                },
            },
            required=[],
        )

    async def execute(self, limit: int = 20, **kwargs) -> ToolResult:
        _Knowledge, KnowledgeCategory = _import_types()
        return ToolResult.ok({
            "postmortems": _list_by_category(
                KnowledgeCategory.POSTMORTEM, None, limit,
            ),
        })


_STRUCTURED_KNOWLEDGE_TOOLS = [
    SubmitADRTool, SubmitRunbookTool, SubmitPostmortemTool,
    ListADRsTool, ListRunbooksTool, ListPostmortemsTool,
]


def create_structured_knowledge_tools() -> List[BaseTool]:
    """Construct the 6 structured-knowledge tools."""
    return [cls() for cls in _STRUCTURED_KNOWLEDGE_TOOLS]


__all__ = [
    "SubmitADRTool", "SubmitRunbookTool", "SubmitPostmortemTool",
    "ListADRsTool", "ListRunbooksTool", "ListPostmortemsTool",
    "create_structured_knowledge_tools",
]
