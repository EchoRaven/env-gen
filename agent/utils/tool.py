"""
Tool Interface Module - LiteLLM-compatible tool definitions

Inspired by OpenHands, this module provides:
- Standard OpenAI/LiteLLM function calling format
- Clean tool definition with ChatCompletionToolParam
- Tool registry with categorization
- Async execution support
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Optional, TypeVar
import asyncio
import inspect
from functools import wraps


class ToolCategory(Enum):
    """Tool category for organization."""
    FILE = "file"           # File operations (read, write, list)
    CODE = "code"           # Code operations (grep, replace, lint)
    SHELL = "shell"         # Shell commands
    RUNTIME = "runtime"     # Runtime operations (start server, test API)
    SEARCH = "search"       # Search operations
    THINK = "think"         # Thinking/reasoning tools
    AGENT = "agent"         # Agent control tools (think, finish)
    KNOWLEDGE = "knowledge" # Knowledge management (query, store)
    WORKSPACE = "workspace" # Shared workspace (specs, status, contracts)
    CUSTOM = "custom"       # Custom tools


class SecurityRisk(Enum):
    """Security risk level for actions."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class ToolResult:
    """Result of tool execution."""
    success: bool = True
    data: Any = None
    error_message: Optional[str] = None
    execution_time: float = 0.0
    metadata: dict = field(default_factory=dict)
    # #1116: framework-level notices about the CALL ITSELF, rendered into the text the
    # agent reads. `data` belongs to the tool and its consumers parse its shape, so a
    # notice must not be smuggled in there. Appended last so no positional construction
    # of ToolResult changes meaning.
    notices: list = field(default_factory=list)
    
    @classmethod
    def ok(cls, data: Any = None, **metadata) -> "ToolResult":
        """Create success result."""
        return cls(success=True, data=data, metadata=metadata)
    
    @classmethod
    def fail(cls, error_message: str, **metadata) -> "ToolResult":
        """Create failure result."""
        return cls(success=False, error_message=error_message, metadata=metadata)
    
    # #674: on FAILURE this returned the error line ALONE and dropped `data` on the floor —
    # and `data` is where tools put what actually went wrong. `test_api` reads the HTTP response
    # body, bounds it (#610) and stores it as data["response"], then reports
    # `error_message="HTTP Error: 500"`. The agent saw the status code and nothing else.
    #
    # Measured over the 249 run logs: 25788 failed tool calls, each roughly one wasted agent
    # step (per #257 a run's cost is prompt, re-sent every step). `test_api` is the largest
    # single source at 5248 across 123 runs, median 22 per run, and 1750 of those are a bare
    # "HTTP Error: N" with no body. 22 construction sites across 6 files build a failed
    # ToolResult carrying data the model never sees — code_tools alone has 10, including the
    # #635 syntax check whose data={"errors": [...]} held the line and column.
    #
    # The ceiling is #610's already-justified agent-facing body limit rather than a new number,
    # and producers that bound their own payloads (_bound_api_body_610, output[:2000]) are
    # unaffected because they are already under it.
    _FAILED_DATA_CHARS_674 = 8000

    def _with_notices_1116(self, text: str) -> str:
        """Append framework notices so the CALLER sees them, not only a log reader."""
        try:
            extra = [str(n).strip() for n in (self.notices or []) if str(n).strip()]
        except Exception:
            return text
        return text + "\n" + "\n".join(extra) if extra else text

    def __str__(self) -> str:
        if self.success:
            body = str(self.data) if self.data is not None else "OK"
            return self._with_notices_1116(body)
        base = f"Error: {self.error_message}"
        if self.data is None:
            return self._with_notices_1116(base)
        detail = str(self.data)
        if not detail or detail in ("{}", "[]", "None"):
            return self._with_notices_1116(base)
        if len(detail) > self._FAILED_DATA_CHARS_674:
            detail = (detail[:self._FAILED_DATA_CHARS_674]
                      + f"\n… [truncated — {len(detail)} chars total]")
        return self._with_notices_1116(f"{base}\n{detail}")


def create_tool_param(
    name: str,
    description: str,
    parameters: dict[str, dict],
    required: Optional[list[str]] = None,
) -> dict:
    """
    Create a tool parameter in OpenAI/LiteLLM ChatCompletionToolParam format.
    
    Args:
        name: Tool name
        description: Tool description
        parameters: Dict of parameter_name -> {type, description, enum?, ...}
                    OR a full JSON schema object with type, properties, required
        required: List of required parameter names (ignored if parameters is full schema)
        
    Returns:
        ChatCompletionToolParam-compatible dict
        
    Example:
        # Simple format (preferred):
        tool = create_tool_param(
            name="read",
            description="Read a file from disk",
            parameters={
                "file_path": {"type": "string", "description": "File path to read"},
                "path": {"type": "string", "description": "Alias for file_path (Claude Code-style)"},
                "offset": {"type": "integer", "description": "1-based line offset (optional)"},
            },
            required=["file_path"]
        )
        
        # Full schema format (also accepted):
        tool = create_tool_param(
            name="read",
            description="Read a file from disk",
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"]
            }
        )
    """
    # Check if parameters is already a full JSON schema (has "type": "object" and "properties")
    if isinstance(parameters, dict) and parameters.get("type") == "object" and "properties" in parameters:
        # Already full schema format, use as-is
        params_obj = parameters
    else:
        # Simple properties dict, wrap it
        params_obj = {
            "type": "object",
            "properties": parameters,
            "required": required or [],
        }
    
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": params_obj,
        },
    }


class BaseTool(ABC):
    """
    Base class for all tools.
    
    Tools should:
    1. Define their interface via the `tool_definition` property
    2. Implement async `execute` method
    3. Handle errors gracefully
    
    Example:
        class ReadToolExample(BaseTool):
            @property
            def tool_definition(self) -> dict:
                return create_tool_param(
                    name="read",
                    description="Read file contents",
                    parameters={"file_path": {"type": "string", "description": "File path"}},
                    required=["file_path"]
                )
            
            async def execute(self, file_path: str, **kwargs) -> ToolResult:
                content = Path(file_path).read_text()
                return ToolResult.ok(content)
    """
    
    def __init__(self, name: Optional[str] = None, category: Optional[ToolCategory] = None):
        self._execution_count = 0
        self._last_executed: Optional[datetime] = None
        self._category = category if category is not None else ToolCategory.CUSTOM
        self._name_override = name  # For subclasses that set name directly
    
    @property
    @abstractmethod
    def tool_definition(self) -> dict:
        """
        Return tool definition in ChatCompletionToolParam format.
        
        Returns:
            Dict with 'type' and 'function' keys
        """
        pass
    
    @property
    def name(self) -> str:
        """Get tool name from definition or override."""
        if hasattr(self, '_name_override') and self._name_override:
            return self._name_override
        try:
            return self.tool_definition.get("function", {}).get("name", "unknown")
        except RecursionError:
            return getattr(self, 'NAME', 'unknown')
    
    @property
    def description(self) -> str:
        """Get tool description from definition."""
        return self.tool_definition.get("function", {}).get("description", "")
    
    @property
    def category(self) -> ToolCategory:
        """Get tool category."""
        return self._category
    
    @abstractmethod
    async def execute(self, **kwargs) -> ToolResult:
        """
        Execute the tool with given parameters.
        
        Args:
            **kwargs: Tool parameters
            
        Returns:
            ToolResult with success/failure and data
        """
        pass
    
    async def __call__(self, **kwargs) -> ToolResult:
        """Make tool callable. Supports both sync and async execute methods."""
        import asyncio
        import inspect
        
        start_time = datetime.now()
        
        try:
            # Handle both sync and async execute methods
            if inspect.iscoroutinefunction(self.execute):
                result = await self.execute(**kwargs)
            else:
                # Run sync function in executor to not block event loop
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(None, lambda: self.execute(**kwargs))
            
            if result:
                result.execution_time = (datetime.now() - start_time).total_seconds()
            self._execution_count += 1
            self._last_executed = datetime.now()
            return result
        except Exception as e:
            return ToolResult.fail(str(e))


class ToolRegistry:
    """
    Registry for managing tools.
    
    Provides:
    - Tool registration and lookup
    - Category-based filtering
    - Export to OpenAI function format
    """
    
    def __init__(self):
        self._tools: dict[str, BaseTool] = {}
        self._categories: dict[ToolCategory, list[str]] = {cat: [] for cat in ToolCategory}

    def _normalize_category(self, category: Any) -> ToolCategory:
        """Normalize enum/string category values to ToolCategory."""
        if isinstance(category, ToolCategory):
            return category
        if isinstance(category, str):
            raw = category.strip()
            if not raw:
                return ToolCategory.CUSTOM
            # Prefer enum value mapping ("workspace"), fallback to name mapping ("WORKSPACE")
            try:
                return ToolCategory(raw.lower())
            except Exception:
                try:
                    return ToolCategory[raw.upper()]
                except Exception:
                    return ToolCategory.CUSTOM
        return ToolCategory.CUSTOM
    
    def register(self, tool: BaseTool) -> None:
        """Register a tool."""
        name = tool.name
        if name in self._tools:
            # Allow re-registration (update)
            self.unregister(name)

        normalized_category = self._normalize_category(tool.category)
        # Keep the tool's category canonical for later lookups/unregister.
        if hasattr(tool, "_category"):
            tool._category = normalized_category

        self._tools[name] = tool
        self._categories[normalized_category].append(name)
    
    def unregister(self, name: str) -> bool:
        """Unregister a tool by name."""
        if name not in self._tools:
            return False
        
        tool = self._tools[name]
        del self._tools[name]

        normalized_category = self._normalize_category(tool.category)
        if name in self._categories[normalized_category]:
            self._categories[normalized_category].remove(name)
        
        return True
    
    def get(self, name: str) -> Optional[BaseTool]:
        """Get a tool by name."""
        return self._tools.get(name)
    
    def get_all(self) -> list[BaseTool]:
        """Get all registered tools."""
        return list(self._tools.values())
    
    def get_by_category(self, category: ToolCategory) -> list[BaseTool]:
        """Get tools by category."""
        normalized_category = self._normalize_category(category)
        names = self._categories.get(normalized_category, [])
        return [self._tools[n] for n in names if n in self._tools]
    
    def to_openai_tools(self) -> list[dict]:
        """
        Export all tools in OpenAI/LiteLLM format.
        
        Returns:
            List of ChatCompletionToolParam dicts
        """
        result = []
        for tool in self._tools.values():
            td = getattr(tool, "tool_definition", None)
            if td:
                # tool_definition might be a method or a property
                result.append(td() if callable(td) else td)
        return result
    
    def to_openai_functions(self) -> list[dict]:
        """
        Alias for to_openai_tools() for backward compatibility.
        
        Returns:
            List of function dicts for OpenAI function calling
        """
        return self.to_openai_tools()
    
    def __contains__(self, name: str) -> bool:
        return name in self._tools
    
    def __len__(self) -> int:
        return len(self._tools)
    
    def __iter__(self):
        return iter(self._tools.values())


# ===== Tool Decorator =====

T = TypeVar('T')


def tool(
    name: Optional[str] = None,
    description: Optional[str] = None,
    category: ToolCategory = ToolCategory.CUSTOM,
    parameters: Optional[dict] = None,
    required: Optional[list[str]] = None,
):
    """
    Decorator to convert a function into a tool.
    
    Usage:
        @tool(
            name="echo",
            description="Echo the input message",
            parameters={"message": {"type": "string", "description": "Message to echo"}},
            required=["message"]
        )
        async def echo(message: str) -> str:
            return message
    """
    def decorator(func: Callable) -> type[BaseTool]:
        func_name = name or func.__name__
        func_description = description or func.__doc__ or f"Execute {func_name}"
        
        # Auto-detect parameters from function signature if not provided
        func_params = parameters
        func_required = required or []
        
        if func_params is None:
            func_params = {}
            sig = inspect.signature(func)
            hints = {}
            try:
                hints = func.__annotations__
            except AttributeError:
                pass
            
            type_map = {
                str: "string",
                int: "integer",
                float: "number",
                bool: "boolean",
                list: "array",
                dict: "object",
            }
            
            for param_name, param in sig.parameters.items():
                if param_name in ['self', 'cls', 'kwargs']:
                    continue
                
                param_type = hints.get(param_name, str)
                json_type = type_map.get(param_type, "string")
                
                func_params[param_name] = {
                    "type": json_type,
                    "description": f"Parameter {param_name}",
                }
                
                if param.default == inspect.Parameter.empty:
                    func_required.append(param_name)
        
        class FunctionTool(BaseTool):
            def __init__(self):
                super().__init__()
                self._func = func
                self._category = category
            
            @property
            def tool_definition(self) -> dict:
                return create_tool_param(
                    name=func_name,
                    description=func_description,
                    parameters=func_params,
                    required=func_required,
                )
            
            async def execute(self, **kwargs) -> ToolResult:
                try:
                    if asyncio.iscoroutinefunction(self._func):
                        result = await self._func(**kwargs)
                    else:
                        result = self._func(**kwargs)
                    return ToolResult.ok(result)
                except Exception as e:
                    return ToolResult.fail(str(e))
        
        FunctionTool.__name__ = f"{func_name}Tool"
        return FunctionTool
    
    return decorator


# ===== Built-in Tools =====

class ThinkTool(BaseTool):
    """
    Tool for explicit reasoning/thinking.
    
    Allows the agent to think through a problem without taking action.
    Inspired by OpenHands ThinkTool.
    """
    
    DESCRIPTION = """Use this tool to think through a problem before acting.
    
Common use cases:
1. When exploring code and discovering bugs, brainstorm possible fixes
2. After receiving test results, think about how to fix failures
3. When planning complex changes, outline different approaches
4. When debugging issues, organize your thoughts and hypotheses

This tool logs your thought process but does not execute any code or make changes."""
    
    def __init__(self):
        super().__init__()
        self._category = ToolCategory.THINK
    
    @property
    def tool_definition(self) -> dict:
        return create_tool_param(
            name="think",
            description=self.DESCRIPTION,
            parameters={
                "thought": {
                    "type": "string",
                    "description": "The thought or reasoning to log",
                },
            },
            required=["thought"],
        )
    
    async def execute(self, thought: str, **kwargs) -> ToolResult:
        # Think tool just logs and returns the thought
        return ToolResult.ok(f"Thought: {thought}")


class FinishTool(BaseTool):
    """Tool to signal task completion."""
    
    def __init__(self):
        super().__init__()
        self._category = ToolCategory.CUSTOM
    
    @property
    def tool_definition(self) -> dict:
        return create_tool_param(
            name="finish",
            description="Signal that the task is complete. Use this when you have finished all required work.",
            parameters={
                "message": {
                    "type": "string",
                    "description": "Final message summarizing what was done",
                },
            },
            required=["message"],
        )
    
    async def execute(self, message: str, **kwargs) -> ToolResult:
        return ToolResult.ok({"finished": True, "message": message})


# Global tool registry
global_registry = ToolRegistry()
