"""
Message Protocol Module - Unified communication messages between Agents

Includes:
- Message bus messages (TaskMessage, ResultMessage, StatusMessage, etc.)
- Code generation tasks (Task, Issue, TaskResult, VerifyResult, etc.)
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional, List, Dict
from uuid import uuid4


# =============================================================================
# Code Generation Task Types (for UserAgent <-> CodeAgent communication)
# =============================================================================

class TaskType(Enum):
    """Types of code generation tasks"""
    DESIGN = "design"           # Generate design documents
    BACKEND = "backend"         # Generate backend code
    FRONTEND = "frontend"       # Generate frontend code
    DATABASE = "database"       # Generate database schema
    ENV = "env"                 # Generate OpenEnv adapter
    DOCKER = "docker"           # Generate Docker config
    FIX = "fix"                 # Fix an issue
    TEST = "test"               # Run tests
    VERIFICATION = "verification"  # Verify environment is runnable


class TaskStatus(Enum):
    """Status of task execution"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


class IssueSeverity(Enum):
    """Severity levels for issues"""
    ERROR = "error"           # Must fix - blocks functionality
    WARNING = "warning"       # Should fix - degraded experience
    SUGGESTION = "suggestion" # Could fix - improvement opportunity


@dataclass
class FileSpec:
    """Specification for a file to be generated"""
    path: str                           # Relative path within project
    purpose: str                        # What this file does
    requirements: List[str] = field(default_factory=list)
    template: Optional[str] = None      # Optional template content
    dependencies: List[str] = field(default_factory=list)


@dataclass
class Task:
    """
    A code generation task from User Agent to Code Agent.
    Contains everything Code Agent needs to complete the work.
    """
    id: str
    type: TaskType
    
    # What to do
    description: str
    requirements: List[str] = field(default_factory=list)
    
    # Where to do it (structure constraints)
    target_directory: str = ""
    allowed_paths: List[str] = field(default_factory=list)
    file_specs: List[FileSpec] = field(default_factory=list)
    
    # Context
    existing_files: List[str] = field(default_factory=list)
    dependencies: Dict[str, str] = field(default_factory=dict)  # file -> content summary
    
    # Reference images for design (selected by User Agent)
    reference_images: List[Dict[str, str]] = field(default_factory=list)  # [{path, description, purpose}]
    
    # Acceptance criteria
    acceptance_criteria: List[str] = field(default_factory=list)
    
    # Priority and ordering
    priority: int = 0
    depends_on: List[str] = field(default_factory=list)  # Task IDs
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            "id": self.id,
            "type": self.type.value,
            "description": self.description,
            "requirements": self.requirements,
            "target_directory": self.target_directory,
            "allowed_paths": self.allowed_paths,
            "file_specs": [
                {
                    "path": f.path,
                    "purpose": f.purpose,
                    "requirements": f.requirements,
                    "dependencies": f.dependencies,
                }
                for f in self.file_specs
            ],
            "existing_files": self.existing_files,
            "reference_images": self.reference_images,
            "acceptance_criteria": self.acceptance_criteria,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Task":
        """Create from dictionary"""
        return cls(
            id=data["id"],
            type=TaskType(data["type"]),
            description=data["description"],
            requirements=data.get("requirements", []),
            target_directory=data.get("target_directory", ""),
            allowed_paths=data.get("allowed_paths", []),
            file_specs=[
                FileSpec(
                    path=f["path"],
                    purpose=f["purpose"],
                    requirements=f.get("requirements", []),
                    dependencies=f.get("dependencies", []),
                )
                for f in data.get("file_specs", [])
            ],
            existing_files=data.get("existing_files", []),
            acceptance_criteria=data.get("acceptance_criteria", []),
        )


@dataclass
class Issue:
    """
    An issue found by User Agent during verification.
    Provides clear context for Code Agent to fix.
    """
    id: str
    task_id: str              # Which task this relates to
    severity: IssueSeverity
    
    # Problem description
    title: str
    description: str
    error_message: Optional[str] = None
    
    # Location
    file_path: Optional[str] = None
    line_number: Optional[int] = None
    code_snippet: Optional[str] = None
    
    # Fix guidance
    suggested_fix: Optional[str] = None
    related_files: List[str] = field(default_factory=list)
    
    # Verification
    verification_command: Optional[str] = None
    expected_result: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "id": self.id,
            "task_id": self.task_id,
            "severity": self.severity.value,
            "title": self.title,
            "description": self.description,
            "error_message": self.error_message,
            "file_path": self.file_path,
            "line_number": self.line_number,
            "code_snippet": self.code_snippet,
            "suggested_fix": self.suggested_fix,
            "related_files": self.related_files,
            "verification_command": self.verification_command,
            "expected_result": self.expected_result,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Issue":
        """Create from dictionary"""
        return cls(
            id=data["id"],
            task_id=data["task_id"],
            severity=IssueSeverity(data["severity"]),
            title=data["title"],
            description=data["description"],
            error_message=data.get("error_message"),
            file_path=data.get("file_path"),
            line_number=data.get("line_number"),
            code_snippet=data.get("code_snippet"),
            suggested_fix=data.get("suggested_fix"),
            related_files=data.get("related_files", []),
            verification_command=data.get("verification_command"),
            expected_result=data.get("expected_result"),
        )
    
    def format_for_agent(self) -> str:
        """Format issue for agent consumption"""
        lines = [
            f"## Issue: {self.title}",
            f"Severity: {self.severity.value.upper()}",
            f"",
            f"### Description",
            self.description,
        ]
        
        if self.error_message:
            lines.extend(["", "### Error Message", "```", self.error_message, "```"])
        
        if self.file_path:
            loc = f"{self.file_path}"
            if self.line_number:
                loc += f":{self.line_number}"
            lines.extend(["", f"### Location", loc])
        
        if self.code_snippet:
            lines.extend(["", "### Code Snippet", "```", self.code_snippet, "```"])
        
        if self.suggested_fix:
            lines.extend(["", "### Suggested Fix", self.suggested_fix])
        
        if self.related_files:
            lines.extend(["", "### Related Files", *[f"- {f}" for f in self.related_files]])
        
        return "\n".join(lines)


@dataclass
class CommandResult:
    """Result of a command execution"""
    command: str
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    
    @property
    def success(self) -> bool:
        return self.exit_code == 0


@dataclass
class TaskResult:
    """Result from Code Agent after executing a task."""
    task_id: str
    status: TaskStatus
    
    # What was done
    files_created: List[str] = field(default_factory=list)
    files_modified: List[str] = field(default_factory=list)
    
    # Commands run
    commands: List[Dict] = field(default_factory=list)
    
    # Issues encountered
    issues: List[str] = field(default_factory=list)
    
    # Summary
    summary: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "task_id": self.task_id,
            "status": self.status.value,
            "files_created": self.files_created,
            "files_modified": self.files_modified,
            "commands": self.commands,
            "issues": self.issues,
            "summary": self.summary,
        }


@dataclass
class FixResult:
    """Result from Code Agent after fixing an issue."""
    issue_id: str
    fixed: bool
    
    # What was changed
    changes: List[str] = field(default_factory=list)
    
    # Verification
    needs_verification: List[str] = field(default_factory=list)
    
    # Notes
    notes: str = ""


@dataclass
class VerifyResult:
    """Result from User Agent after verifying a task or fix."""
    task_id: str
    passed: bool
    
    # What was checked
    checks_performed: List[str] = field(default_factory=list)
    
    # Results
    passed_checks: List[str] = field(default_factory=list)
    failed_checks: List[str] = field(default_factory=list)
    
    # Problems found
    problems: List[str] = field(default_factory=list)
    
    # Overall assessment
    summary: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "task_id": self.task_id,
            "passed": self.passed,
            "checks_performed": self.checks_performed,
            "passed_checks": self.passed_checks,
            "failed_checks": self.failed_checks,
            "problems": self.problems,
            "summary": self.summary,
        }


# =============================================================================
# Message Bus Types (for general Agent-to-Agent communication)
# =============================================================================


class MessageType(Enum):
    """Message type enumeration"""
    TASK = "task"           # Task assignment
    RESULT = "result"       # Task result
    STATUS = "status"       # Status update
    ERROR = "error"         # Error report
    CONTROL = "control"     # Control command
    HEARTBEAT = "heartbeat" # Heartbeat detection
    LOG = "log"             # Log message


class MessagePriority(Enum):
    """Message priority levels"""
    LOW = 0
    NORMAL = 1
    HIGH = 2
    URGENT = 3


class MessageStatus(Enum):
    """Message delivery and processing status"""
    PENDING = "pending"       # Sent, waiting for delivery
    DELIVERED = "delivered"   # Delivered to inbox
    READ = "read"             # Recipient has seen it (via check_inbox)
    PROCESSING = "processing" # Recipient is working on it
    RESPONDED = "responded"   # Recipient has replied
    EXPIRED = "expired"       # TTL expired, no response


class ControlAction(Enum):
    """Control action types"""
    START = "start"
    STOP = "stop"
    PAUSE = "pause"
    RESUME = "resume"
    RESTART = "restart"
    SHUTDOWN = "shutdown"


@dataclass
class MessageHeader:
    """Message header - contains metadata"""
    message_id: str = field(default_factory=lambda: str(uuid4()))
    timestamp: datetime = field(default_factory=datetime.now)
    source_agent_id: str = ""
    target_agent_id: str = ""  # Empty string means broadcast
    priority: MessagePriority = MessagePriority.NORMAL
    correlation_id: Optional[str] = None  # Used to track related message chains
    reply_to: Optional[str] = None  # ID of message being replied to
    ttl: Optional[int] = None  # Message time-to-live (seconds)
    # Status tracking
    status: MessageStatus = MessageStatus.PENDING
    delivered_at: Optional[datetime] = None
    read_at: Optional[datetime] = None
    responded_at: Optional[datetime] = None
    requires_response: bool = False  # Whether sender expects a reply


@dataclass
class BaseMessage:
    """Base message class"""
    header: MessageHeader = field(default_factory=MessageHeader)
    message_type: MessageType = MessageType.STATUS
    payload: Any = None
    metadata: dict = field(default_factory=dict)
    
    def to_dict(self) -> dict:
        """Convert to dictionary format"""
        return {
            "header": {
                "message_id": self.header.message_id,
                "timestamp": self.header.timestamp.isoformat(),
                "source_agent_id": self.header.source_agent_id,
                "target_agent_id": self.header.target_agent_id,
                "priority": self.header.priority.value,
                "correlation_id": self.header.correlation_id,
                "reply_to": self.header.reply_to,
                "ttl": self.header.ttl,
            },
            "message_type": self.message_type.value,
            "payload": self.payload,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "BaseMessage":
        """Create message from dictionary format"""
        header_data = data.get("header", {})
        header = MessageHeader(
            message_id=header_data.get("message_id", str(uuid4())),
            timestamp=datetime.fromisoformat(header_data.get("timestamp", datetime.now().isoformat())),
            source_agent_id=header_data.get("source_agent_id", ""),
            target_agent_id=header_data.get("target_agent_id", ""),
            priority=MessagePriority(header_data.get("priority", 1)),
            correlation_id=header_data.get("correlation_id"),
            reply_to=header_data.get("reply_to"),
            ttl=header_data.get("ttl"),
        )
        return cls(
            header=header,
            message_type=MessageType(data.get("message_type", "status")),
            payload=data.get("payload"),
            metadata=data.get("metadata", {}),
        )


@dataclass
class TaskMessage(BaseMessage):
    """Task message"""
    message_type: MessageType = field(default=MessageType.TASK, init=False)
    task_id: str = field(default_factory=lambda: str(uuid4()))
    task_name: str = ""
    task_description: str = ""
    task_params: dict = field(default_factory=dict)
    deadline: Optional[datetime] = None
    dependencies: list[str] = field(default_factory=list)  # List of dependent task IDs


@dataclass
class ResultMessage(BaseMessage):
    """Result message"""
    message_type: MessageType = field(default=MessageType.RESULT, init=False)
    task_id: str = ""
    success: bool = True
    result_data: Any = None
    error_message: Optional[str] = None
    execution_time: Optional[float] = None  # Execution time (seconds)


@dataclass
class StatusMessage(BaseMessage):
    """Status message"""
    message_type: MessageType = field(default=MessageType.STATUS, init=False)
    agent_status: str = ""
    progress: Optional[float] = None  # 0.0 - 1.0
    current_task_id: Optional[str] = None
    resource_usage: dict = field(default_factory=dict)


@dataclass
class ErrorMessage(BaseMessage):
    """Error message"""
    message_type: MessageType = field(default=MessageType.ERROR, init=False)
    error_code: str = ""
    error_message: str = ""
    error_details: dict = field(default_factory=dict)
    recoverable: bool = True
    stack_trace: Optional[str] = None


@dataclass
class ControlMessage(BaseMessage):
    """Control message"""
    message_type: MessageType = field(default=MessageType.CONTROL, init=False)
    action: ControlAction = ControlAction.START
    action_params: dict = field(default_factory=dict)
    force: bool = False  # Whether to force execution


# Message factory functions
def create_task_message(
    source_id: str,
    target_id: str,
    task_name: str,
    task_description: str = "",
    task_params: dict = None,
    priority: MessagePriority = MessagePriority.NORMAL,
) -> TaskMessage:
    """Shortcut method to create a task message"""
    header = MessageHeader(
        source_agent_id=source_id,
        target_agent_id=target_id,
        priority=priority,
    )
    return TaskMessage(
        header=header,
        task_name=task_name,
        task_description=task_description,
        task_params=task_params or {},
    )


def create_result_message(
    source_id: str,
    target_id: str,
    task_id: str,
    success: bool,
    result_data: Any = None,
    error_message: str = None,
    reply_to: str = None,
) -> ResultMessage:
    """Shortcut method to create a result message"""
    header = MessageHeader(
        source_agent_id=source_id,
        target_agent_id=target_id,
        reply_to=reply_to,
    )
    return ResultMessage(
        header=header,
        task_id=task_id,
        success=success,
        result_data=result_data,
        error_message=error_message,
    )


def create_error_message(
    source_id: str,
    error_code: str,
    error_message: str,
    target_id: str = "",
    recoverable: bool = True,
) -> ErrorMessage:
    """Shortcut method to create an error message"""
    header = MessageHeader(
        source_agent_id=source_id,
        target_agent_id=target_id,
        priority=MessagePriority.HIGH,
    )
    return ErrorMessage(
        header=header,
        error_code=error_code,
        error_message=error_message,
        recoverable=recoverable,
    )


# =============================================================================
# Message Tracker - Track sent messages and their status
# =============================================================================

class MessageTracker:
    """
    Tracks message delivery and response status.
    
    Used by agents to:
    - Know if their messages were delivered/read/responded
    - Get notified when messages are overdue for response
    - Query pending messages awaiting response
    """
    
    def __init__(self):
        self._sent_messages: Dict[str, Dict] = {}  # message_id -> info
        self._response_timeout_seconds: int = 120  # Default timeout for expected responses
    
    def track_sent(
        self,
        message_id: str,
        to_agent: str,
        content: str,
        msg_type: str,
        requires_response: bool = False,
        timeout_seconds: int = None,
    ):
        """Track a sent message."""
        self._sent_messages[message_id] = {
            "to": to_agent,
            "content": content[:100],  # Truncate for storage
            "type": msg_type,
            "sent_at": datetime.now(),
            "status": MessageStatus.PENDING,
            "delivered_at": None,
            "read_at": None,
            "responded_at": None,
            "requires_response": requires_response,
            "timeout_seconds": timeout_seconds or self._response_timeout_seconds,
            "response_message_id": None,
        }
    
    def mark_delivered(self, message_id: str):
        """Mark message as delivered to recipient's inbox."""
        if message_id in self._sent_messages:
            self._sent_messages[message_id]["status"] = MessageStatus.DELIVERED
            self._sent_messages[message_id]["delivered_at"] = datetime.now()
    
    def mark_read(self, message_id: str):
        """Mark message as read by recipient."""
        if message_id in self._sent_messages:
            self._sent_messages[message_id]["status"] = MessageStatus.READ
            self._sent_messages[message_id]["read_at"] = datetime.now()
    
    def mark_responded(self, message_id: str, response_message_id: str = None):
        """Mark message as responded to."""
        if message_id in self._sent_messages:
            self._sent_messages[message_id]["status"] = MessageStatus.RESPONDED
            self._sent_messages[message_id]["responded_at"] = datetime.now()
            self._sent_messages[message_id]["response_message_id"] = response_message_id
    
    def get_status(self, message_id: str) -> Optional[Dict]:
        """Get status of a sent message."""
        if message_id not in self._sent_messages:
            return None
        
        info = self._sent_messages[message_id]
        now = datetime.now()
        
        # Check if overdue
        is_overdue = False
        if info["requires_response"] and info["status"] != MessageStatus.RESPONDED:
            elapsed = (now - info["sent_at"]).total_seconds()
            is_overdue = elapsed > info["timeout_seconds"]
        
        return {
            "message_id": message_id,
            "to": info["to"],
            "status": info["status"].value,
            "sent_at": info["sent_at"].isoformat(),
            "delivered_at": info["delivered_at"].isoformat() if info["delivered_at"] else None,
            "read_at": info["read_at"].isoformat() if info["read_at"] else None,
            "responded_at": info["responded_at"].isoformat() if info["responded_at"] else None,
            "requires_response": info["requires_response"],
            "is_overdue": is_overdue,
            "response_message_id": info["response_message_id"],
        }
    
    def get_pending_responses(self) -> List[Dict]:
        """Get all messages that expect a response but haven't received one."""
        pending = []
        now = datetime.now()
        
        for msg_id, info in self._sent_messages.items():
            if info["requires_response"] and info["status"] != MessageStatus.RESPONDED:
                elapsed = (now - info["sent_at"]).total_seconds()
                pending.append({
                    "message_id": msg_id,
                    "to": info["to"],
                    "type": info["type"],
                    "content_preview": info["content"],
                    "status": info["status"].value,
                    "elapsed_seconds": int(elapsed),
                    "is_overdue": elapsed > info["timeout_seconds"],
                    "timeout_seconds": info["timeout_seconds"],
                })
        
        # Sort by most overdue first
        pending.sort(key=lambda x: -x["elapsed_seconds"])
        return pending
    
    def get_overdue_messages(self) -> List[Dict]:
        """Get messages that are overdue for response."""
        return [m for m in self.get_pending_responses() if m["is_overdue"]]
    
    def cleanup_old(self, max_age_hours: int = 2):
        """Remove tracking for old messages."""
        cutoff = datetime.now()
        to_remove = []
        
        for msg_id, info in self._sent_messages.items():
            age_hours = (cutoff - info["sent_at"]).total_seconds() / 3600
            if age_hours > max_age_hours:
                to_remove.append(msg_id)
        
        for msg_id in to_remove:
            del self._sent_messages[msg_id]
