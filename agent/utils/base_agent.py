"""
Agent Base Module - Defines core structure and behavior of Agents

Provides:
- BaseAgent: Base class for all Agents
- AgentCapability: Agent capability definition
- AgentRole: Agent role definition

Enhanced Features (OpenHands-inspired):
- Stuck detection to break infinite loops
- Retry mechanism with exponential backoff
- Structured debug logging for observability
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Optional, TypeVar
from uuid import uuid4
import asyncio
import logging

from .config import AgentConfig, LogLevel
from .state import AgentState, StateManager, TaskContext, TaskState, AgentContext
from .message import (
    BaseMessage, 
    TaskMessage, 
    ResultMessage, 
    StatusMessage,
    ErrorMessage,
    ControlMessage,
    ControlAction,
    MessageType,
    MessagePriority,
    create_result_message,
    create_error_message,
)
from .tool import BaseTool, ToolRegistry, ToolResult


class AgentRole(Enum):
    """Agent role types"""
    COORDINATOR = "coordinator"   # Coordinator - manages other agents
    WORKER = "worker"             # Worker - executes specific tasks
    SUPERVISOR = "supervisor"     # Supervisor - monitors and validates
    SPECIALIST = "specialist"     # Specialist - specific domain
    ASSISTANT = "assistant"       # Assistant - auxiliary work


@dataclass
class AgentCapability:
    """Agent capability definition"""
    name: str
    description: str = ""
    enabled: bool = True
    config: dict = field(default_factory=dict)


@dataclass
class AgentMetrics:
    """Agent metrics statistics"""
    tasks_received: int = 0
    tasks_completed: int = 0
    tasks_failed: int = 0
    total_execution_time: float = 0.0  # seconds
    average_execution_time: float = 0.0
    last_active: Optional[datetime] = None
    errors_count: int = 0
    # New metrics for enhanced features
    total_retries: int = 0
    stuck_detections: int = 0
    llm_calls: int = 0
    tool_calls: int = 0
    
    def record_task_completion(self, execution_time: float, success: bool) -> None:
        """Record task completion"""
        self.last_active = datetime.now()
        if success:
            self.tasks_completed += 1
        else:
            self.tasks_failed += 1
        
        self.total_execution_time += execution_time
        total_tasks = self.tasks_completed + self.tasks_failed
        if total_tasks > 0:
            self.average_execution_time = self.total_execution_time / total_tasks
    
    def to_dict(self) -> dict:
        return {
            "tasks_received": self.tasks_received,
            "tasks_completed": self.tasks_completed,
            "tasks_failed": self.tasks_failed,
            "total_execution_time": self.total_execution_time,
            "average_execution_time": self.average_execution_time,
            "last_active": self.last_active.isoformat() if self.last_active else None,
            "errors_count": self.errors_count,
            "success_rate": self.tasks_completed / max(1, self.tasks_completed + self.tasks_failed),
            "total_retries": self.total_retries,
            "stuck_detections": self.stuck_detections,
            "llm_calls": self.llm_calls,
            "tool_calls": self.tool_calls,
        }


class BaseAgent(ABC):
    """
    Agent Base Class
    
    All Agents must inherit this class and implement the process_task method
    
    Lifecycle:
    1. __init__: Create instance
    2. initialize: Initialize resources
    3. start: Start running
    4. process_task: Process tasks (loop)
    5. stop: Stop running
    6. cleanup: Clean up resources
    
    Enhanced Features:
    - Stuck detection: Automatically detects when agent is stuck in loops
    - Retry mechanism: Exponential backoff retry for LLM and tool calls
    - Debug logging: Structured logging for prompts, responses, and tool calls
    
    Usage example:
        class MyAgent(BaseAgent):
            async def process_task(self, task: TaskMessage) -> ResultMessage:
                # Process task with stuck detection
                if self.check_if_stuck():
                    self.inject_loop_breaker()
                
                result = do_something(task.payload)
                return create_result_message(
                    self.agent_id, task.header.source_agent_id,
                    task.task_id, True, result
                )
    """
    
    def __init__(
        self,
        config: AgentConfig,
        role: AgentRole = AgentRole.WORKER,
        enable_stuck_detection: bool = True,
        enable_debug_logging: bool = False,
    ):
        # Basic attributes
        self._config = config
        self._role = role
        self._agent_id = config.agent_id or str(uuid4())
        self._name = config.agent_name or f"Agent-{self._agent_id[:8]}"
        
        # State management
        self._context = AgentContext(self._agent_id)
        self._state_manager = self._context.state_manager
        
        # Tool registry
        self._tools = ToolRegistry()
        
        # Capability list
        self._capabilities: list[AgentCapability] = []
        
        # Metrics
        self._metrics = AgentMetrics()
        
        # Message queue
        self._message_queue: asyncio.Queue[BaseMessage] = asyncio.Queue(
            maxsize=config.execution.queue_size
        )
        
        # Callbacks
        self._on_message_callbacks: list[Callable[[BaseMessage], None]] = []
        self._on_state_change_callbacks: list[Callable[[AgentState, AgentState], None]] = []
        
        # Internal control
        self._running = False
        self._main_task: Optional[asyncio.Task] = None
        self._worker_tasks: list[asyncio.Task] = []
        
        # Logger
        self._logger = self._setup_logger()
        
        # ===== Enhanced Features =====
        
        # Stuck Detection
        self._enable_stuck_detection = enable_stuck_detection
        self._stuck_detector = None
        if enable_stuck_detection:
            self._setup_stuck_detector()
        
        # Debug Logging
        self._enable_debug_logging = enable_debug_logging
        self._debug_logger = None
        if enable_debug_logging:
            self._setup_debug_logging()
        
        # Retry configuration. 2 (not 3): the LLM client below this layer
        # already retries each call up to 3× with backoff, so 3×3=9 total
        # attempts per logical call burned quota on persistent failures
        # (harness-engineering guidance: cap agent-layer retries ~2).
        self._retry_config = {
            "max_retries": 2,
            "min_wait": 1.0,
            "max_wait": 60.0,
            "multiplier": 2.0,
        }
    
    # ===== Stuck Detection =====
    
    def _setup_stuck_detector(self) -> None:
        """Initialize stuck detector."""
        from .stuck_detector import StuckDetector
        self._stuck_detector = StuckDetector(
            max_history=50,
            min_loop_detection=3,
        )
    
    def record_action(self, action: str) -> None:
        """Record an action for stuck detection."""
        if self._stuck_detector and hasattr(self._stuck_detector, 'record_action'):
            self._stuck_detector.record_action(action)
    
    def record_observation(self, observation: str) -> None:
        """Record an observation for stuck detection."""
        if self._stuck_detector:
            self._stuck_detector.add_observation(observation[:500])
    
    def record_error(self, error: str) -> None:
        """Record an error for stuck detection."""
        if self._stuck_detector:
            self._stuck_detector.add_error(error)
    
    def check_if_stuck(self) -> bool:
        """
        Check if agent is stuck in a loop.
        
        Returns:
            True if stuck pattern detected
        """
        if not self._stuck_detector:
            return False
        
        if self._stuck_detector.is_stuck():
            self._metrics.stuck_detections += 1
            analysis = self._stuck_detector.get_analysis()
            self._logger.warning(
                f"Stuck detected: {analysis.loop_type} "
                f"(repeated {analysis.loop_repeat_times} times)"
            )
            return True
        return False
    
    def get_loop_breaker_prompt(self) -> str:
        """Get a prompt to help break detected loops."""
        if self._stuck_detector:
            return self._stuck_detector.get_loop_breaker_prompt()
        return ""
    
    def clear_stuck_history(self) -> None:
        """Clear stuck detection history."""
        if self._stuck_detector:
            self._stuck_detector.clear()
    
    # ===== Debug Logging =====
    
    def _setup_debug_logging(self) -> None:
        """Initialize debug logging.

        The log path is CWD-relative at __init__ time because the workspace
        isn't known yet. Subclasses that DO know their workspace (e.g.
        ``EnvGenAgent``) should call :meth:`_relocate_debug_log_to` once
        the workspace is bound so the per-project Action History UI sees
        this run's tool calls instead of stale ones from a host-wide path.
        """
        from .debug import StructuredLogger
        from pathlib import Path

        log_dir = Path(f".agent_logs/{self._name}")
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"
        self._debug_logger = StructuredLogger(str(log_file))

    def _relocate_debug_log_to(self, log_root: "Path") -> None:
        """Move the debug log under ``<log_root>/<agent_name>/<ts>.jsonl``.

        Used by subclasses (``EnvGenAgent``) once the workspace is known.
        Without this the agent writes to a CWD-relative ``.agent_logs/``,
        and the monitor — which resolves the dir per-workspace — silently
        falls back to a host-wide path containing UNRELATED stale runs.

        Safe to call multiple times; closes the previous logger and
        deletes the prior log file if it's empty (no orphan files
        accumulating in the launch CWD on every agent boot).
        """
        from .debug import StructuredLogger
        from pathlib import Path

        if not self._enable_debug_logging:
            return
        try:
            log_dir = Path(log_root) / self._name
            log_dir.mkdir(parents=True, exist_ok=True)
            log_file = log_dir / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"
            previous = self._debug_logger
            # Capture the prior log's on-disk path before we replace it so
            # we can delete the file if it's still empty (relocation
            # happens before any LLM I/O is logged, so the original file
            # — created by ``_setup_debug_logging`` at CWD-relative
            # ``.agent_logs/<name>/<ts>.jsonl`` — usually has zero bytes
            # and is pure pollution).
            prev_path: Optional[Path] = None
            try:
                if previous is not None:
                    raw = getattr(previous, "path", None) or getattr(previous, "_path", None)
                    if raw:
                        prev_path = Path(str(raw))
            except Exception:
                prev_path = None

            self._debug_logger = StructuredLogger(str(log_file))

            # Best-effort close of the prior handle so we don't leak a fd.
            close = getattr(previous, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass

            # Remove the orphan file if it never received any writes.
            if prev_path is not None and prev_path.exists():
                try:
                    if prev_path.stat().st_size == 0:
                        prev_path.unlink()
                        # Also remove the parent dir if it's now empty —
                        # don't leak empty per-agent dirs in the launch CWD.
                        parent = prev_path.parent
                        try:
                            if parent.exists() and not any(parent.iterdir()):
                                parent.rmdir()
                        except Exception:
                            pass
                except Exception:
                    pass
        except Exception:
            # Never fail agent boot because of log relocation.
            pass
    
    def log_prompt(self, prompt: str, model: str = "") -> None:
        """Log an LLM prompt."""
        if self._debug_logger:
            self._debug_logger.log("prompt", prompt[:2000], {"model": model})
        self._metrics.llm_calls += 1
    
    def log_response(self, response: str, tokens: int = 0) -> None:
        """Log an LLM response."""
        if self._debug_logger:
            self._debug_logger.log("response", response[:2000], {"tokens": tokens})
    
    def log_tool_call(self, tool_name: str, args: dict, result: Any) -> None:
        """Log a tool call."""
        if self._debug_logger:
            self._debug_logger.log(
                "tool_call",
                f"{tool_name}({args})",
                {
                    "result": str(result)[:500],
                    # Persist the AUTHORITATIVE success flag. ToolResult.__str__ drops it
                    # (success -> str(data), which may itself contain words like "errors"),
                    # so without this, downstream readers (hub_reader/Env Forge drawer,
                    # live_monitor) must guess pass/fail from the result text — yielding a
                    # false ✗ on e.g. a passing lint whose data is {"errors": [], ...}.
                    "ok": bool(getattr(result, "success", True)),
                    "error": getattr(result, "error_message", None),
                },
            )
        self._metrics.tool_calls += 1
        
        # Also record for stuck detection
        self.record_action(f"{tool_name}({list(args.keys())})")
        if hasattr(result, 'success') and result.success:
            self.record_observation(str(result.data)[:200] if result.data else "OK")
        elif hasattr(result, 'error_message'):
            self.record_error(result.error_message or "")
    
    def log_event(self, event_type: str, content: str, metadata: dict = None) -> None:
        """Log a custom event."""
        if self._debug_logger:
            self._debug_logger.log(event_type, content, metadata or {})
    
    # ===== Retry Mechanism =====
    
    def configure_retry(
        self,
        max_retries: int = 2,
        min_wait: float = 1.0,
        max_wait: float = 60.0,
        multiplier: float = 2.0,
    ) -> None:
        """Configure retry behavior."""
        self._retry_config = {
            "max_retries": max_retries,
            "min_wait": min_wait,
            "max_wait": max_wait,
            "multiplier": multiplier,
        }
    
    async def call_with_retry(
        self,
        func: Callable,
        *args,
        max_retries: int = None,
        **kwargs,
    ) -> Any:
        """
        Call a function with retry on failure.
        
        Args:
            func: Async function to call
            *args: Positional arguments
            max_retries: Override default max retries
            **kwargs: Keyword arguments
            
        Returns:
            Function result
            
        Raises:
            Last exception if all retries fail
        """
        max_tries = max_retries or self._retry_config["max_retries"]
        last_error = None
        
        for attempt in range(max_tries):
            try:
                if asyncio.iscoroutinefunction(func):
                    return await func(*args, **kwargs)
                else:
                    return func(*args, **kwargs)
            except Exception as e:
                last_error = e
                self._metrics.total_retries += 1
                
                if attempt < max_tries - 1:
                    wait_time = min(
                        self._retry_config["max_wait"],
                        self._retry_config["min_wait"] * (self._retry_config["multiplier"] ** attempt)
                    )
                    self._logger.warning(
                        f"Retry {attempt + 1}/{max_tries} after error: {e}. "
                        f"Waiting {wait_time:.1f}s"
                    )
                    await asyncio.sleep(wait_time)
        
        raise last_error
    
    async def call_tool_with_retry(
        self,
        tool_name: str,
        max_retries: int = None,
        **kwargs,
    ) -> ToolResult:
        """
        Call a tool with retry on failure.
        
        Args:
            tool_name: Name of the tool
            max_retries: Override default max retries
            **kwargs: Tool arguments
            
        Returns:
            ToolResult
        """
        tool = self._tools.get(tool_name)
        if not tool:
            return ToolResult.fail(f"Tool not found: {tool_name}")
        
        max_tries = max_retries or self._retry_config["max_retries"]
        last_error = None
        
        for attempt in range(max_tries):
            try:
                result = await tool(**kwargs)
                self.log_tool_call(tool_name, kwargs, result)
                return result
            except Exception as e:
                last_error = e
                self._metrics.total_retries += 1
                
                if attempt < max_tries - 1:
                    wait_time = min(
                        self._retry_config["max_wait"],
                        self._retry_config["min_wait"] * (self._retry_config["multiplier"] ** attempt)
                    )
                    self._logger.warning(
                        f"Tool {tool_name} retry {attempt + 1}/{max_tries}: {e}"
                    )
                    await asyncio.sleep(wait_time)
        
        return ToolResult.fail(f"Tool failed after {max_tries} attempts: {last_error}")
    
    # ===== Properties =====
    
    @property
    def agent_id(self) -> str:
        return self._agent_id
    
    @property
    def name(self) -> str:
        return self._name
    
    @property
    def role(self) -> AgentRole:
        return self._role
    
    @property
    def config(self) -> AgentConfig:
        return self._config
    
    @property
    def state(self) -> AgentState:
        return self._state_manager.state
    
    @property
    def is_running(self) -> bool:
        return self._running and self._state_manager.is_running
    
    @property
    def context(self) -> AgentContext:
        return self._context
    
    @property
    def tools(self) -> ToolRegistry:
        return self._tools
    
    @property
    def metrics(self) -> AgentMetrics:
        return self._metrics
    
    @property
    def capabilities(self) -> list[AgentCapability]:
        return self._capabilities
    
    # ===== Lifecycle Methods =====
    
    async def initialize(self) -> bool:
        """
        Initialize Agent
        
        Subclasses can override this method to perform custom initialization
        """
        self._logger.info(f"Initializing agent: {self._name}")
        
        try:
            # Register built-in tools
            await self._register_builtin_tools()
            
            # Subclass custom initialization
            await self.on_initialize()
            
            # Transition to IDLE state
            self._state_manager.transition_to(AgentState.IDLE, "initialization_complete")
            
            self._logger.info(f"Agent {self._name} initialized successfully")
            return True
            
        except Exception as e:
            self._logger.error(f"Failed to initialize agent: {e}")
            self._state_manager.transition_to(AgentState.ERROR, f"init_error: {e}")
            return False
    
    async def start(self) -> bool:
        """Start Agent"""
        if self._running:
            self._logger.warning("Agent is already running")
            return False
        
        if self.state != AgentState.IDLE:
            self._logger.warning(f"Cannot start agent in state: {self.state}")
            return False
        
        self._logger.info(f"Starting agent: {self._name}")
        
        try:
            self._running = True
            self._state_manager.transition_to(AgentState.RUNNING, "start_command")
            
            # Start main loop
            self._main_task = asyncio.create_task(self._main_loop())
            
            # Start worker threads
            for i in range(self._config.execution.max_concurrent_tasks):
                task = asyncio.create_task(self._worker_loop(i))
                self._worker_tasks.append(task)
            
            await self.on_start()
            
            self._logger.info(f"Agent {self._name} started successfully")
            return True
            
        except Exception as e:
            self._logger.error(f"Failed to start agent: {e}")
            self._running = False
            self._state_manager.transition_to(AgentState.ERROR, f"start_error: {e}")
            return False
    
    async def stop(self, force: bool = False) -> bool:
        """Stop Agent"""
        if not self._running:
            return True
        
        self._logger.info(f"Stopping agent: {self._name}")
        self._state_manager.transition_to(AgentState.STOPPING, "stop_command")
        
        self._running = False
        
        # Wait for tasks to complete
        if not force:
            # Give running tasks some time to complete
            await asyncio.sleep(0.5)
        
        # Cancel all worker tasks
        for task in self._worker_tasks:
            if not task.done():
                task.cancel()
        
        if self._main_task and not self._main_task.done():
            self._main_task.cancel()
        
        # Wait for task cancellation to complete
        await asyncio.gather(*self._worker_tasks, self._main_task, return_exceptions=True)
        
        self._worker_tasks.clear()
        self._main_task = None
        
        await self.on_stop()
        
        self._state_manager.transition_to(AgentState.STOPPED, "stop_complete")
        self._logger.info(f"Agent {self._name} stopped")
        
        return True
    
    async def cleanup(self) -> None:
        """Clean up resources"""
        self._logger.info(f"Cleaning up agent: {self._name}")
        
        # Ensure stopped
        if self._running:
            await self.stop(force=True)
        
        # Subclass cleanup
        await self.on_cleanup()
        
        # Clear context
        self._context.clear_variables()
        
        self._logger.info(f"Agent {self._name} cleaned up")
    
    # ===== Message Processing =====
    
    async def send_message(self, message: BaseMessage) -> None:
        """Send message to queue"""
        message.header.source_agent_id = self._agent_id
        await self._message_queue.put(message)
        self._logger.debug(f"Message queued: {message.message_type.value}")
    
    async def receive_message(self, message: BaseMessage) -> None:
        """Receive external message"""
        self._logger.debug(f"Received message: {message.message_type.value}")
        
        # Trigger callbacks
        for callback in self._on_message_callbacks:
            try:
                callback(message)
            except Exception as e:
                self._logger.error(f"Message callback error: {e}")
        
        # Handle control messages
        if isinstance(message, ControlMessage):
            await self._handle_control_message(message)
        else:
            await self._message_queue.put(message)
    
    async def _handle_control_message(self, message: ControlMessage) -> None:
        """Handle control message"""
        action = message.action
        
        if action == ControlAction.START:
            await self.start()
        elif action == ControlAction.STOP:
            await self.stop(force=message.force)
        elif action == ControlAction.PAUSE:
            self._state_manager.transition_to(AgentState.PAUSED, "pause_command")
        elif action == ControlAction.RESUME:
            self._state_manager.transition_to(AgentState.RUNNING, "resume_command")
        elif action == ControlAction.SHUTDOWN:
            await self.cleanup()
    
    # ===== Core Processing Logic =====
    
    async def _main_loop(self) -> None:
        """Main message loop"""
        while self._running:
            try:
                # Check if paused
                if self.state == AgentState.PAUSED:
                    await asyncio.sleep(0.1)
                    continue
                
                # Get message from queue
                try:
                    message = await asyncio.wait_for(
                        self._message_queue.get(),
                        timeout=1.0
                    )
                except asyncio.TimeoutError:
                    continue
                
                # Process message
                await self._dispatch_message(message)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                self._logger.error(f"Error in main loop: {e}")
                self._metrics.errors_count += 1
    
    async def _worker_loop(self, worker_id: int) -> None:
        """Worker loop"""
        self._logger.debug(f"Worker {worker_id} started")
        
        while self._running:
            try:
                await asyncio.sleep(0.1)  # Prevent busy loop
            except asyncio.CancelledError:
                break
        
        self._logger.debug(f"Worker {worker_id} stopped")
    
    async def _dispatch_message(self, message: BaseMessage) -> None:
        """Dispatch message"""
        if isinstance(message, TaskMessage):
            await self._handle_task_message(message)
        elif isinstance(message, ResultMessage):
            await self.on_result_received(message)
        elif isinstance(message, StatusMessage):
            await self.on_status_received(message)
        elif isinstance(message, ErrorMessage):
            await self.on_error_received(message)
    
    async def _handle_task_message(self, task: TaskMessage) -> None:
        """Handle task message"""
        self._metrics.tasks_received += 1
        task_id = task.task_id
        
        # Create task context
        task_context = self._state_manager.create_task(
            task_id,
            max_retries=self._config.execution.max_retries,
        )
        
        self._logger.info(f"Processing task: {task.task_name} ({task_id})")
        
        start_time = datetime.now()
        self._state_manager.update_task_state(task_id, TaskState.RUNNING)
        
        try:
            # Call subclass implementation
            result = await asyncio.wait_for(
                self.process_task(task),
                timeout=self._config.execution.task_timeout
            )
            
            execution_time = (datetime.now() - start_time).total_seconds()
            task_succeeded = bool(getattr(result, "success", True))
            
            # Always send result back to caller if available.
            if result:
                result.execution_time = execution_time
                await self.on_task_completed(task, result)

            if task_succeeded:
                self._state_manager.update_task_state(
                    task_id,
                    TaskState.COMPLETED,
                    result=result.result_data if result else None
                )
                self._metrics.record_task_completion(execution_time, True)
                self._logger.info(f"Task completed: {task_id} ({execution_time:.2f}s)")
            else:
                error_message = getattr(result, "error_message", None) or "Task returned unsuccessful result"
                self._state_manager.update_task_state(
                    task_id,
                    TaskState.FAILED,
                    error_message=error_message
                )
                self._metrics.record_task_completion(execution_time, False)
                self._logger.warning(f"Task reported failure: {task_id} - {error_message}")
                await self._handle_task_failure(task, task_context, error_message)
            
        except asyncio.TimeoutError:
            self._state_manager.update_task_state(
                task_id,
                TaskState.TIMEOUT,
                error_message="Task execution timeout"
            )
            self._metrics.record_task_completion(
                (datetime.now() - start_time).total_seconds(), 
                False
            )
            self._logger.warning(f"Task timeout: {task_id}")
            
            # Check if retry
            await self._handle_task_failure(task, task_context, "Timeout")
            
        except Exception as e:
            self._state_manager.update_task_state(
                task_id,
                TaskState.FAILED,
                error_message=str(e)
            )
            self._metrics.record_task_completion(
                (datetime.now() - start_time).total_seconds(),
                False
            )
            self._logger.error(f"Task failed: {task_id} - {e}")
            
            await self._handle_task_failure(task, task_context, str(e))
    
    async def _handle_task_failure(
        self,
        task: TaskMessage,
        task_context: TaskContext,
        error_message: str,
    ) -> None:
        """Handle task failure"""
        if task_context.can_retry() and self._config.execution.retry_on_failure:
            self._logger.info(f"Retrying task: {task.task_id} (attempt {task_context.retry_count + 1})")
            self._state_manager.update_task_state(task.task_id, TaskState.RETRYING)
            
            # Backoff delay
            delay = self._config.execution.retry_backoff ** task_context.retry_count
            await asyncio.sleep(delay)
            
            # Re-queue
            await self._message_queue.put(task)
        else:
            # Send error message
            await self.on_task_failed(task, error_message)
    
    # ===== Tool Management =====
    
    def register_tool(self, tool: BaseTool) -> None:
        """Register tool"""
        self._tools.register(tool)
        self._logger.debug(f"Tool registered: {tool.name}")
    
    def unregister_tool(self, name: str) -> bool:
        """Unregister tool"""
        result = self._tools.unregister(name)
        if result:
            self._logger.debug(f"Tool unregistered: {name}")
        return result
    
    async def call_tool(self, name: str, **kwargs) -> ToolResult:
        """Call tool"""
        tool = self._tools.get(name)
        if not tool:
            return ToolResult.fail(f"Tool not found: {name}")
        
        self._logger.debug(f"Calling tool: {name}")
        result = await tool(**kwargs)
        self.log_tool_call(name, kwargs, result)
        return result
    
    async def _register_builtin_tools(self) -> None:
        """Register built-in tools - subclasses can override"""
        pass
    
    # ===== Capability Management =====
    
    def add_capability(self, capability: AgentCapability) -> None:
        """Add capability"""
        self._capabilities.append(capability)
    
    def has_capability(self, name: str) -> bool:
        """Check if has capability"""
        return any(c.name == name and c.enabled for c in self._capabilities)
    
    # ===== Callback Management =====
    
    def on_message(self, callback: Callable[[BaseMessage], None]) -> None:
        """Register message callback"""
        self._on_message_callbacks.append(callback)
    
    def on_state_change(self, callback: Callable[[AgentState, AgentState], None]) -> None:
        """Register state change callback"""
        self._on_state_change_callbacks.append(callback)
        self._state_manager.add_callback(callback)
    
    # ===== Hook Methods (subclasses can override) =====
    
    async def on_initialize(self) -> None:
        """Initialization hook"""
        pass
    
    async def on_start(self) -> None:
        """Start hook"""
        pass
    
    async def on_stop(self) -> None:
        """Stop hook"""
        pass
    
    async def on_cleanup(self) -> None:
        """Cleanup hook"""
        pass
    
    async def on_task_completed(self, task: TaskMessage, result: ResultMessage) -> None:
        """Task completed hook"""
        pass
    
    async def on_task_failed(self, task: TaskMessage, error: str) -> None:
        """Task failed hook"""
        pass
    
    async def on_result_received(self, result: ResultMessage) -> None:
        """Result received hook"""
        pass
    
    async def on_status_received(self, status: StatusMessage) -> None:
        """Status received hook"""
        pass
    
    async def on_error_received(self, error: ErrorMessage) -> None:
        """Error received hook"""
        pass
    
    # ===== Abstract Methods (subclasses must implement) =====
    
    @abstractmethod
    async def process_task(self, task: TaskMessage) -> ResultMessage:
        """
        Process task
        
        This is the core method of Agent, subclasses must implement
        
        Args:
            task: Task message
            
        Returns:
            Result message
        """
        pass
    
    # ===== Helper Methods =====
    
    def _setup_logger(self) -> logging.Logger:
        """Setup logger"""
        logger = logging.getLogger(f"Agent.{self._name}")
        
        level_map = {
            LogLevel.DEBUG: logging.DEBUG,
            LogLevel.INFO: logging.INFO,
            LogLevel.WARNING: logging.WARNING,
            LogLevel.ERROR: logging.ERROR,
            LogLevel.CRITICAL: logging.CRITICAL,
        }
        logger.setLevel(level_map.get(self._config.logging.level, logging.INFO))
        
        if not logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter(self._config.logging.log_format))
            logger.addHandler(handler)
        
        return logger
    
    def get_status(self) -> dict:
        """Get Agent status information"""
        return {
            "agent_id": self._agent_id,
            "name": self._name,
            "role": self._role.value,
            "state": self.state.value,
            "is_running": self.is_running,
            "queue_size": self._message_queue.qsize(),
            "metrics": self._metrics.to_dict(),
            "capabilities": [c.name for c in self._capabilities if c.enabled],
            "tools": [t.name for t in self._tools.get_all()],
        }
    
    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}(id={self._agent_id}, name={self._name}, state={self.state.value})>"
