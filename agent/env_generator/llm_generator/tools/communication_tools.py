"""
Communication Tools - Enable agents to communicate via MessageBus

These tools DIRECTLY use MessageBus, not through agent wrapper methods.
Agent only provides:
- agent_id (for source identification)
- message_bus reference
- inbox for receiving messages

Tools:
- send_message: Send message to another agent
- ask_agent: Ask another agent a question and wait for response
- broadcast: Broadcast message to all agents
- check_inbox: Check received messages
- subscribe_messages: Subscribe to message types
- unsubscribe_messages: Unsubscribe from messages
- publish_message: Publish to subscribers (pub/sub)
- list_agents: List available agents
"""

from typing import Any, Dict, List, Optional, TYPE_CHECKING
from datetime import datetime
from uuid import uuid4
import asyncio

from ._base import (
    BaseTool,
    ToolResult,
    ToolCategory,
    create_tool_param,
)

# Import MessageBus types directly
from utils.communication import MessageBus
from utils.message import (
    BaseMessage,
    MessageHeader,
    MessageType,
    MessagePriority,
)
from agent_metadata import (
    RESIDENT_LANE_IDS,
    ROLE_DESCRIPTIONS,
)

if TYPE_CHECKING:
    from multi_agent.agents.base import EnvGenAgent


def _get_message_bus(agent: "EnvGenAgent") -> Optional[MessageBus]:
    """Get MessageBus from agent."""
    return getattr(agent, "_message_bus", None)


def _discover_agent_ids(agent: Optional["EnvGenAgent"], include_self: bool = False) -> List[str]:
    """
    Discover valid agent IDs dynamically for tool schemas.

    Includes:
    - Core static agents
    - Runtime MessageBus-registered agents
    - Dynamic spawned agents from team manager
    """
    discovered = set(RESIDENT_LANE_IDS)

    if agent is not None:
        bus = _get_message_bus(agent)
        if bus:
            try:
                discovered.update(bus.list_agents())
            except Exception:
                pass

        manager = getattr(agent, "_agent_manager", None)
        if manager and hasattr(manager, "get_active_agents"):
            try:
                for spawned in manager.get_active_agents():
                    spawned_id = getattr(spawned, "agent_id", None)
                    if spawned_id:
                        discovered.add(str(spawned_id))
            except Exception:
                pass

        if not include_self:
            discovered.discard(getattr(agent, "agent_id", ""))

    return sorted(x for x in discovered if x)


def _resolve_message_targets(
    agent: Optional["EnvGenAgent"],
    target: str,
) -> tuple[List[str], Optional[str], Optional[str]]:
    """Resolve `target` to concrete runtime agent IDs."""
    if agent is None:
        return [], None, "Agent not configured"
    bus = _get_message_bus(agent)
    if not bus:
        return [], None, "MessageBus not available"

    available = [a for a in bus.list_agents() if a != getattr(agent, "agent_id", "")]
    normalized_target = str(target or "").strip()
    if normalized_target in available:
        return [normalized_target], None, None

    return [], None, f"Cannot send to '{normalized_target}'. Available: {available}"


def _create_message(
    source_agent_id: str,
    target_agent_id: str,
    content: str,
    msg_type: str,
    context: Dict = None,
    tags: List[str] = None,
    priority: str = "normal",
    persist: bool = False,
) -> BaseMessage:
    """Create a BaseMessage with enhanced metadata."""
    # Map priority string to MessagePriority
    priority_map = {
        "low": MessagePriority.LOW,
        "normal": MessagePriority.NORMAL,
        "high": MessagePriority.HIGH,
        "urgent": MessagePriority.URGENT,
    }
    msg_priority = priority_map.get(priority.lower(), MessagePriority.NORMAL)
    
    header = MessageHeader(
        message_id=str(uuid4()),
        source_agent_id=source_agent_id,
        target_agent_id=target_agent_id,
        priority=msg_priority,
    )
    return BaseMessage(
        header=header,
        message_type=MessageType.STATUS,
        payload=content,
        metadata={
            "msg_type": msg_type,
            "context": context or {},
            "tags": tags or [],
            "persist": persist,
            "read": False,
            "acknowledged": False,
        }
    )


# ============================================================================
# Send Message Tool
# ============================================================================

class SendMessageTool(BaseTool):
    """
    Send a message to another agent with optional tags and priority.
    
    Use this for one-way notifications, updates, or information sharing.
    """
    
    NAME = "send_message"
    
    DESCRIPTION = """Send a message to another agent.

Use this tool to:
- **START an agent's work loop**: msg_type="task_ready" (IMPORTANT!)
- Notify other agents of progress ("Backend API routes are ready")
- Share information ("API uses 'items' as response wrapper")
- Report completion ("Database schema created")
- Send warnings ("Database migration required")

Args:
    to_agent: Target agent ID (for example: design, backend, frontend, orchestrator)
    content: The message content
    msg_type: Type of message:
        - "task_ready": START an agent's work loop! (use to kickoff agents)
        - "info": General information (default)
        - "update": Status updates
        - "complete": Completion notification
        - "warning": Warnings
        - "issue": Bug reports / issues
    tags: List of tags for filtering (e.g., ["api", "format", "important"])
    priority: Message priority - YOU decide the urgency! Default: normal
    persist: If true, message won't be auto-cleared from inbox. Default: false

## Priority Levels (YOU DECIDE!)

| Priority | When to Use |
|----------|-------------|
| urgent   | Needs IMMEDIATE attention (bugs, blockers, activation) |
| high     | Important, process ASAP (questions, issues, completion) |
| normal   | Standard messages (info, updates) |
| low      | Not time-sensitive (FYI, background info) |

Higher priority messages are processed FIRST.
Same priority = FIFO (first in, first out).

Examples:
    # START an agent's work loop (MOST IMPORTANT!)
    send_message(
        to_agent="design", 
        content="Requirements ready. Please create design specs.",
        msg_type="task_ready",  # <-- This starts the agent's main loop!
        priority="high"
    )
    
    # Normal info message
    send_message(to_agent="frontend", content="API ready")
    
    # Urgent - critical issue
    send_message(
        to_agent="backend",
        content="AUTH IS BROKEN! Fix immediately!",
        msg_type="issue",
        priority="urgent"
    )
    
    # Low priority - FYI info
    send_message(
        to_agent="orchestrator",
        content="Progress update: 50% complete",
        priority="low"
    )

Returns:
    Confirmation with message ID
"""
    
    def __init__(self, agent: "EnvGenAgent" = None):
        super().__init__(name=self.NAME, category=ToolCategory.AGENT)
        self.agent = agent
    
    def set_agent(self, agent: "EnvGenAgent"):
        """Set the agent that will use this tool."""
        self.agent = agent
    
    @property
    def tool_definition(self):
        return self.get_tool_param()
    
    def get_tool_param(self):
        dynamic_targets = _discover_agent_ids(self.agent, include_self=False)
        return create_tool_param(
            name=self.NAME,
            description=self.DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "to_agent": {
                        "type": "string",
                        "enum": dynamic_targets,
                        "description": "Target agent ID"
                    },
                    "content": {
                        "type": "string",
                        "description": "Message content"
                    },
                    "msg_type": {
                        "type": "string",
                        "enum": ["info", "update", "complete", "warning", "issue", "task_ready"],
                        "description": "Type of message. Use 'task_ready' to START an agent's work loop! (default: info)"
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Tags for filtering (e.g., ['api', 'format'])"
                    },
                    "priority": {
                        "type": "string",
                        "enum": ["low", "normal", "high", "urgent"],
                        "description": "Message priority (default: normal)"
                    },
                    "persist": {
                        "type": "boolean",
                        "description": "Keep message in inbox even after clearing (default: false)"
                    }
                },
                "required": ["to_agent", "content"]
            }
        )
    
    def execute(
        self, 
        to_agent: str, 
        content: str, 
        msg_type: str = "info",
        tags: List[str] = None,
        priority: str = "normal",
        persist: bool = False,
    ) -> ToolResult:
        if not self.agent:
            return ToolResult(success=False, error_message="Agent not configured")
        
        bus = _get_message_bus(self.agent)
        if not bus:
            return ToolResult(success=False, error_message="MessageBus not available")

        resolved_targets, alias_warning, resolve_error = _resolve_message_targets(self.agent, to_agent)
        if resolve_error:
            return ToolResult(success=False, error_message=resolve_error)

        # Queue for async send via agent's pending notifications (thread-safe)
        if not hasattr(self.agent, "_pending_notifications"):
            self.agent._pending_notifications = []
        pending = self.agent._pending_notifications

        # Track sent messages for status monitoring
        requires_response = msg_type in ("issue", "question", "task_ready")
        tracker = getattr(self.agent, "_message_tracker", None)
        message_ids: List[str] = []
        for target_id in resolved_targets:
            message = _create_message(
                source_agent_id=self.agent.agent_id,
                target_agent_id=target_id,
                content=content,
                msg_type=msg_type,
                tags=tags,
                priority=priority,
                persist=persist,
            )
            pending.append((bus, message))
            message_ids.append(message.header.message_id)
            if tracker:
                tracker.track_sent(
                    message_id=message.header.message_id,
                    to_agent=target_id,
                    content=content,
                    msg_type=msg_type,
                    requires_response=requires_response,
                    timeout_seconds=180 if msg_type == "issue" else 120,
                )
            try:
                hubs = getattr(self.agent, "_hubs", None)
                if hubs:
                    hubs.eventhub.publish_event(
                        "messagebus",
                        msg_type,
                        {
                            "from": self.agent.agent_id,
                            "to": target_id,
                            "content": content,
                            "tags": tags or [],
                            "persist": persist,
                            "message_id": message.header.message_id,
                        },
                        recipients=[target_id],
                        priority=priority,
                    )
            except Exception:
                pass
        
        tag_str = f", tags={tags}" if tags else ""
        info = f"Message sent to {resolved_targets}{tag_str}: '{content[:50]}...'"
        if alias_warning:
            info += f"\n{alias_warning}"
        return ToolResult(
            success=True,
            data={
                "sent": True,
                "message_id": message_ids[0] if message_ids else None,
                "message_ids": message_ids,
                "to": resolved_targets,
                "msg_type": msg_type,
                "priority": priority,
                "tags": tags or [],
                "persist": persist,
                "info": info,
            }
        )


# ============================================================================
# Ask Agent Tool
# ============================================================================

class AskAgentTool(BaseTool):
    """
    Ask another agent a question and wait for their response.
    
    Use this when you need information from another agent's domain.
    """
    
    NAME = "ask_agent"
    
    DESCRIPTION = """Ask another agent a question and wait for response.

Use this when you need information from another agent:
- Ask 'design' about API specifications or schema
- Ask 'database' about table structures  
- Ask 'backend' about API endpoints
- Ask 'frontend' about UI components
- Ask 'orchestrator' about requirements or overall workflow state

Args:
    agent_id: Target agent (design, database, backend, frontend, orchestrator, verifier, ...)
    question: Your question

Returns:
    The agent's response
"""
    
    def __init__(self, agent: "EnvGenAgent" = None):
        super().__init__(name=self.NAME, category=ToolCategory.AGENT)
        self.agent = agent
    
    def set_agent(self, agent: "EnvGenAgent"):
        self.agent = agent
    
    @property
    def tool_definition(self):
        return self.get_tool_param()
    
    def get_tool_param(self):
        dynamic_targets = _discover_agent_ids(self.agent, include_self=False)
        return create_tool_param(
            name=self.NAME,
            description=self.DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "enum": dynamic_targets,
                        "description": "Target agent ID"
                    },
                    "question": {
                        "type": "string",
                        "description": "Your question"
                    }
                },
                "required": ["agent_id", "question"]
            }
        )
    
    def execute(self, agent_id: str, question: str) -> ToolResult:
        """
        Send a question to another agent. The answer will be delivered via check_inbox.
        The tool queues the question message for async sending.
        """
        if not self.agent:
            return ToolResult(success=False, error_message="Agent not configured")
        
        bus = _get_message_bus(self.agent)
        if not bus:
            return ToolResult(success=False, error_message="MessageBus not available")

        resolved_targets, alias_warning, resolve_error = _resolve_message_targets(self.agent, agent_id)
        if resolve_error:
            return ToolResult(success=False, error_message=resolve_error)
        if len(resolved_targets) != 1:
            return ToolResult(
                success=False,
                error_message=(
                    f"Ambiguous ask target '{agent_id}'. "
                    f"Resolved candidates: {resolved_targets}. Use a concrete runtime agent ID."
                ),
            )
        resolved_agent_id = resolved_targets[0]
        
        # Generate question ID
        question_id = str(uuid4())
        
        # Create question message with high priority
        message = _create_message(
            source_agent_id=self.agent.agent_id,
            target_agent_id=resolved_agent_id,
            content=question,
            msg_type="question",
            priority="high",
            context={"question_id": question_id},
        )
        
        # Queue for async send via pending notifications (thread-safe)
        if not hasattr(self.agent, "_pending_notifications"):
            self.agent._pending_notifications = []
        self.agent._pending_notifications.append((bus, message))
        
        return ToolResult(
            success=True,
            data={
                "status": "question_sent",
                "question_id": question_id,
                "to": resolved_agent_id,
                "info": (
                    f"Question sent to {resolved_agent_id}. Check inbox later for answer."
                    + (f"\n{alias_warning}" if alias_warning else "")
                ),
            }
        )


# ============================================================================
# Broadcast Tool
# ============================================================================

class BroadcastTool(BaseTool):
    """
    Broadcast a message to all other agents with optional tags and persistence.
    """
    
    NAME = "broadcast"
    
    DESCRIPTION = """Broadcast a message to all other agents.

Use for important announcements everyone should know:
- Phase completions ("Design phase complete")
- Critical changes ("API response format changed")
- System-wide updates ("Database schema updated")
- Requirements/design specs that all agents need

Args:
    message: The message to broadcast
    msg_type: Type (info, update, complete, warning). Default: info
    tags: List of tags for filtering (e.g., ["requirements", "design", "important"])
    persist: If true, message won't be auto-cleared (good for specs). Default: false

Examples:
    # Simple announcement
    broadcast(message="Design phase complete")
    
    # Important spec that should persist
    broadcast(
        message="REQUIREMENTS: {project_name: 'MyApp', ...}",
        tags=["requirements", "important"],
        persist=true
    )

Returns:
    Confirmation with recipient count
"""
    
    def __init__(self, agent: "EnvGenAgent" = None):
        super().__init__(name=self.NAME, category=ToolCategory.AGENT)
        self.agent = agent
    
    def set_agent(self, agent: "EnvGenAgent"):
        self.agent = agent
    
    @property
    def tool_definition(self):
        return self.get_tool_param()
    
    def get_tool_param(self):
        dynamic_senders = _discover_agent_ids(self.agent, include_self=False)
        return create_tool_param(
            name=self.NAME,
            description=self.DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "Message to broadcast"
                    },
                    "msg_type": {
                        "type": "string",
                        "enum": ["info", "update", "complete", "warning"],
                        "description": "Type of message"
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Tags for filtering (e.g., ['requirements', 'design'])"
                    },
                    "persist": {
                        "type": "boolean",
                        "description": "Keep message in inbox even after clearing (default: false)"
                    }
                },
                "required": ["message"]
            }
        )
    
    def execute(
        self, 
        message: str, 
        msg_type: str = "info",
        tags: List[str] = None,
        persist: bool = False,
    ) -> ToolResult:
        if not self.agent:
            return ToolResult(success=False, error_message="Agent not configured")
        
        bus = _get_message_bus(self.agent)
        if not bus:
            return ToolResult(success=False, error_message="MessageBus not available")
        
        recipients = [a for a in bus.list_agents() if a != self.agent.agent_id]
        
        # Queue messages for each recipient (thread-safe via pending notifications)
        if not hasattr(self.agent, "_pending_notifications"):
            self.agent._pending_notifications = []
        
        for recipient in recipients:
            msg = _create_message(
                source_agent_id=self.agent.agent_id,
                target_agent_id=recipient,
                content=message,
                msg_type=msg_type,
                tags=tags,
                persist=persist,
            )
            self.agent._pending_notifications.append((bus, msg))
        try:
            hubs = getattr(self.agent, "_hubs", None)
            if hubs:
                hubs.eventhub.publish_event(
                    "messagebus",
                    msg_type,
                    {
                        "from": self.agent.agent_id,
                        "content": message,
                        "tags": tags or [],
                        "persist": persist,
                        "broadcast": True,
                    },
                    recipients=recipients,
                    priority="normal",
                )
        except Exception:
            pass
        
        tag_str = f", tags={tags}" if tags else ""
        persist_str = " (persistent)" if persist else ""
        
        return ToolResult(
            success=True,
            data={
                "broadcast": True,
                "recipients": recipients,
                "message_count": len(recipients),
                "tags": tags or [],
                "persist": persist,
                "info": f"Broadcast{persist_str} sent to {len(recipients)} agents{tag_str}"
            }
        )


# ============================================================================
# Check Inbox Tool
# ============================================================================



class CheckInboxTool(BaseTool):
    """
    Check inbox for received messages with smart filtering.
    """
    
    NAME = "check_inbox"
    
    DESCRIPTION = """Check your inbox for messages from other agents with optional filtering.

Messages arrive from:
- Subscriptions (status updates, broadcasts)
- Direct messages from other agents
- Answers to your questions

Args:
    limit: Max messages to return (default: 10)
    clear: Clear messages after reading (default: true). Note: persist=true messages are never cleared.
    from_agent: Filter by sender (e.g., "design", "backend")
    tags: Filter by tags (e.g., ["api", "format"])
    msg_type: Filter by message type (e.g., "complete", "issue")
    unread_only: Only return unread messages (default: false)
    search: Search keyword in message content

Examples:
    # Get all messages
    check_inbox()
    
    # Get only messages from design agent
    check_inbox(from_agent="design")
    
    # Get messages with specific tags
    check_inbox(tags=["api"])
    
    # Search for specific content
    check_inbox(search="endpoint")
    
    # Combine filters
    check_inbox(from_agent="backend", tags=["api"], unread_only=true)

Returns:
    List of matching messages with metadata
"""
    
    def __init__(self, agent: "EnvGenAgent" = None):
        super().__init__(name=self.NAME, category=ToolCategory.AGENT)
        self.agent = agent
    
    def set_agent(self, agent: "EnvGenAgent"):
        self.agent = agent
    
    @property
    def tool_definition(self):
        return self.get_tool_param()
    
    def get_tool_param(self):
        dynamic_senders = _discover_agent_ids(self.agent, include_self=False)
        return create_tool_param(
            name=self.NAME,
            description=self.DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Max messages to return (default: 10)"
                    },
                    "clear": {
                        "type": "boolean",
                        "description": "Clear non-persistent messages after reading (default: true)"
                    },
                    "from_agent": {
                        "type": "string",
                        "enum": dynamic_senders,
                        "description": "Filter by sender agent"
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Filter by tags (matches if ANY tag matches)"
                    },
                    "msg_type": {
                        "type": "string",
                        "enum": ["info", "update", "complete", "warning", "issue", "question", "answer"],
                        "description": "Filter by message type"
                    },
                    "unread_only": {
                        "type": "boolean",
                        "description": "Only return unread messages (default: false)"
                    },
                    "search": {
                        "type": "string",
                        "description": "Search keyword in message content"
                    }
                },
                "required": []
            }
        )
    
    def execute(
        self,
        limit: int = 10,
        clear: bool = True,
        from_agent: str = None,
        tags: List[str] = None,
        msg_type: str = None,
        unread_only: bool = False,
        search: str = None,
    ) -> ToolResult:
        if not self.agent:
            return ToolResult(success=False, error_message="Agent not configured")

        # #292: the schema declares limit as integer, but the model reasonably
        # passes numeric args as strings ("10"). `filtered[:limit]` below then
        # raises "slice indices must be integers" and the whole inbox read
        # fails (r76 live, 10×). Coerce a coercible value; fall back to the
        # default for an uncoercible one — never crash on a plausible arg.
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = 10

        durable_events = []
        try:
            hubs = getattr(self.agent, "_hubs", None)
            if hubs:
                durable_events = hubs.eventhub.list_inbox(self.agent.agent_id, unread_only=unread_only)
        except Exception:
            durable_events = []

        # Get all messages (we'll filter ourselves)
        all_messages = self.agent.get_inbox_messages(limit=999, clear=False)
        if durable_events:
            for event in durable_events:
                payload = event.get("payload") or {}
                all_messages.append({
                    "id": event.get("id"),
                    "from": payload.get("from") or event.get("source_hub"),
                    "type": event.get("event_type"),
                    # #291: raw, untruncated payload — same as the non-durable
                    # formatting path below. #274 wrapped this in an undefined
                    # summarize_inbox_message_body(...) (NameError crashed the
                    # whole check_inbox on any durable event) AND a summarizer
                    # would violate the no-truncation invariant (see the #274
                    # NOTE below + test_inbox_no_content_truncation).
                    "content": payload.get("content") or payload.get("body") or str(payload),
                    "tags": payload.get("tags", []),
                    "priority": event.get("priority", "normal"),
                    "persist": True,
                    "timestamp": event.get("created_at"),
                    "eventhub": True,
                })
        
        if not all_messages:
            return ToolResult(
                success=True,
                data={
                    "count": 0,
                    "messages": [],
                    "filters_applied": self._get_filter_summary(from_agent, tags, msg_type, unread_only, search),
                    "info": "Inbox empty. No new messages."
                }
            )
        
        # Apply filters
        filtered = []
        for msg in all_messages:
            # Filter by sender
            if from_agent and msg.get("from") != from_agent:
                continue
            
            # Filter by tags (ANY match)
            if tags:
                msg_tags = msg.get("tags", [])
                if not any(t in msg_tags for t in tags):
                    continue
            
            # Filter by type
            if msg_type and msg.get("type") != msg_type:
                continue
            
            # Filter unread
            if unread_only and msg.get("read", False):
                continue
            
            # Search in content
            if search:
                content = msg.get("content", "").lower()
                if search.lower() not in content:
                    continue
            
            filtered.append(msg)
        
        # Apply limit
        filtered = filtered[:limit]

        # #274 NOTE: inbox bodies are deliberately NOT truncated. A 2026-06-01 directive
        # ("不要截断，这个肯定要完整信息的") removed a [:500] cap that broke Facebook-scale
        # task_ready: the orchestrator sends a multi-thousand-char CONTRACT through the
        # inbox, and a trimmed body left the receiver unable to see it and unable to ask for
        # the rest (the re-ask reply truncated too), wedging the pipeline. test_inbox_no_
        # content_truncation locks this in. Context savings for oversized bodies must come
        # from the SENDER (send a summary + a hub pointer), not from clipping on read.

        # Mark as read
        for msg in filtered:
            msg["read"] = True
        
        # Clear non-persistent messages if requested
        if clear:
            inbox = getattr(self.agent, "_subscription_inbox", [])
            # Keep persistent messages and messages not in our filtered result
            read_message_ids = {
                str(m.get("id"))
                for m in filtered
                if m.get("id") and not m.get("persist", False)
            }
            fallback_object_ids = {
                id(m)
                for m in filtered
                if not m.get("id") and not m.get("persist", False)
            }
            new_inbox = [
                m for m in inbox
                if m.get("persist", False)
                or (
                    str(m.get("id")) not in read_message_ids
                    and (m.get("id") or id(m) not in fallback_object_ids)
                )
            ]
            self.agent._subscription_inbox = new_inbox
            try:
                hubs = getattr(self.agent, "_hubs", None)
                if hubs:
                    for msg in filtered:
                        if msg.get("eventhub") and msg.get("id"):
                            # O14/Phase 4.1: thread caller=agent_id so the
                            # mutation is attributable; self-mutation (caller
                            # == agent) passes the Phase 4.1 identity gate.
                            hubs.eventhub.mark_read(
                                self.agent.agent_id, msg.get("id"),
                                caller=self.agent.agent_id,
                            )
            except Exception:
                pass
        
        # Format output
        formatted = []
        for msg in filtered:
            formatted.append({
                "id": msg.get("id", ""),
                "from": msg.get("from", "unknown"),
                "type": msg.get("type", "message"),
                # NO TRUNCATION: agents must see the full inbound
                # payload. The PRIOR `[:500]` silently sliced every
                # message body to 500 chars, breaking Facebook-scale
                # tasks at v3 re-pilot 2026-06-01 (~3500-char task_ready
                # payloads → Design saw 14%, couldn't see the contract,
                # asked orchestrator to re-send everything). Per user
                # 2026-06-01 directive: "不要截断，这个肯定要完整信息的".
                "content": msg.get("content", ""),
                "tags": msg.get("tags", []),
                "priority": msg.get("priority", "normal"),
                "persist": msg.get("persist", False),
                "timestamp": msg.get("timestamp", ""),
            })
        
        return ToolResult(
            success=True,
            data={
                "count": len(formatted),
                "total_inbox": len(all_messages),
                "messages": formatted,
                "filters_applied": self._get_filter_summary(from_agent, tags, msg_type, unread_only, search),
                "info": f"Retrieved {len(formatted)} of {len(all_messages)} message(s)"
            }
        )
    
    def _get_filter_summary(self, from_agent, tags, msg_type, unread_only, search) -> Dict:
        """Get summary of applied filters."""
        filters = {}
        if from_agent:
            filters["from_agent"] = from_agent
        if tags:
            filters["tags"] = tags
        if msg_type:
            filters["msg_type"] = msg_type
        if unread_only:
            filters["unread_only"] = True
        if search:
            filters["search"] = search
        return filters if filters else {"none": "all messages"}


# ============================================================================
# Get Important Messages Tool
# ============================================================================

class GetImportantMessagesTool(BaseTool):
    """
    Get all persistent/important messages that won't be auto-cleared.
    """
    
    NAME = "get_important_messages"
    
    DESCRIPTION = """Get all important (persistent) messages.

These are messages sent with persist=true that won't be auto-cleared.
Use this to review key information shared by other agents.

Returns:
    List of all persistent messages
"""
    
    def __init__(self, agent: "EnvGenAgent" = None):
        super().__init__(name=self.NAME, category=ToolCategory.AGENT)
        self.agent = agent
    
    def set_agent(self, agent: "EnvGenAgent"):
        self.agent = agent
    
    @property
    def tool_definition(self):
        return self.get_tool_param()
    
    def get_tool_param(self):
        dynamic_senders = _discover_agent_ids(self.agent, include_self=False)
        return create_tool_param(
            name=self.NAME,
            description=self.DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {},
                "required": []
            }
        )
    
    def execute(self) -> ToolResult:
        if not self.agent:
            return ToolResult(success=False, error_message="Agent not configured")
        
        inbox = getattr(self.agent, "_subscription_inbox", [])
        important = [m for m in inbox if m.get("persist", False)]
        
        formatted = []
        for msg in important:
            formatted.append({
                "from": msg.get("from", "unknown"),
                "type": msg.get("type", "message"),
                # NO TRUNCATION (see CheckInboxTool.execute above).
                "content": msg.get("content", ""),
                "tags": msg.get("tags", []),
                "timestamp": msg.get("timestamp", ""),
            })
        
        return ToolResult(
            success=True,
            data={
                "count": len(formatted),
                "messages": formatted,
                "info": f"Found {len(formatted)} important message(s)"
            }
        )


# ============================================================================
# Search Messages Tool
# ============================================================================

class SearchMessagesTool(BaseTool):
    """
    Full-text search across all messages in inbox.
    """
    
    NAME = "search_messages"
    
    DESCRIPTION = """Search for messages containing specific keywords.

Use this to find specific information shared by other agents.

Args:
    query: Search keywords
    from_agent: Optional - limit search to specific sender

Examples:
    search_messages(query="API format")
    search_messages(query="endpoint", from_agent="backend")

Returns:
    List of matching messages
"""
    
    def __init__(self, agent: "EnvGenAgent" = None):
        super().__init__(name=self.NAME, category=ToolCategory.AGENT)
        self.agent = agent
    
    def set_agent(self, agent: "EnvGenAgent"):
        self.agent = agent
    
    @property
    def tool_definition(self):
        return self.get_tool_param()
    
    def get_tool_param(self):
        dynamic_senders = _discover_agent_ids(self.agent, include_self=False)
        return create_tool_param(
            name=self.NAME,
            description=self.DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search keywords"
                    },
                    "from_agent": {
                        "type": "string",
                        "enum": dynamic_senders,
                        "description": "Optional: limit search to specific sender"
                    }
                },
                "required": ["query"]
            }
        )
    
    def execute(self, query: str, from_agent: str = None) -> ToolResult:
        if not self.agent:
            return ToolResult(success=False, error_message="Agent not configured")
        
        inbox = getattr(self.agent, "_subscription_inbox", [])
        query_lower = query.lower()
        
        matches = []
        for msg in inbox:
            # Filter by sender if specified
            if from_agent and msg.get("from") != from_agent:
                continue
            
            # Search in content and tags
            content = msg.get("content", "").lower()
            tags = " ".join(msg.get("tags", [])).lower()
            msg_type = msg.get("type", "").lower()
            
            if query_lower in content or query_lower in tags or query_lower in msg_type:
                matches.append(msg)
        
        formatted = []
        for msg in matches:
            formatted.append({
                "from": msg.get("from", "unknown"),
                "type": msg.get("type", "message"),
                # NO TRUNCATION (see CheckInboxTool.execute above).
                "content": msg.get("content", ""),
                "tags": msg.get("tags", []),
                "timestamp": msg.get("timestamp", ""),
                "match_context": self._get_match_context(msg.get("content", ""), query),
            })
        
        return ToolResult(
            success=True,
            data={
                "query": query,
                "from_agent": from_agent,
                "count": len(formatted),
                "messages": formatted,
                "info": f"Found {len(formatted)} message(s) matching '{query}'"
            }
        )
    
    def _get_match_context(self, content: str, query: str) -> str:
        """Get snippet of content around the match."""
        content_lower = content.lower()
        query_lower = query.lower()
        pos = content_lower.find(query_lower)
        if pos == -1:
            return ""
        
        start = max(0, pos - 30)
        end = min(len(content), pos + len(query) + 30)
        snippet = content[start:end]
        
        if start > 0:
            snippet = "..." + snippet
        if end < len(content):
            snippet = snippet + "..."
        
        return snippet


# ============================================================================
# List Agents Tool
# ============================================================================

class ListAgentsTool(BaseTool):
    """
    List available agents you can communicate with.
    """
    
    NAME = "list_agents"
    
    DESCRIPTION = """List available agents you can communicate with.

Returns:
    List of agent IDs and their roles
"""
    
    def __init__(self, agent: "EnvGenAgent" = None):
        super().__init__(name=self.NAME, category=ToolCategory.AGENT)
        self.agent = agent
    
    def set_agent(self, agent: "EnvGenAgent"):
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
                "required": []
            }
        )
    
    def execute(self) -> ToolResult:
        if not self.agent:
            return ToolResult(success=False, error_message="Agent not configured")
        
        bus = _get_message_bus(self.agent)
        if not bus:
            return ToolResult(success=False, error_message="MessageBus not available")
        
        agents = []
        for agent_id in bus.list_agents():
            if agent_id != self.agent.agent_id:  # Exclude self
                agents.append({
                    "id": agent_id,
                    "role": ROLE_DESCRIPTIONS.get(agent_id, "Agent"),
                })
        
        if not agents:
            return ToolResult(
                success=True,
                data={
                    "agents": [],
                    "info": "No other agents available"
                }
            )
        
        return ToolResult(
            success=True,
            data={
                "agents": agents,
                "info": f"Found {len(agents)} available agents"
            }
        )


# ============================================================================
# Subscribe Messages Tool
# ============================================================================

class SubscribeMessagesTool(BaseTool):
    """
    Subscribe to receive specific types of messages via MessageBus.
    """
    
    NAME = "subscribe_messages"
    
    DESCRIPTION = """Subscribe to message types from MessageBus.

Available types:
- status: Progress updates from agents
- task: Task assignments
- error: Error notifications
- broadcast: System-wide announcements

Args:
    message_types: List of types to subscribe to

Returns:
    Subscription ID
"""
    
    def __init__(self, agent: "EnvGenAgent" = None):
        super().__init__(name=self.NAME, category=ToolCategory.AGENT)
        self.agent = agent
    
    def set_agent(self, agent: "EnvGenAgent"):
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
                    "message_types": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Types to subscribe: status, task, error, broadcast"
                    }
                },
                "required": ["message_types"]
            }
        )
    
    def execute(self, message_types: List[str]) -> ToolResult:
        if not self.agent:
            return ToolResult(success=False, error_message="Agent not configured")
        
        bus = _get_message_bus(self.agent)
        if not bus:
            return ToolResult(success=False, error_message="MessageBus not available")
        
        # Subscribe directly via MessageBus
        sub_id = str(uuid4())[:8]
        bus_sub_ids = []
        
        for msg_type in message_types:
            try:
                # Convert string to MessageType
                mt = None
                for e in MessageType:
                    if e.value == msg_type:
                        mt = e
                        break
                
                # Create callback that puts messages in agent's inbox
                async def on_message(message: BaseMessage, agent=self.agent):
                    inbox = getattr(agent, "_subscription_inbox", [])
                    inbox.append({
                        "id": message.header.message_id,
                        "from": message.header.source_agent_id,
                        "type": message.metadata.get("msg_type", message.message_type.value),
                        "content": message.payload if isinstance(message.payload, str) else str(message.payload),
                        "tags": message.metadata.get("tags", []),
                        "metadata": dict(message.metadata or {}),
                        "priority": message.header.priority.name.lower(),
                        "persist": message.metadata.get("persist", False),
                        "read": False,
                        "timestamp": datetime.now().isoformat(),
                    })
                
                bus_sub_id = bus.subscribe(
                    subscriber_id=self.agent.agent_id,
                    message_types=[mt] if mt else None,
                    async_callback=on_message,
                )
                bus_sub_ids.append(bus_sub_id)
            except Exception as e:
                pass  # Skip invalid message types
        
        # Store subscription info in agent for later unsubscribe
        subscriptions = getattr(self.agent, "_subscriptions", {})
        subscriptions[sub_id] = {"types": message_types, "bus_sub_ids": bus_sub_ids}
        
        return ToolResult(
            success=True,
            data={
                "subscription_id": sub_id,
                "types": message_types,
                "info": f"Subscribed to {message_types}. Use check_inbox() to see messages."
            }
        )


# ============================================================================
# Unsubscribe Messages Tool
# ============================================================================

class UnsubscribeMessagesTool(BaseTool):
    """
    Unsubscribe from message types.
    """
    
    NAME = "unsubscribe_messages"
    
    DESCRIPTION = """Unsubscribe from messages.

Args:
    subscription_id: The subscription ID returned by subscribe_messages

Returns:
    Confirmation of unsubscription
"""
    
    def __init__(self, agent: "EnvGenAgent" = None):
        super().__init__(name=self.NAME, category=ToolCategory.AGENT)
        self.agent = agent
    
    def set_agent(self, agent: "EnvGenAgent"):
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
                    "subscription_id": {
                        "type": "string",
                        "description": "Subscription ID to unsubscribe"
                    }
                },
                "required": ["subscription_id"]
            }
        )
    
    def execute(self, subscription_id: str) -> ToolResult:
        if not self.agent:
            return ToolResult(success=False, error_message="Agent not configured")
        
        bus = _get_message_bus(self.agent)
        if not bus:
            return ToolResult(success=False, error_message="MessageBus not available")
        
        # Get subscription info from agent
        subscriptions = getattr(self.agent, "_subscriptions", {})
        if subscription_id not in subscriptions:
            return ToolResult(
                success=False,
                error_message=f"Subscription {subscription_id} not found"
            )
        
        sub_info = subscriptions.pop(subscription_id)
        
        # Unsubscribe from MessageBus directly
        for bus_sub_id in sub_info.get("bus_sub_ids", []):
            try:
                bus.unsubscribe(bus_sub_id)
            except:
                pass
        
        return ToolResult(
            success=True,
            data={
                "unsubscribed": True,
                "subscription_id": subscription_id,
                "info": f"Unsubscribed from {subscription_id}"
            }
        )


# ============================================================================
# Publish Message Tool (Pub/Sub pattern)
# ============================================================================

class PublishMessageTool(BaseTool):
    """
    Publish a message to a topic (pub/sub pattern).
    All subscribers to that topic will receive the message.
    """
    
    NAME = "publish_message"
    
    DESCRIPTION = """Publish a message to MessageBus (pub/sub pattern).

Unlike send_message (point-to-point), publish sends to ALL subscribers
of the message type, not a specific agent.

Args:
    message_type: Type of message (status, task, error, broadcast)
    content: Message content
    
Returns:
    Confirmation of publication
"""
    
    def __init__(self, agent: "EnvGenAgent" = None):
        super().__init__(name=self.NAME, category=ToolCategory.AGENT)
        self.agent = agent
    
    def set_agent(self, agent: "EnvGenAgent"):
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
                    "message_type": {
                        "type": "string",
                        "enum": ["status", "task", "error", "broadcast"],
                        "description": "Type of message to publish"
                    },
                    "content": {
                        "type": "string",
                        "description": "Message content"
                    }
                },
                "required": ["message_type", "content"]
            }
        )
    
    def execute(self, message_type: str, content: str) -> ToolResult:
        if not self.agent:
            return ToolResult(success=False, error_message="Agent not configured")
        
        bus = _get_message_bus(self.agent)
        if not bus:
            return ToolResult(success=False, error_message="MessageBus not available")
        
        # Convert string to MessageType
        mt = MessageType.STATUS
        for e in MessageType:
            if e.value == message_type:
                mt = e
                break
        
        # Get all agents to publish to (excluding self)
        recipients = [a for a in bus.list_agents() if a != self.agent.agent_id]
        
        # Queue messages for each recipient (thread-safe via pending notifications)
        if not hasattr(self.agent, "_pending_notifications"):
            self.agent._pending_notifications = []
        
        for recipient in recipients:
            message = BaseMessage(
                header=MessageHeader(
                    source_agent_id=self.agent.agent_id,
                    target_agent_id=recipient,
                ),
                message_type=mt,
                payload=content,
                metadata={"msg_type": message_type},
            )
            self.agent._pending_notifications.append((bus, message))
        
        return ToolResult(
            success=True,
            data={
                "published": True,
                "type": message_type,
                "recipients": len(recipients),
                "info": f"Published {message_type} message to {len(recipients)} agents"
            }
        )


# ============================================================================
# Message Status Tracking Tools
# ============================================================================

class GetMessageStatusTool(BaseTool):
    """
    Get the delivery/read/response status of a sent message.
    Helps sender know if recipient received and is working on their message.
    """
    
    NAME = "get_message_status"
    
    DESCRIPTION = """Check the status of a message you sent.

Returns:
- status: pending/delivered/read/processing/responded
- is_overdue: True if expected response hasn't arrived within timeout
- timestamps: when delivered, read, responded

Use this to:
- Check if your issue report was received
- Know if recipient has started processing
- Detect if a message needs to be re-sent or escalated

Args:
    message_id: ID of the message (returned when you sent it)
"""
    
    def __init__(self, agent: "EnvGenAgent" = None):
        super().__init__(name=self.NAME, category=ToolCategory.AGENT)
        self.agent = agent
    
    def set_agent(self, agent: "EnvGenAgent"):
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
                    "message_id": {
                        "type": "string",
                        "description": "ID of the message to check"
                    }
                },
                "required": ["message_id"]
            }
        )
    
    def execute(self, message_id: str) -> ToolResult:
        if not self.agent:
            return ToolResult(success=False, error_message="Agent not configured")
        
        tracker = getattr(self.agent, "_message_tracker", None)
        if not tracker:
            return ToolResult(
                success=True,
                data={"info": "Message tracking not enabled. Status unknown."}
            )
        
        status = tracker.get_status(message_id)
        if not status:
            return ToolResult(
                success=True,
                data={"info": f"Message {message_id} not found in tracker. May be old or from different session."}
            )
        
        return ToolResult(success=True, data=status)


class GetPendingRepliesTool(BaseTool):
    """
    Get all messages you sent that expect a reply but haven't received one.
    Useful for tracking unanswered issues and questions.
    """
    
    NAME = "get_pending_replies"
    
    DESCRIPTION = """Get messages you sent that are awaiting responses.

Returns list of messages with:
- to: recipient agent
- type: message type (issue, question, etc.)
- status: current status
- elapsed_seconds: how long since sent
- is_overdue: True if past expected response time

Use this to:
- Track your outstanding issues/questions
- Identify agents that haven't responded
- Decide whether to follow up or escalate
"""
    
    def __init__(self, agent: "EnvGenAgent" = None):
        super().__init__(name=self.NAME, category=ToolCategory.AGENT)
        self.agent = agent
    
    def set_agent(self, agent: "EnvGenAgent"):
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
                    "include_non_overdue": {
                        "type": "boolean",
                        "description": "Include messages not yet overdue (default: True)"
                    }
                },
                "required": []
            }
        )
    
    def execute(self, include_non_overdue: bool = True) -> ToolResult:
        if not self.agent:
            return ToolResult(success=False, error_message="Agent not configured")
        
        tracker = getattr(self.agent, "_message_tracker", None)
        if not tracker:
            return ToolResult(
                success=True,
                data={"pending": [], "info": "Message tracking not enabled."}
            )
        
        pending = tracker.get_pending_responses()
        
        if not include_non_overdue:
            pending = [m for m in pending if m["is_overdue"]]
        
        overdue_count = sum(1 for m in pending if m["is_overdue"])
        
        return ToolResult(
            success=True,
            data={
                "pending": pending,
                "total": len(pending),
                "overdue_count": overdue_count,
                "info": f"{len(pending)} messages awaiting reply ({overdue_count} overdue)"
            }
        )


class AcknowledgeMessageTool(BaseTool):
    """
    Acknowledge receipt of a message. Sends ACK back to sender.
    Use this to let sender know you received their message.
    """
    
    NAME = "acknowledge_message"
    
    DESCRIPTION = """Acknowledge receipt of a message.

Sends automatic ACK to the sender so they know you received it.
The sender's get_message_status() will show status=delivered.

Args:
    message_id: ID of the received message
    note: Optional note to include with acknowledgement
"""
    
    def __init__(self, agent: "EnvGenAgent" = None):
        super().__init__(name=self.NAME, category=ToolCategory.AGENT)
        self.agent = agent
    
    def set_agent(self, agent: "EnvGenAgent"):
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
                    "message_id": {
                        "type": "string",
                        "description": "ID of the message to acknowledge"
                    },
                    "note": {
                        "type": "string",
                        "description": "Optional note (e.g., 'Working on it', 'Will fix in 5 min')"
                    }
                },
                "required": ["message_id"]
            }
        )
    
    def execute(self, message_id: str, note: str = None) -> ToolResult:
        if not self.agent:
            return ToolResult(success=False, error_message="Agent not configured")
        
        bus = _get_message_bus(self.agent)
        if not bus:
            return ToolResult(success=False, error_message="MessageBus not available")
        
        # Find the original message to get sender
        inbox = getattr(self.agent, "_inbox", [])
        original_msg = None
        for msg in inbox:
            msg_id = msg.get("id") if isinstance(msg, dict) else getattr(msg.header, "message_id", None)
            if msg_id == message_id:
                original_msg = msg
                break
        
        if not original_msg:
            return ToolResult(
                success=True,
                data={"info": f"Message {message_id} not found in inbox. May already be processed."}
            )
        
        # Get sender
        sender = original_msg.get("from") if isinstance(original_msg, dict) else original_msg.header.source_agent_id
        
        if not sender:
            return ToolResult(
                success=True,
                data={"info": "Cannot determine sender. ACK not sent."}
            )
        
        # Queue ACK message
        if not hasattr(self.agent, "_pending_notifications"):
            self.agent._pending_notifications = []
        
        ack_content = f"ACK: Received message {message_id[:8]}..."
        if note:
            ack_content += f" Note: {note}"
        
        ack_message = _create_message(
            source_agent_id=self.agent.agent_id,
            target_agent_id=sender,
            content=ack_content,
            msg_type="ack",
            context={"original_message_id": message_id},
            priority="normal",
        )
        self.agent._pending_notifications.append((bus, ack_message))
        
        return ToolResult(
            success=True,
            data={
                "acknowledged": True,
                "original_message_id": message_id,
                "ack_sent_to": sender,
                "note": note,
            }
        )


class MarkProcessingTool(BaseTool):
    """
    Mark that you're actively working on a received message/issue.
    Lets sender know their issue is being addressed.
    """
    
    NAME = "mark_processing"
    
    DESCRIPTION = """Mark a message as 'processing' - you're actively working on it.

Sends status update to sender. Their get_message_status() shows status=processing.

Use this to:
- Let sender know you're working on their issue
- Provide estimate of when you'll be done
- Prevent sender from escalating prematurely

Args:
    message_id: ID of the message you're processing
    estimated_minutes: Estimated time to complete (optional)
    status_note: Brief status update (optional)
"""
    
    def __init__(self, agent: "EnvGenAgent" = None):
        super().__init__(name=self.NAME, category=ToolCategory.AGENT)
        self.agent = agent
    
    def set_agent(self, agent: "EnvGenAgent"):
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
                    "message_id": {
                        "type": "string",
                        "description": "ID of the message you're processing"
                    },
                    "estimated_minutes": {
                        "type": "integer",
                        "description": "Estimated minutes to complete"
                    },
                    "status_note": {
                        "type": "string",
                        "description": "Brief status (e.g., 'Investigating root cause')"
                    }
                },
                "required": ["message_id"]
            }
        )
    
    def execute(
        self,
        message_id: str,
        estimated_minutes: int = None,
        status_note: str = None
    ) -> ToolResult:
        if not self.agent:
            return ToolResult(success=False, error_message="Agent not configured")
        
        bus = _get_message_bus(self.agent)
        if not bus:
            return ToolResult(success=False, error_message="MessageBus not available")
        
        # Find the original message to get sender
        inbox = getattr(self.agent, "_inbox", [])
        original_msg = None
        for msg in inbox:
            msg_id = msg.get("id") if isinstance(msg, dict) else getattr(msg.header, "message_id", None)
            if msg_id == message_id:
                original_msg = msg
                break
        
        if not original_msg:
            # Try interrupt messages
            interrupt_msgs = getattr(self.agent, "_interrupt_messages", [])
            for msg in interrupt_msgs:
                if msg.get("id") == message_id:
                    original_msg = msg
                    break
        
        if not original_msg:
            return ToolResult(
                success=True,
                data={"info": f"Message {message_id} not found. Continuing anyway."}
            )
        
        # Get sender
        sender = original_msg.get("from") if isinstance(original_msg, dict) else original_msg.header.source_agent_id
        
        if not sender:
            return ToolResult(success=True, data={"info": "Cannot determine sender."})
        
        # Queue processing status message
        if not hasattr(self.agent, "_pending_notifications"):
            self.agent._pending_notifications = []
        
        content = f"PROCESSING: Working on message {message_id[:8]}..."
        if status_note:
            content += f" Status: {status_note}"
        if estimated_minutes:
            content += f" ETA: ~{estimated_minutes} min"
        
        status_message = _create_message(
            source_agent_id=self.agent.agent_id,
            target_agent_id=sender,
            content=content,
            msg_type="status",
            context={
                "original_message_id": message_id,
                "processing_status": "in_progress",
                "estimated_minutes": estimated_minutes,
            },
            priority="normal",
        )
        self.agent._pending_notifications.append((bus, status_message))
        
        return ToolResult(
            success=True,
            data={
                "marked_processing": True,
                "original_message_id": message_id,
                "notified": sender,
                "estimated_minutes": estimated_minutes,
                "status_note": status_note,
            }
        )


# ============================================================================
# Exports
# ============================================================================

def create_communication_tools(agent: "EnvGenAgent" = None, include_advanced: bool = True) -> List[BaseTool]:
    """Create communication tools for an agent.

    By default returns full set; callers can request a core-only subset.
    """
    tools = [
        SendMessageTool(agent),
        AskAgentTool(agent),
        BroadcastTool(agent),
        CheckInboxTool(agent),
        ListAgentsTool(agent),
    ]
    if include_advanced:
        tools.extend([
            GetImportantMessagesTool(agent),
            SearchMessagesTool(agent),
            SubscribeMessagesTool(agent),
            UnsubscribeMessagesTool(agent),
            PublishMessageTool(agent),
            # Message status tracking tools
            GetMessageStatusTool(agent),
            GetPendingRepliesTool(agent),
            AcknowledgeMessageTool(agent),
            MarkProcessingTool(agent),
        ])
    return tools


__all__ = [
    "SendMessageTool",
    "AskAgentTool",
    "BroadcastTool",
    "CheckInboxTool",
    "GetImportantMessagesTool",
    "SearchMessagesTool",
    "ListAgentsTool",
    "SubscribeMessagesTool",
    "UnsubscribeMessagesTool",
    "PublishMessageTool",
    # Message status tracking
    "GetMessageStatusTool",
    "GetPendingRepliesTool",
    "AcknowledgeMessageTool",
    "MarkProcessingTool",
    "create_communication_tools",
]

