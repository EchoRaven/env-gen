"""
Progress Reporting Tools - Tools for reporting progress to the coordinating lane

Provides:
- ReportProgressTool: Report current work status
- ReportCompletionTool: Report task completion
- ReportIssueTool: Report issues or blockers

These tools enable agents to communicate their progress to the coordinating lane
(typically the resident orchestrator), which handles progress tracking.
"""

from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from ._base import (
    BaseTool,
    ToolResult,
    ToolCategory,
    create_tool_param,
    Workspace,
)


# ============================================================================
# Report Progress Tool
# ============================================================================

class ReportProgressTool(BaseTool):
    """
    Report current work progress to the coordinating lane.
    
    Use this to keep the coordinating lane informed about what you're working on.
    """
    
    NAME = "report_progress"
    
    DESCRIPTION = """Report your current work progress to the coordinating lane.

Use this to communicate:
- What you're currently working on
- Significant milestones reached
- Status updates during long tasks

The coordinating lane consolidates reports from all agents to track overall project progress.

Examples:
    report_progress(status="Starting database schema design")
    report_progress(status="Completed user authentication API", phase="backend")
    report_progress(status="Creating React components", details={"components": ["Header", "Footer"]})
"""
    
    # Instance registry to avoid shared class state
    _instances: Dict[str, "ReportProgressTool"] = {}
    
    def __init__(self, agent_id: str = "unknown"):
        super().__init__(name=self.NAME, category=ToolCategory.AGENT)
        # Instance-level storage (NOT class-level)
        self._agent_id = agent_id
        self._agent_name = "Unknown Agent"
        self._progress_callback: Optional[Callable] = None
        self._memory_bank = None
        # Register instance
        ReportProgressTool._instances[agent_id] = self
    
    @classmethod
    def configure(cls, agent_id: str, agent_name: str, callback: Callable = None, memory_bank=None):
        """Configure an instance for specific agent."""
        instance = cls._instances.get(agent_id)
        if instance:
            instance._agent_id = agent_id
            instance._agent_name = agent_name
            instance._progress_callback = callback
            instance._memory_bank = memory_bank
    
    @classmethod
    def get_instance(cls, agent_id: str) -> Optional["ReportProgressTool"]:
        """Get instance for a specific agent."""
        return cls._instances.get(agent_id)
    
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
                    "status": {
                        "type": "string",
                        "description": "Brief status message (e.g., 'Completed database schema')"
                    },
                    "phase": {
                        "type": "string",
                        "enum": ["requirements", "design", "database", "backend", "frontend", "docker", "testing"],
                        "description": "Current project phase (optional)"
                    },
                    "details": {
                        "type": "object",
                        "description": "Additional details (files_created, components, etc.)"
                    }
                },
                "required": ["status"]
            }
        )
    
    def execute(self, status: str, phase: str = None, details: Dict[str, Any] = None) -> ToolResult:
        report = {
            "type": "progress_report",
            "agent_id": self._agent_id,
            "agent_name": self._agent_name,
            "status": status,
            "phase": phase,
            "details": details or {},
            "timestamp": datetime.now().isoformat(),
        }
        
        # Update own MemoryBank if available
        if self._memory_bank:
            try:
                self._memory_bank.update_active_context(
                    focus=f"Working on: {status}",
                    recent_change=status,
                )
            except Exception:
                pass  # Memory update is best-effort
        
        # Send to coordinating lane via callback
        if self._progress_callback:
            try:
                self._progress_callback(report)
                return ToolResult(
                    success=True,
                    data={
                        "reported": True,
                        "status": status,
                        "phase": phase,
                        "info": f"Progress reported to coordinating lane: {status}"
                    }
                )
            except Exception as e:
                return ToolResult(
                    success=False,
                    error_message=f"Failed to report progress: {e}"
                )
        
        # No callback - log locally only
        return ToolResult(
            success=True,
            data={
                "reported": False,
                "status": status,
                "phase": phase,
                "info": f"Progress logged locally (coordinating lane not connected): {status}"
            }
        )


# ============================================================================
# Report Completion Tool
# ============================================================================

class ReportCompletionTool(BaseTool):
    """
    Report task completion to the coordinating lane.
    
    Use this when you've completed a significant task or milestone.
    """
    
    NAME = "report_completion"
    
    DESCRIPTION = """Report task completion to the coordinating lane.

Use this when you've completed:
- A significant task or milestone
- A file or component
- A phase of work

Examples:
    report_completion(task="Database schema design")
    report_completion(task="User API endpoints", files_created=["api/users.js", "api/auth.js"])
    report_completion(task="React Dashboard component", phase="frontend")
"""
    
    # Instance registry to avoid shared class state
    _instances: Dict[str, "ReportCompletionTool"] = {}
    
    def __init__(self, agent_id: str = "unknown"):
        super().__init__(name=self.NAME, category=ToolCategory.AGENT)
        # Instance-level storage (NOT class-level)
        self._agent_id = agent_id
        self._agent_name = "Unknown Agent"
        self._completion_callback: Optional[Callable] = None
        self._memory_bank = None
        # Register instance
        ReportCompletionTool._instances[agent_id] = self
    
    @classmethod
    def configure(cls, agent_id: str, agent_name: str, callback: Callable = None, memory_bank=None):
        """Configure an instance for specific agent."""
        instance = cls._instances.get(agent_id)
        if instance:
            instance._agent_id = agent_id
            instance._agent_name = agent_name
            instance._completion_callback = callback
            instance._memory_bank = memory_bank
    
    @classmethod
    def get_instance(cls, agent_id: str) -> Optional["ReportCompletionTool"]:
        """Get instance for a specific agent."""
        return cls._instances.get(agent_id)
    
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
                    "task": {
                        "type": "string",
                        "description": "Name of the completed task"
                    },
                    "files_created": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of files created (optional)"
                    },
                    "phase": {
                        "type": "string",
                        "enum": ["requirements", "design", "database", "backend", "frontend", "docker", "testing"],
                        "description": "Project phase that was completed (optional)"
                    },
                    "summary": {
                        "type": "string",
                        "description": "Brief summary of what was done (optional)"
                    }
                },
                "required": ["task"]
            }
        )
    
    def execute(
        self,
        task: str,
        files_created: List[str] = None,
        phase: str = None,
        summary: str = None,
        **kwargs,
    ) -> ToolResult:
        # Backward/typo compatibility for LLM-generated keys like "files_created?"
        if files_created is None:
            legacy_files = kwargs.get("files_created?")
            if isinstance(legacy_files, list):
                files_created = legacy_files

        report = {
            "type": "completion_report",
            "agent_id": self._agent_id,
            "agent_name": self._agent_name,
            "task": task,
            "files_created": files_created or [],
            "phase": phase,
            "summary": summary,
            "timestamp": datetime.now().isoformat(),
        }
        
        # Update own MemoryBank if available
        if self._memory_bank:
            try:
                self._memory_bank.append_to_progress(task, category="completed")
            except Exception:
                pass  # Memory update is best-effort
        
        # Send to coordinating lane via callback
        if self._completion_callback:
            try:
                self._completion_callback(report)
                return ToolResult(
                    success=True,
                    data={
                        "reported": True,
                        "task": task,
                        "phase": phase,
                        "files_created": files_created or [],
                        "info": f"Completion reported to coordinating lane: {task}"
                    }
                )
            except Exception as e:
                return ToolResult(
                    success=False,
                    error_message=f"Failed to report completion: {e}"
                )
        
        # No callback - log locally only
        return ToolResult(
            success=True,
            data={
                "reported": False,
                "task": task,
                "phase": phase,
                "info": f"Completion logged locally (coordinating lane not connected): {task}"
            }
        )


# ============================================================================
# Report Issue Tool
# ============================================================================

class ReportIssueTool(BaseTool):
    """
    Report issues or blockers to the coordinating lane.
    
    Use this when you encounter problems that need attention.
    """
    
    NAME = "report_issue"
    
    DESCRIPTION = """Report an issue or blocker to the coordinating lane.

Use this when you encounter:
- Errors or bugs
- Missing dependencies
- Unclear requirements
- Blockers that need resolution

The coordinating lane tracks all issues across agents for project monitoring.

**IMPORTANT**: 
1. Use `assign_to` to specify which agent should fix the issue:
   - "frontend": UI, React, JSX, CSS, Vite, npm build errors in frontend
   - "backend": API, Express, routes, middleware, server code
   - "database": SQL, schema, seed data, PostgreSQL
   - "design": Spec files, API/database design documents

2. **Issue Queuing**: Issues are queued and sent ONE AT A TIME to avoid overwhelming
   the target agent. If you have multiple issues for the same agent, they will be
   batched into a single message.

3. **Deduplication**: Similar issues to the same agent within 60s are deduplicated.
   The tool will return "skipped" if the issue is a duplicate.

Examples:
    report_issue(issue="Missing page components in frontend", assign_to="frontend")
    report_issue(issue="API endpoint returns 500 error", assign_to="backend", severity="error")
    report_issue(issue="Database seed has duplicate emails", assign_to="database", severity="critical")
"""
    
    # Instance registry to avoid shared class state
    _instances: Dict[str, "ReportIssueTool"] = {}
    
    # Deduplication: track recently sent issues per agent (class-level for simplicity)
    _recent_issues: Dict[str, List[tuple]] = {}  # agent_id -> [(timestamp, issue_hash), ...]
    _DEDUP_WINDOW_SECONDS = 60  # Deduplicate similar issues within 60 seconds
    
    def __init__(self, agent_id: str = "unknown"):
        super().__init__(name=self.NAME, category=ToolCategory.AGENT)
        # Instance-level storage (NOT class-level)
        self._agent_id = agent_id
        self._agent_name = "Unknown Agent"
        self._issue_callback: Optional[Callable] = None
        self._memory_bank = None
        self._agent = None  # Agent reference for MessageBus access
        # Register instance
        ReportIssueTool._instances[agent_id] = self
    
    def set_agent(self, agent):
        """Set the agent that will use this tool (for MessageBus access)."""
        self._agent = agent
    
    @classmethod
    def configure(cls, agent_id: str, agent_name: str, callback: Callable = None, memory_bank=None, agent=None):
        """Configure an instance for specific agent."""
        instance = cls._instances.get(agent_id)
        if instance:
            instance._agent_id = agent_id
            instance._agent_name = agent_name
            instance._issue_callback = callback
            instance._memory_bank = memory_bank
            if agent:
                instance._agent = agent
    
    @classmethod
    def get_instance(cls, agent_id: str) -> Optional["ReportIssueTool"]:
        """Get instance for a specific agent."""
        return cls._instances.get(agent_id)
    
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
                    "issue": {
                        "type": "string",
                        "description": "Description of the issue"
                    },
                    "assign_to": {
                        "type": "string",
                        "enum": ["frontend", "backend", "database", "design"],
                        "description": "Which agent should fix this issue (REQUIRED). frontend=UI/React, backend=API/Express, database=SQL/seed, design=specs"
                    },
                    "severity": {
                        "type": "string",
                        "enum": ["info", "warning", "error", "critical"],
                        "description": "Issue severity (default: warning)"
                    },
                    "phase": {
                        "type": "string",
                        "enum": ["requirements", "design", "database", "backend", "frontend", "docker", "testing"],
                        "description": "Project phase where issue occurred (optional)"
                    },
                    "context": {
                        "type": "string",
                        "description": "Additional context (error message, stack trace, etc.)"
                    }
                },
                "required": ["issue", "assign_to"]
            }
        )
    
    def _compute_issue_hash(self, issue: str, assign_to: str) -> str:
        """Compute a hash for deduplication based on key words in the issue."""
        import hashlib
        # Normalize: lowercase, remove extra whitespace, take first 200 chars
        normalized = ' '.join(issue.lower().split())[:200]
        key = f"{assign_to}:{normalized}"
        return hashlib.md5(key.encode()).hexdigest()[:16]
    
    def _is_duplicate(self, issue: str, assign_to: str) -> bool:
        """Check if this issue is a duplicate of a recently sent one."""
        now = datetime.now()
        issue_hash = self._compute_issue_hash(issue, assign_to)
        
        # Clean up old entries
        if assign_to in self._recent_issues:
            self._recent_issues[assign_to] = [
                (ts, h) for ts, h in self._recent_issues[assign_to]
                if (now - ts).total_seconds() < self._DEDUP_WINDOW_SECONDS
            ]
        else:
            self._recent_issues[assign_to] = []
        
        # Check for duplicate
        for ts, h in self._recent_issues[assign_to]:
            if h == issue_hash:
                return True
        
        # Record this issue
        self._recent_issues[assign_to].append((now, issue_hash))
        return False
    
    def execute(self, issue: str, assign_to: str = "backend", severity: str = "warning", phase: str = None, context: str = None) -> ToolResult:
        # Deduplication check
        if self._is_duplicate(issue, assign_to):
            return ToolResult(
                success=True,
                data={
                    "reported": False,
                    "dispatched": False,
                    "skipped": True,
                    "issue": issue,
                    "assign_to": assign_to,
                    "severity": severity,
                    "info": f"Issue skipped (duplicate within {self._DEDUP_WINDOW_SECONDS}s): {issue[:60]}..."
                }
            )
        
        report = {
            "type": "issue_report",
            "agent_id": self._agent_id,
            "agent_name": self._agent_name,
            "issue": issue,
            "assign_to": assign_to,  # Explicit assignment to responsible agent
            "severity": severity,
            "phase": phase,
            "context": context,
            "timestamp": datetime.now().isoformat(),
        }
        
        # Update own MemoryBank if available
        if self._memory_bank:
            try:
                self._memory_bank.append_to_progress(f"{severity}: {issue}", category="issues")
            except Exception:
                pass  # Memory update is best-effort
        
        # Send to coordinating lane via callback (for tracking)
        if self._issue_callback:
            try:
                self._issue_callback(report)
            except Exception:
                pass  # Callback is best-effort
        
        # ALSO send message to the assigned agent to trigger fix!
        # Use _pending_notifications pattern since execute() runs in a thread
        dispatched = False
        if hasattr(self, '_agent') and self._agent:
            try:
                from uuid import uuid4
                from utils.message import BaseMessage, MessageHeader, MessageType, MessagePriority
                
                bus = getattr(self._agent, '_external_bus', None)
                if bus:
                    # Build issue content with context
                    issue_content = issue
                    if context:
                        issue_content += f"\n\nContext: {context}"
                    
                    # Queue notification for async processing by agent
                    pending = getattr(self._agent, "_pending_notifications", None)
                    if pending is None:
                        self._agent._pending_notifications = []
                        pending = self._agent._pending_notifications
                    
                    header = MessageHeader(
                        message_id=str(uuid4()),
                        source_agent_id=self._agent_id,
                        target_agent_id=assign_to,
                        priority=MessagePriority.HIGH,
                    )
                    msg = BaseMessage(
                        header=header,
                        message_type=MessageType.STATUS,
                        payload=issue_content,
                        metadata={
                            "msg_type": "issue",
                        "severity": severity,
                        "phase": phase,
                            "context": {"original_report": report},
                            "tags": ["issue", severity],
                            "persist": True,  # Issues should persist
                            "read": False,
                        },
                    )
                    # Store for async delivery (thread-safe)
                    pending.append((bus, msg))
                    dispatched = True
            except Exception as e:
                # Dispatch is best-effort
                pass
        
        return ToolResult(
            success=True,
            data={
                "reported": True,
                "dispatched": dispatched,
                "issue": issue,
                "assign_to": assign_to,
                "severity": severity,
                "phase": phase,
                "info": f"Issue [{severity}] reported and {'dispatched to ' + assign_to if dispatched else 'logged'}: {issue[:100]}"
            }
        )


# ============================================================================
# Get Progress Tool
# ============================================================================

class GetProgressTool(BaseTool):
    """
    Get project progress from the coordinating lane.
    
    Use this to understand overall project status and what other agents have done.
    """
    
    NAME = "get_progress"
    
    DESCRIPTION = """Get current project progress from the coordinating lane.

Use this to:
- Understand what has been completed
- Check what other agents are working on
- See open issues or blockers
- Get project timeline

Examples:
    get_progress()                              # Get overall project status
    get_progress(scope="all")                   # Full status with agent details
    get_progress(scope="agent", agent_id="backend")  # Check specific agent
    get_progress(scope="issues")                # List open issues
    get_progress(scope="timeline", limit=10)    # Recent activity
"""
    
    # Instance registry to avoid shared class state
    _instances: Dict[str, "GetProgressTool"] = {}
    
    def __init__(self, agent_id: str = "unknown"):
        super().__init__(name=self.NAME, category=ToolCategory.AGENT)
        # Instance-level storage (NOT class-level)
        self._agent_id = agent_id
        self._query_callback: Optional[Callable] = None
        # Register instance
        GetProgressTool._instances[agent_id] = self
    
    @classmethod
    def configure(cls, agent_id: str, callback: Callable = None):
        """Configure an instance for specific agent."""
        instance = cls._instances.get(agent_id)
        if instance:
            instance._agent_id = agent_id
            instance._query_callback = callback
    
    @classmethod
    def get_instance(cls, agent_id: str) -> Optional["GetProgressTool"]:
        """Get instance for a specific agent."""
        return cls._instances.get(agent_id)
    
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
                    "scope": {
                        "type": "string",
                        "enum": ["summary", "all", "agent", "issues", "timeline", "phases"],
                        "description": "What to query: summary (default), all (full status), agent (specific agent), issues, timeline, phases"
                    },
                    "agent_id": {
                        "type": "string",
                        "description": "Agent ID to query (required if scope='agent')"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Limit for timeline entries (default: 20)"
                    }
                },
                "required": []
            }
        )
    
    def execute(self, scope: str = "summary", agent_id: str = None, limit: int = 20) -> ToolResult:
        query = {
            "type": "progress_query",
            "from_agent": self._agent_id,
            "scope": scope,
            "agent_id": agent_id,
            "limit": limit,
        }
        
        # Query coordinating lane via callback
        if self._query_callback:
            try:
                result = self._query_callback(query)
                return ToolResult(
                    success=True,
                    data={
                        "scope": scope,
                        "progress": result,
                        "info": f"Project progress ({scope})"
                    }
                )
            except Exception as e:
                return ToolResult(
                    success=False,
                    error_message=f"Failed to get progress: {e}"
                )
        
        # No callback configured - provide helpful guidance
        # In the current architecture, agents communicate via messages
        return ToolResult(
            success=True,
            data={
                "scope": scope,
                "progress": {
                    "note": "Direct progress query not available. Use alternative methods:",
                    "alternatives": [
                        "check_inbox() - See messages from other agents including status updates",
                        "ask_agent(agent_id='orchestrator', question='What is the current project status?') - Ask the coordinating lane directly",
                        "recall(query='project progress') - Search your memory for progress updates"
                    ]
                },
                "info": f"Progress query ({scope}) - use check_inbox or ask_agent instead"
            }
        )


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "ReportProgressTool",
    "ReportCompletionTool",
    "ReportIssueTool",
    "GetProgressTool",
]

