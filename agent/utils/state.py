"""
State Management Module - Defines Agent state and lifecycle

Supports:
- AgentState: Agent state enumeration
- TaskState: Task state enumeration
- StateManager: State manager
- StateTransition: State transition record
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Optional
from uuid import uuid4
import threading
from collections import deque


class AgentState(Enum):
    """Agent lifecycle state"""
    INITIALIZING = "initializing"   # Initializing
    IDLE = "idle"                   # Idle
    RUNNING = "running"             # Running
    PAUSED = "paused"               # Paused
    STOPPING = "stopping"           # Stopping
    STOPPED = "stopped"             # Stopped
    ERROR = "error"                 # Error state
    RECOVERING = "recovering"       # Recovering


class TaskState(Enum):
    """Task state"""
    PENDING = "pending"             # Pending
    QUEUED = "queued"               # Queued
    RUNNING = "running"             # Running
    COMPLETED = "completed"         # Completed
    FAILED = "failed"               # Failed
    CANCELLED = "cancelled"         # Cancelled
    TIMEOUT = "timeout"             # Timeout
    RETRYING = "retrying"           # Retrying


# Valid state transition mapping
VALID_AGENT_TRANSITIONS: dict[AgentState, list[AgentState]] = {
    AgentState.INITIALIZING: [AgentState.IDLE, AgentState.ERROR],
    AgentState.IDLE: [AgentState.RUNNING, AgentState.STOPPING, AgentState.ERROR],
    AgentState.RUNNING: [AgentState.IDLE, AgentState.PAUSED, AgentState.STOPPING, AgentState.ERROR],
    AgentState.PAUSED: [AgentState.RUNNING, AgentState.STOPPING, AgentState.ERROR],
    AgentState.STOPPING: [AgentState.STOPPED, AgentState.ERROR],
    AgentState.STOPPED: [AgentState.INITIALIZING],
    AgentState.ERROR: [AgentState.RECOVERING, AgentState.STOPPED],
    AgentState.RECOVERING: [AgentState.IDLE, AgentState.ERROR, AgentState.STOPPED],
}

VALID_TASK_TRANSITIONS: dict[TaskState, list[TaskState]] = {
    TaskState.PENDING: [TaskState.QUEUED, TaskState.CANCELLED],
    TaskState.QUEUED: [TaskState.RUNNING, TaskState.CANCELLED],
    TaskState.RUNNING: [TaskState.COMPLETED, TaskState.FAILED, TaskState.TIMEOUT, TaskState.CANCELLED],
    TaskState.FAILED: [TaskState.RETRYING, TaskState.CANCELLED],
    TaskState.RETRYING: [TaskState.RUNNING, TaskState.FAILED, TaskState.CANCELLED],
    TaskState.TIMEOUT: [TaskState.RETRYING, TaskState.CANCELLED],
    TaskState.COMPLETED: [],  # Terminal state
    TaskState.CANCELLED: [],  # Terminal state
}


@dataclass
class StateTransition:
    """State transition record"""
    transition_id: str = field(default_factory=lambda: str(uuid4()))
    timestamp: datetime = field(default_factory=datetime.now)
    from_state: str = ""
    to_state: str = ""
    trigger: str = ""  # Trigger reason
    metadata: dict = field(default_factory=dict)


@dataclass
class TaskContext:
    """Task execution context"""
    task_id: str = ""
    state: TaskState = TaskState.PENDING
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    retry_count: int = 0
    max_retries: int = 3
    error_message: Optional[str] = None
    result: Any = None
    metadata: dict = field(default_factory=dict)
    
    def is_terminal(self) -> bool:
        """Check if in terminal state"""
        return self.state in [TaskState.COMPLETED, TaskState.CANCELLED]
    
    def can_retry(self) -> bool:
        """Check if can retry"""
        return self.retry_count < self.max_retries and self.state in [TaskState.FAILED, TaskState.TIMEOUT]
    
    def duration(self) -> Optional[float]:
        """Calculate execution duration (seconds)"""
        if self.started_at is None:
            return None
        end_time = self.completed_at or datetime.now()
        return (end_time - self.started_at).total_seconds()


class StateManager:
    """
    Agent State Manager
    
    - Manages Agent and task states
    - Validates state transition validity
    - Records state transition history
    - Supports state change callbacks
    """
    
    def __init__(
        self,
        initial_state: AgentState = AgentState.INITIALIZING,
        history_size: int = 100,
    ):
        self._state = initial_state
        self._lock = threading.RLock()
        self._history: deque[StateTransition] = deque(maxlen=history_size)
        self._tasks: dict[str, TaskContext] = {}
        self._callbacks: list[Callable[[AgentState, AgentState], None]] = []
        
        # Record initial state
        self._record_transition(None, initial_state, "initialization")
    
    @property
    def state(self) -> AgentState:
        """Get current state"""
        with self._lock:
            return self._state
    
    @property
    def is_running(self) -> bool:
        """Check if running"""
        return self._state == AgentState.RUNNING
    
    @property
    def is_idle(self) -> bool:
        """Check if idle"""
        return self._state == AgentState.IDLE
    
    @property
    def can_accept_tasks(self) -> bool:
        """Check if can accept new tasks"""
        return self._state in [AgentState.IDLE, AgentState.RUNNING]
    
    def transition_to(
        self,
        new_state: AgentState,
        trigger: str = "",
        force: bool = False,
    ) -> bool:
        """
        Transition to new state
        
        Args:
            new_state: Target state
            trigger: Trigger reason
            force: Whether to force transition (skip validity check)
            
        Returns:
            Whether transition was successful
        """
        with self._lock:
            old_state = self._state
            
            # Check transition validity
            if not force:
                valid_targets = VALID_AGENT_TRANSITIONS.get(old_state, [])
                if new_state not in valid_targets:
                    return False
            
            self._state = new_state
            self._record_transition(old_state, new_state, trigger)
            
            # Trigger callbacks
            for callback in self._callbacks:
                try:
                    callback(old_state, new_state)
                except Exception:
                    pass  # Callback failure doesn't affect state transition
            
            return True
    
    def _record_transition(
        self,
        from_state: Optional[AgentState],
        to_state: AgentState,
        trigger: str,
    ) -> None:
        """Record state transition"""
        transition = StateTransition(
            from_state=from_state.value if from_state else "",
            to_state=to_state.value,
            trigger=trigger,
        )
        self._history.append(transition)
    
    def add_callback(self, callback: Callable[[AgentState, AgentState], None]) -> None:
        """Add state change callback"""
        self._callbacks.append(callback)
    
    def remove_callback(self, callback: Callable[[AgentState, AgentState], None]) -> None:
        """Remove state change callback"""
        if callback in self._callbacks:
            self._callbacks.remove(callback)
    
    def get_history(self, limit: int = 10) -> list[StateTransition]:
        """Get state transition history"""
        return list(self._history)[-limit:]
    
    # Task state management
    def create_task(
        self,
        task_id: str,
        max_retries: int = 3,
        metadata: dict = None,
    ) -> TaskContext:
        """Create new task"""
        with self._lock:
            context = TaskContext(
                task_id=task_id,
                max_retries=max_retries,
                metadata=metadata or {},
            )
            self._tasks[task_id] = context
            return context
    
    def get_task(self, task_id: str) -> Optional[TaskContext]:
        """Get task context"""
        return self._tasks.get(task_id)
    
    def update_task_state(
        self,
        task_id: str,
        new_state: TaskState,
        error_message: str = None,
        result: Any = None,
    ) -> bool:
        """Update task state"""
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return False
            
            old_state = task.state
            
            # Check transition validity
            valid_targets = VALID_TASK_TRANSITIONS.get(old_state, [])
            if new_state not in valid_targets:
                return False
            
            task.state = new_state
            
            if new_state == TaskState.RUNNING and task.started_at is None:
                task.started_at = datetime.now()
            
            if new_state in [TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED, TaskState.TIMEOUT]:
                task.completed_at = datetime.now()
            
            if new_state == TaskState.RETRYING:
                task.retry_count += 1
            
            if error_message:
                task.error_message = error_message
            
            if result is not None:
                task.result = result
            
            return True
    
    def get_active_tasks(self) -> list[TaskContext]:
        """Get all active tasks"""
        return [
            task for task in self._tasks.values()
            if task.state in [TaskState.PENDING, TaskState.QUEUED, TaskState.RUNNING, TaskState.RETRYING]
        ]
    
    def get_completed_tasks(self) -> list[TaskContext]:
        """Get all completed tasks"""
        return [
            task for task in self._tasks.values()
            if task.state == TaskState.COMPLETED
        ]
    
    def cleanup_tasks(self, keep_recent: int = 100) -> int:
        """Clean up completed tasks, keep recent N"""
        with self._lock:
            terminal_tasks = [
                task for task in self._tasks.values()
                if task.is_terminal()
            ]
            
            if len(terminal_tasks) <= keep_recent:
                return 0
            
            # Sort by completion time
            terminal_tasks.sort(key=lambda t: t.completed_at or datetime.min)
            
            # Remove oldest
            to_remove = terminal_tasks[:-keep_recent]
            for task in to_remove:
                del self._tasks[task.task_id]
            
            return len(to_remove)
    
    def to_dict(self) -> dict:
        """Export state information"""
        return {
            "current_state": self._state.value,
            "active_tasks_count": len(self.get_active_tasks()),
            "completed_tasks_count": len(self.get_completed_tasks()),
            "recent_transitions": [
                {
                    "from": t.from_state,
                    "to": t.to_state,
                    "trigger": t.trigger,
                    "timestamp": t.timestamp.isoformat(),
                }
                for t in self.get_history(5)
            ],
        }


class AgentContext:
    """
    Agent Runtime Context
    
    Contains all context information needed for agent execution
    """
    
    def __init__(self, agent_id: str):
        self.agent_id = agent_id
        self.state_manager = StateManager()
        self.variables: dict[str, Any] = {}
        self.shared_memory: dict[str, Any] = {}
        self._lock = threading.RLock()
    
    def set_variable(self, key: str, value: Any) -> None:
        """Set context variable"""
        with self._lock:
            self.variables[key] = value
    
    def get_variable(self, key: str, default: Any = None) -> Any:
        """Get context variable"""
        return self.variables.get(key, default)
    
    def delete_variable(self, key: str) -> bool:
        """Delete context variable"""
        with self._lock:
            if key in self.variables:
                del self.variables[key]
                return True
            return False
    
    def clear_variables(self) -> None:
        """Clear all variables"""
        with self._lock:
            self.variables.clear()
