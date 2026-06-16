"""
AgentForge Utils - Agent Infrastructure Module

Provides core components for building intelligent Multi-Agent systems:

Core Modules:
- message: Message protocol definitions
- config: Configuration management
- state: State and lifecycle management
- tool: Tool interface and registry (LiteLLM compatible)
- base_agent: Agent base class
- communication: Communication mechanisms (message bus, event system)
- llm: LLM client for various providers (OpenAI, Anthropic, etc.)
- memory: Memory systems with LLM-based condensation
"""

# ===== Core Modules =====

# Message module
from .message import (
    # Enums
    MessageType,
    MessagePriority,
    ControlAction,
    # Data classes
    MessageHeader,
    BaseMessage,
    TaskMessage,
    ResultMessage,
    StatusMessage,
    ErrorMessage,
    ControlMessage,
    # Factory functions
    create_task_message,
    create_result_message,
    create_error_message,
)

# Config module
from .config import (
    # Enums
    LogLevel,
    LLMProvider,
    ExecutionMode,
    # Config classes
    LLMConfig,
    ExecutionConfig,
    LoggingConfig,
    NetworkConfig,
    MemoryConfig,
    AgentConfig,
)

# State module
from .state import (
    # Enums
    AgentState,
    TaskState,
    # Data classes
    StateTransition,
    TaskContext,
    # Managers
    StateManager,
    AgentContext,
    # Constants
    VALID_AGENT_TRANSITIONS,
    VALID_TASK_TRANSITIONS,
)

# Tool module (refactored with LiteLLM support)
from .tool import (
    # Enums
    ToolCategory,
    SecurityRisk,
    # Data classes
    ToolResult,
    # Base class
    BaseTool,
    # Registry
    ToolRegistry,
    global_registry,
    # Decorator
    tool,
    # Helper function
    create_tool_param,
    # Built-in tools
    ThinkTool,
    FinishTool,
)

# Agent base
from .base_agent import (
    AgentRole,
    AgentCapability,
    AgentMetrics,
    BaseAgent,
)

# Communication module
from .communication import (
    Subscription,
    MessageBus,
    EventEmitter,
    MessageRouter,
)

# ===== Intelligence Modules =====

# LLM module
from .llm import (
    # Data classes
    Message,
    LLMResponse,
    # Base class
    BaseLLMClient,
    # Clients
    OpenAIClient,
    AnthropicClient,
    LocalLLMClient,
    # Factory
    create_llm_client,
    # High-level interface
    LLM,
)

# Memory module (with LLM condenser)
from .memory import (
    # Data classes
    MemoryItem,
    # Memory types
    ShortTermMemory,
    WorkingMemory,
    LongTermMemory,
    # LLM Condenser
    LLMSummarizingCondenser,
    # Unified memory
    AgentMemory,
)


# Version info
__version__ = "0.4.0"
__author__ = "AgentForge Team"


# Export list
__all__ = [
    # ===== Core =====
    # Message
    "MessageType",
    "MessagePriority",
    "ControlAction",
    "MessageHeader",
    "BaseMessage",
    "TaskMessage",
    "ResultMessage",
    "StatusMessage",
    "ErrorMessage",
    "ControlMessage",
    "create_task_message",
    "create_result_message",
    "create_error_message",
    
    # Config
    "LogLevel",
    "LLMProvider",
    "ExecutionMode",
    "LLMConfig",
    "ExecutionConfig",
    "LoggingConfig",
    "NetworkConfig",
    "MemoryConfig",
    "AgentConfig",
    
    # State
    "AgentState",
    "TaskState",
    "StateTransition",
    "TaskContext",
    "StateManager",
    "AgentContext",
    "VALID_AGENT_TRANSITIONS",
    "VALID_TASK_TRANSITIONS",
    
    # Tool (LiteLLM compatible)
    "ToolCategory",
    "SecurityRisk",
    "ToolResult",
    "BaseTool",
    "ToolRegistry",
    "global_registry",
    "tool",
    "create_tool_param",
    "ThinkTool",
    "FinishTool",
    
    # Agent
    "AgentRole",
    "AgentCapability",
    "AgentMetrics",
    "BaseAgent",
    
    # Communication
    "Subscription",
    "MessageBus",
    "EventEmitter",
    "MessageRouter",
    
    # ===== Intelligence =====
    # LLM
    "Message",
    "LLMResponse",
    "BaseLLMClient",
    "OpenAIClient",
    "AnthropicClient",
    "LocalLLMClient",
    "create_llm_client",
    "LLM",
    
    # Memory (with condenser)
    "MemoryItem",
    "ShortTermMemory",
    "WorkingMemory",
    "LongTermMemory",
    "LLMSummarizingCondenser",
    "AgentMemory",
]
