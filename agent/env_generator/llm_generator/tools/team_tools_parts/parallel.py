"""Shared imports/helpers for split team tool modules."""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.tool import BaseTool, ToolResult, create_tool_param, ToolCategory


class ParallelExecuteTool(BaseTool):
    """Execute multiple subtasks in parallel using profile-resolved agents."""
    
    NAME = "parallel_execute"
    DESCRIPTION = """Execute multiple independent subtasks in parallel with profile-resolved agent teams (one-shot convenience).

You can define team composition and per-agent metadata.

Each agent can have:
- name: A descriptive name for this agent
- role: What this agent specializes in
- agent_type: Optional runtime worker label; if omitted, the runtime must infer a valid profile from the definition
- config_profile: Explicit backing execution profile (backend/frontend/database/verifier/review_worker/analysis_worker/worker/...).
  If omitted, the tool defaults to the parent agent's profile when possible.
- skills: Optional final skill allowlist for that worker
- inherit_parent_skills: Optional bool controlling whether parent skills are merged in
- capabilities: What tools/abilities this agent should have
- task: The specific task to complete
- context: Additional context and constraints

The tool spawns agents using runtime labels plus explicit execution profiles, runs them in parallel, and aggregates results.

For long-running teams that need explicit lifecycle (launch/monitor/pause/resume/terminate),
use the managed team tools instead of this one-shot parallel worker shortcut.

Example - Frontend creating pages with specialized agents:
    parallel_execute(
        team_name="PageBuilders",
        agents=[
            {
                "name": "HomePage Builder",
                "role": "Landing page specialist",
                "capabilities": ["file_write", "component_design"],
                "task": "Create HomePage with hero section, featured products grid, and newsletter signup",
                "context": {"route": "/", "style": "modern, clean"}
            },
            {
                "name": "Product Page Builder", 
                "role": "E-commerce page specialist",
                "capabilities": ["file_write", "api_integration"],
                "task": "Create ProductPage with image gallery, details, reviews, and add-to-cart",
                "context": {"route": "/product/:id", "api": "/api/products/:id"}
            },
            {
                "name": "Cart Page Builder",
                "role": "Checkout flow specialist", 
                "capabilities": ["file_write", "state_management"],
                "task": "Create CartPage with item list, quantity controls, and checkout button",
                "context": {"route": "/cart", "state": "useCart hook"}
            }
        ]
    )

Example - Backend with specialized API developers:
    parallel_execute(
        team_name="APITeam",
        agents=[
            {
                "name": "Auth API Developer",
                "role": "Security specialist",
                "capabilities": ["file_write", "security"],
                "task": "Create /api/auth/* endpoints with JWT, refresh tokens, password reset",
                "context": {"security": "bcrypt, JWT", "models": ["User", "Session"]}
            },
            {
                "name": "Product API Developer",
                "role": "CRUD specialist",
                "capabilities": ["file_write", "database"],
                "task": "Create /api/products/* endpoints with filtering, pagination, search",
                "context": {"models": ["Product", "Category"], "features": ["pagination", "search"]}
            }
        ],
        coordination="Each agent works independently but shares the same database models"
    )

Example - Investigation team with diverse perspectives:
    parallel_execute(
        team_name="BugHunters",
        agents=[
            {
                "name": "Database Inspector",
                "role": "DB expert",
                "task": "Check if the bug is related to database queries or connections",
                "context": {"error": "500 on /api/orders"}
            },
            {
                "name": "API Analyzer",
                "role": "API expert", 
                "task": "Check if the bug is in the API endpoint logic or validation",
                "context": {"error": "500 on /api/orders"}
            },
            {
                "name": "Frontend Debugger",
                "role": "Frontend expert",
                "task": "Check if the bug is caused by incorrect frontend API calls",
                "context": {"error": "500 on /api/orders"}
            }
        ],
        coordination="Share findings via message. First to find root cause should notify others."
    )
"""
    
    def __init__(self):
        super().__init__(name=self.NAME, category=ToolCategory.CUSTOM)
        self._agent_manager = None
        self._agent_id = None
    
    @property
    def tool_definition(self):
        return create_tool_param(
            name=self.NAME,
            description=self.DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "team_name": {
                        "type": "string",
                        "description": "Name for this agent team (e.g., 'PageBuilders', 'APITeam')",
                    },
                    "agents": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {
                                    "type": "string",
                                    "description": "Descriptive name for this agent",
                                },
                                "role": {
                                    "type": "string",
                                    "description": "What this agent specializes in",
                                },
                                "agent_type": {
                                    "type": "string",
                                    "description": "Optional free-form runtime worker label (e.g., security_auditor, api_debugger, frontend_builder)",
                                },
                                "config_profile": {
                                    "type": "string",
                                    "description": "Optional backing execution profile (e.g., backend, frontend, database, verifier, review_worker, analysis_worker, worker)",
                                },
                                "skills": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "Optional explicit skill allowlist for this worker",
                                },
                                "inherit_parent_skills": {
                                    "type": "boolean",
                                    "description": "Whether to merge in parent skills for this worker (default: true)",
                                },
                                "capabilities": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "Tools/abilities: file_write, file_read, api_call, database, security, testing, etc.",
                                },
                                "task": {
                                    "type": "string",
                                    "description": "The specific task for this agent to complete",
                                },
                                "context": {
                                    "type": "object",
                                    "description": "Additional context, constraints, or information",
                                },
                            },
                            "required": ["name", "task"],
                        },
                        "description": "List of agents to create for this team",
                    },
                    "coordination": {
                        "type": "string",
                        "description": "How agents should coordinate (share info, dependencies, communication)",
                    },
                    "max_concurrent": {
                        "type": "integer",
                        "description": "Maximum concurrent agents (default: 5)",
                        "default": 5,
                    },
                    "timeout": {
                        "type": "number",
                        "description": "Timeout per agent in seconds (default: 300)",
                        "default": 300,
                    },
                },
                "required": ["agents"],
            }
        )
    
    async def execute(
        self,
        agents: List[Dict],
        team_name: str = "DynamicTeam",
        coordination: str = "",
        max_concurrent: int = 5,
        timeout: float = 300.0,
        **kwargs
    ) -> ToolResult:
        if not self._agent_manager:
            return ToolResult(success=False, error_message="Agent manager not configured")
        
        if not agents:
            return ToolResult(success=False, error_message="No agents defined")
        
        if len(agents) > 10:
            return ToolResult(
                success=False, 
                error_message=f"Too many agents ({len(agents)}). Maximum is 10."
            )
        
        try:
            # Convert to subtasks format with per-agent metadata
            subtasks = []
            parent_default_profile = self._infer_parent_default_profile()
            for agent_def in agents:
                agent_config_profile = agent_def.get("config_profile", "")
                if not agent_config_profile and parent_default_profile:
                    agent_config_profile = parent_default_profile
                subtask = {
                    "task": agent_def.get("task", ""),
                    "context": agent_def.get("context", {}),
                    # Pass agent metadata for profile-based resolution
                    "agent_definition": {
                        "name": agent_def.get("name", "Worker"),
                        "role": agent_def.get("role", ""),
                        # #348: OPTIONAL per this tool's own docs ("if omitted,
                        # the runtime must infer") and all three worked examples
                        # omit it. Injecting "" sailed past the validator's
                        # missing/None short-circuit and hit its non-empty check,
                        # so following the documentation was a guaranteed
                        # E_CHILD_TASK_CONTRACT rejection. Absent stays absent.
                        "agent_type": agent_def.get("agent_type") or None,
                        "config_profile": agent_config_profile,
                        "skills": agent_def.get("skills", []),
                        "inherit_parent_skills": agent_def.get("inherit_parent_skills", True),
                        "capabilities": agent_def.get("capabilities", []),
                    },
                }
                # Add coordination info to context
                if coordination:
                    subtask["context"]["_coordination"] = coordination
                    subtask["context"]["_team_name"] = team_name
                
                subtasks.append(subtask)
            
            result = await self._agent_manager.parallel_execute_profiled(
                subtasks=subtasks,
                parent_id=self._agent_id or "",
                team_name=team_name,
                max_concurrent=min(max_concurrent, 8),
                timeout=min(timeout, 600.0),
            )
            
            success = bool(result["success"])
            payload = {
                "team_name": team_name,
                "total_agents": len(agents),
                "succeeded": len(agents) - len(result["failed"]),
                "failed": len(result["failed"]),
                "duration_seconds": result["duration"],
                "effective_max_concurrent": result.get("effective_max_concurrent"),
                "failure_rate_recent": result.get("failure_rate_recent"),
                "spawn_budget_remaining": result.get("spawn_budget_remaining"),
                "deduped_count": result.get("deduped_count"),
                "contract_rejected_count": result.get("contract_rejected_count"),
                "recommended_actions_summary": result.get("recommended_actions_summary"),
                "recommended_action": result.get("recommended_action"),
                "error_code": result.get("error_code"),
                "error_message": result.get("error_message") or result.get("error"),
                "error": result.get("error"),
                "results": result["results"],
                "failed_indices": result["failed"],
            }
            return ToolResult(
                success=success,
                data=payload,
                error_message=None if success else self._summarize_parallel_failure(payload),
            )
        except Exception as e:
            return ToolResult(success=False, error_message=str(e))

    @staticmethod
    def _summarize_parallel_failure(payload: Dict) -> str:
        team_name = payload.get("team_name") or "parallel team"
        total = payload.get("total_agents")
        succeeded = payload.get("succeeded")
        failed = payload.get("failed")
        parts = [f"{team_name} completed with {succeeded}/{total} succeeded ({failed} failed)."]
        if payload.get("error_message") or payload.get("error"):
            parts.append(str(payload.get("error_message") or payload.get("error")))

        failed_items = []
        for item in payload.get("results") or []:
            if not isinstance(item, dict) or item.get("success", True):
                continue
            name = item.get("agent_name") or item.get("agent_id") or "worker"
            code = item.get("error_code") or "E_AGENT_FAILED"
            message = item.get("error_message") or item.get("error") or item.get("status") or "failed"
            failed_items.append(f"{name}: {code} - {message}")
        if failed_items:
            parts.append("; ".join(failed_items[:4]))
        return " ".join(parts)

    def _infer_parent_default_profile(self) -> str:
        parent = str(self._agent_id or "").lower()
        for profile in ("orchestrator", "design", "database", "backend", "frontend", "verifier", "knowledge"):
            if profile in parent:
                return profile
        return ""
