"""
Step Reminder Tools - Let agents manage pinned reminders across steps.

These tools let an agent keep lightweight step-scoped guidance that is injected
at the beginning of each future step.
"""

from typing import Any, Dict, List, Optional

from ._base import BaseTool, ToolCategory, ToolResult, create_tool_param


class SetStepReminderTool(BaseTool):
    """Create or update a pinned reminder shown at the start of each step."""

    NAME = "set_step_reminder"

    DESCRIPTION = """Create or update a pinned reminder that will be injected at the start of every future step.

Use this when you want to persist short-term self-guidance across multiple steps, such as:
- current focus
- next milestone
- constraints to not forget
- a checklist for the next several moves

Examples:
    set_step_reminder(title="Current focus", content="Finish backend auth flow before tests")
    set_step_reminder(title="Checklist", content=["update schema", "run lint", "notify verifier"])
    set_step_reminder(title="Constraints", content={"owner": "backend", "avoid": "broad refactor"})

If a reminder with the same title already exists, it will be replaced.

Optional controls:
- ttl_steps: Show this reminder for only the next N steps, then remove it
- auto_clear_on_finish: Clear this reminder automatically when finish() or deliver_project() succeeds
"""

    def __init__(self, agent=None):
        super().__init__(name=self.NAME, category=ToolCategory.AGENT)
        self.agent = agent

    def set_agent(self, agent):
        self.agent = agent

    @property
    def tool_definition(self):
        return self.get_tool_param()

    def get_tool_param(self):
        return create_tool_param(
            name=self.NAME,
            description=self.DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Stable reminder title, e.g. 'Current focus' or 'Checklist'",
                    },
                    "content": {
                        "description": "Reminder payload. Can be a string, array, or object.",
                        "anyOf": [
                            {"type": "string"},
                            {"type": "array"},
                            {"type": "object"},
                        ],
                    },
                    "ttl_steps": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "Optional number of future steps to keep showing this reminder.",
                    },
                    "auto_clear_on_finish": {
                        "type": "boolean",
                        "description": "If true, clear this reminder automatically when finish() or deliver_project() succeeds.",
                    },
                },
                "required": ["title", "content"],
            },
        )

    def execute(
        self,
        title: str,
        content: Any,
        ttl_steps: Optional[int] = None,
        auto_clear_on_finish: bool = False,
    ) -> ToolResult:
        if not self.agent or not hasattr(self.agent, "upsert_step_reminder"):
            return ToolResult(success=False, error_message="Step reminder runtime not available")
        try:
            self.agent.upsert_step_reminder(
                title=title,
                content=content,
                ttl_steps=ttl_steps,
                auto_clear_on_finish=auto_clear_on_finish,
            )
            reminders = list(getattr(self.agent, "_step_reminders", []) or [])
            return ToolResult(
                success=True,
                data={
                    "updated": True,
                    "title": str(title).strip(),
                    "count": len(reminders),
                    "ttl_steps": ttl_steps,
                    "auto_clear_on_finish": bool(auto_clear_on_finish),
                    "info": f"Step reminder '{str(title).strip()}' saved",
                },
            )
        except Exception as e:
            return ToolResult(success=False, error_message=f"Failed to set step reminder: {e}")


class ListStepRemindersTool(BaseTool):
    """Inspect current pinned step reminders."""

    NAME = "list_step_reminders"

    DESCRIPTION = """List the pinned reminders that will be injected at the start of future steps.

Use this when you want to inspect what guidance you already pinned for yourself.
"""

    def __init__(self, agent=None):
        super().__init__(name=self.NAME, category=ToolCategory.AGENT)
        self.agent = agent

    def set_agent(self, agent):
        self.agent = agent

    @property
    def tool_definition(self):
        return self.get_tool_param()

    def get_tool_param(self):
        return create_tool_param(
            name=self.NAME,
            description=self.DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {},
            },
            required=[],
        )

    def execute(self) -> ToolResult:
        if not self.agent:
            return ToolResult(success=False, error_message="Step reminder runtime not available")
        reminders = list(getattr(self.agent, "_step_reminders", []) or [])
        summary: List[Dict[str, Any]] = []
        ttl_bound_count = 0
        auto_clear_count = 0
        for idx, item in enumerate(reminders, start=1):
            if isinstance(item, dict):
                ttl_steps = item.get("ttl_steps")
                auto_clear = bool(item.get("auto_clear_on_finish", False))
                if ttl_steps is not None:
                    ttl_bound_count += 1
                if auto_clear:
                    auto_clear_count += 1
                summary.append(
                    {
                        "index": idx,
                        "title": str(item.get("title") or item.get("name") or f"Reminder {idx}").strip(),
                        "content": item.get("content", item.get("value", item.get("items"))),
                        "ttl_steps_remaining": ttl_steps,
                        "auto_clear_on_finish": auto_clear,
                        "kind": "structured",
                    }
                )
                continue
            summary.append(
                {
                    "index": idx,
                    "title": f"Reminder {idx}",
                    "content": item,
                    "ttl_steps_remaining": None,
                    "auto_clear_on_finish": False,
                    "kind": "plain",
                }
            )
        return ToolResult(
            success=True,
            data={
                "count": len(reminders),
                "reminders": reminders,
                "summary": summary,
                "ttl_bound_count": ttl_bound_count,
                "auto_clear_on_finish_count": auto_clear_count,
            },
        )


class ClearStepRemindersTool(BaseTool):
    """Clear one or all pinned step reminders."""

    NAME = "clear_step_reminders"

    DESCRIPTION = """Clear pinned step reminders.

Args:
    title: Optional reminder title. If provided, clear only that reminder.
           If omitted, clear all step reminders.
"""

    def __init__(self, agent=None):
        super().__init__(name=self.NAME, category=ToolCategory.AGENT)
        self.agent = agent

    def set_agent(self, agent):
        self.agent = agent

    @property
    def tool_definition(self):
        return self.get_tool_param()

    def get_tool_param(self):
        return create_tool_param(
            name=self.NAME,
            description=self.DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Optional reminder title to clear. Omit to clear all reminders.",
                    }
                },
            },
            required=[],
        )

    def execute(self, title: Optional[str] = None) -> ToolResult:
        if not self.agent:
            return ToolResult(success=False, error_message="Step reminder runtime not available")

        try:
            if title:
                target = str(title).strip()
                current = list(getattr(self.agent, "_step_reminders", []) or [])
                filtered = [
                    item for item in current
                    if not (
                        (isinstance(item, dict) and str(item.get("title", "")).strip() == target)
                        or (isinstance(item, str) and item.strip() == target)
                    )
                ]
                self.agent.set_step_reminders(filtered)
                return ToolResult(
                    success=True,
                    data={
                        "cleared": True,
                        "title": target,
                        "count": len(filtered),
                        "info": f"Cleared step reminder '{target}'",
                    },
                )

            self.agent.clear_step_reminders()
            return ToolResult(
                success=True,
                data={
                    "cleared": True,
                    "count": 0,
                    "info": "Cleared all step reminders",
                },
            )
        except Exception as e:
            return ToolResult(success=False, error_message=f"Failed to clear step reminders: {e}")


def create_step_reminder_tools(agent=None) -> List[BaseTool]:
    """Factory for step reminder management tools."""
    return [
        SetStepReminderTool(agent=agent),
        ListStepRemindersTool(agent=agent),
        ClearStepRemindersTool(agent=agent),
    ]
