"""Shared imports/helpers for split team tool modules."""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.tool import BaseTool, ToolResult, create_tool_param, ToolCategory


class SubmitPlanTool(BaseTool):
    """Submit a plan for decision before executing complex tasks."""
    
    NAME = "submit_plan"
    DESCRIPTION = """Submit a change proposal for approval before executing complex changes.

USE THIS WHEN:
- Making major refactoring changes
- Modifying multiple files
- Changes that are hard to undo

This is an approval-routing tool, not the same thing as the local `plan(...)` workboard.
The lead agent (User Agent) will accept, reject, or request changes with feedback.

Example:
    submit_plan(
        title="Refactor authentication module",
        description="Improve security and reduce code duplication",
        steps=[
            {"action": "Extract common auth logic", "target": "src/auth/"},
            {"action": "Add JWT refresh token", "target": "src/auth/jwt.js"}
        ]
    )
"""
    
    def __init__(self):
        super().__init__(name=self.NAME, category=ToolCategory.CUSTOM)
        self._plan_decision = None
        self._agent_id = None
    
    @property
    def tool_definition(self):
        return create_tool_param(
            name=self.NAME,
            description=self.DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Brief title for the plan",
                    },
                    "description": {
                        "type": "string",
                        "description": "What the plan aims to achieve",
                    },
                    "steps": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "action": {"type": "string"},
                                "target": {"type": "string"},
                            },
                        },
                        "description": "List of planned steps",
                    },
                    "require_approval": {
                        "type": "boolean",
                        "description": "Whether to require explicit approval (default: true)",
                    },
                },
                "required": ["title", "description", "steps"],
            }
        )
    
    async def execute(
        self,
        title: str,
        description: str,
        steps: List[Dict],
        require_approval: bool = True,
        **kwargs
    ) -> ToolResult:
        if not self._plan_decision:
            return ToolResult(success=False, error_message="Plan decision protocol not configured")
        
        try:
            plan = await self._plan_decision.submit_plan(
                agent_id=self._agent_id or "",
                title=title,
                description=description,
                steps=steps,
                require_approval=require_approval,
            )
            
            # Wait for decision
            plan = await self._plan_decision.wait_for_decision(plan.id)
            
            return ToolResult(
                success=True,
                data={
                    "plan_id": plan.id,
                    "status": plan.status.value,
                    "approved": plan.status.value == "approved",
                    "feedback": plan.feedback,
                    "decision_maker": plan.decision_maker_id,
                },
            )
        except Exception as e:
            return ToolResult(success=False, error_message=str(e))
class AcceptPlanTool(BaseTool):
    """Accept a submitted plan (for lead agent)."""
    
    NAME = "accept_plan"
    DESCRIPTION = """Accept a submitted change proposal from another agent.

ONLY FOR: Lead agent (User Agent) to make approval decisions.

Example:
    accept_plan(plan_id="plan_a1b2c3d4", feedback="Good plan, proceed")
"""
    
    def __init__(self):
        super().__init__(name=self.NAME, category=ToolCategory.CUSTOM)
        self._plan_decision = None
        self._agent_id = None
    
    @property
    def tool_definition(self):
        return create_tool_param(
            name=self.NAME,
            description=self.DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "plan_id": {
                        "type": "string",
                        "description": "ID of the plan to accept",
                    },
                    "feedback": {
                        "type": "string",
                        "description": "Optional feedback",
                    },
                },
                "required": ["plan_id"],
            }
        )
    
    def execute(
        self,
        plan_id: str,
        feedback: Optional[str] = None,
        **kwargs
    ) -> ToolResult:
        if not self._plan_decision:
            return ToolResult(success=False, error_message="Plan decision protocol not configured")
        
        try:
            success = self._plan_decision.accept_plan(
                plan_id=plan_id,
                decision_maker_id=self._agent_id or "",
                feedback=feedback,
            )
            
            if success:
                return ToolResult(success=True, data={"accepted": plan_id, "feedback": feedback})
            else:
                return ToolResult(success=False, error_message=f"Failed to accept plan {plan_id}")
        except Exception as e:
            return ToolResult(success=False, error_message=str(e))
class RequestPlanChangesTool(BaseTool):
    """Reject a submitted plan or request changes."""
    
    NAME = "request_plan_changes"
    DESCRIPTION = """Reject a submitted change proposal or request revisions.

ONLY FOR: Lead agent (typically the orchestrator lane) to make plan decisions.

Example:
    request_plan_changes(
        plan_id="plan_a1b2c3d4",
        feedback="Don't modify the database schema, only update the API",
        allow_revision=True
    )
"""
    
    def __init__(self):
        super().__init__(name=self.NAME, category=ToolCategory.CUSTOM)
        self._plan_decision = None
        self._agent_id = None
    
    @property
    def tool_definition(self):
        return create_tool_param(
            name=self.NAME,
            description=self.DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "plan_id": {
                        "type": "string",
                        "description": "ID of the plan to reject or send back for changes",
                    },
                    "feedback": {
                        "type": "string",
                        "description": "Required feedback explaining the requested changes",
                    },
                    "allow_revision": {
                        "type": "boolean",
                        "description": "Allow agent to revise and resubmit (default: true)",
                    },
                },
                "required": ["plan_id", "feedback"],
            }
        )
    
    def execute(
        self,
        plan_id: str,
        feedback: str,
        allow_revision: bool = True,
        **kwargs
    ) -> ToolResult:
        if not self._plan_decision:
            return ToolResult(success=False, error_message="Plan decision protocol not configured")
        
        try:
            success = self._plan_decision.request_plan_changes(
                plan_id=plan_id,
                decision_maker_id=self._agent_id or "",
                feedback=feedback,
                request_revision=allow_revision,
            )
            
            if success:
                return ToolResult(
                    success=True,
                    data={
                        "decision_target": plan_id,
                        "feedback": feedback,
                        "revision_allowed": allow_revision,
                    },
                )
            else:
                return ToolResult(success=False, error_message=f"Failed to decide plan {plan_id}")
        except Exception as e:
            return ToolResult(success=False, error_message=str(e))
class ListPendingPlanDecisionsTool(BaseTool):
    """Get all plans pending a decision (for lead agent)."""
    
    NAME = "list_pending_plan_decisions"
    DESCRIPTION = """Get all submitted change proposals waiting for a decision.

ONLY FOR: Lead agent (User Agent) to see pending plans.

Returns list of plans with their details.

Example:
    list_pending_plan_decisions()
"""
    
    def __init__(self):
        super().__init__(name=self.NAME, category=ToolCategory.CUSTOM)
        self._plan_decision = None
    
    @property
    def tool_definition(self):
        return create_tool_param(
            name=self.NAME,
            description=self.DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {},
            }
        )
    
    def execute(self, **kwargs) -> ToolResult:
        if not self._plan_decision:
            return ToolResult(success=False, error_message="Plan decision protocol not configured")
        
        try:
            plans = self._plan_decision.get_pending_plan_decisions()
            
            return ToolResult(
                success=True,
                data={
                    "count": len(plans),
                    "plans": [p.to_dict() for p in plans],
                },
            )
        except Exception as e:
            return ToolResult(success=False, error_message=str(e))


# ============================================================
# 4. PERSONA MANAGEMENT TOOLS
# ============================================================
