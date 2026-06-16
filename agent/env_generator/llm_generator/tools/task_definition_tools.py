"""
Task Definition Tools - Flexible tools for Task Agent

Design Philosophy:
- Task Agent has full freedom to define actions and tasks
- These tools help organize and save definitions
- No restrictions on what actions can be defined
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
import yaml

from utils.tool import BaseTool, ToolCategory, ToolResult


logger = logging.getLogger("task_definition_tools")


def _sync_task_file_to_hub(tool: BaseTool, output_path: Path, content: str, operation: str) -> None:
    hubs = getattr(tool, "_hubs", None)
    if not hubs or not hasattr(hubs, "sync_file_change"):
        return
    try:
        rel_path = str(output_path.relative_to(getattr(tool, "output_dir", output_path.parent))).replace("\\", "/")
    except Exception:
        rel_path = str(output_path)
    try:
        hubs.sync_file_change(
            rel_path,
            content,
            agent=str(getattr(tool, "_agent_id", "") or ""),
            operation=operation,
            old_content="",
        )
    except Exception:
        return


class DefineActionSpaceTool(BaseTool):
    """Define a custom action space."""
    
    NAME = "define_action_space"
    DESCRIPTION = """Define a custom action space for the application.

YOU have full freedom to define any actions that make sense for this app.
Don't use generic templates - design actions specific to the application!

Example:
```python
define_action_space({
    "name": "GameVault Actions",
    "description": "Custom actions for game store",
    "actions": {
        "browse_by_genre": {
            "type": "ui",
            "description": "Filter games by genre",
            "parameters": {
                "genre": {"type": "string", "enum": ["action", "rpg", "strategy"]}
            },
            "effects": ["games_filtered"]
        },
        "view_game_details": {
            "type": "ui",
            "description": "Click on a game to see details",
            "parameters": {"game_id": {"type": "string"}},
            "effects": ["on_game_page"]
        },
        "api_list_games": {
            "type": "api",
            "description": "Get games from API",
            "parameters": {
                "page": {"type": "int"},
                "genre": {"type": "string", "optional": True}
            }
        }
    }
})
```

Action types are NOT restricted - use whatever makes sense:
- ui: Web UI interactions
- api: Direct API calls
- mcp: MCP tool calls
- custom: Application-specific actions
"""
    
    def __init__(self, output_dir: Path = None):
        super().__init__(name=self.NAME, category=ToolCategory.AGENT)
        self.output_dir = output_dir
        self._action_space = None
    
    def get_tool_param(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.NAME,
                "description": self.DESCRIPTION,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action_space": {
                            "type": "object",
                            "description": "Action space definition with name, description, and actions dict"
                        },
                        "name": {
                            "type": "string",
                            "description": "Action space name (flat form)."
                        },
                        "description": {
                            "type": "string",
                            "description": "Action space description (flat form)."
                        },
                        "actions": {
                            "type": "object",
                            "description": "Actions dictionary keyed by action name (flat form)."
                        }
                    },
                    "additionalProperties": True
                }
            }
        }
    
    def tool_definition(self):
        return self.get_tool_param()
    
    def execute(self, action_space: Optional[Dict] = None, **kwargs) -> ToolResult:
        """Save action space definition."""
        try:
            # Accept both formats:
            # 1) define_action_space(action_space={...})
            # 2) define_action_space(name=..., description=..., actions=...)
            if action_space is None:
                if kwargs:
                    action_space = {
                        "name": kwargs.get("name"),
                        "description": kwargs.get("description", ""),
                        "actions": kwargs.get("actions", {}),
                    }
                    # Preserve any additional caller-provided fields.
                    for key, value in kwargs.items():
                        if key not in action_space:
                            action_space[key] = value
                else:
                    return ToolResult.fail(
                        "Missing action space payload. Provide action_space={...} "
                        "or flat fields (name/description/actions)."
                    )

            if not isinstance(action_space, dict):
                return ToolResult.fail("action_space must be an object/dict")
            if not action_space.get("name"):
                return ToolResult.fail("action_space.name is required")
            if "actions" not in action_space or not isinstance(action_space.get("actions"), dict):
                return ToolResult.fail("action_space.actions must be a dictionary")

            self._action_space = action_space
            
            # Save to file if output_dir set
            if self.output_dir:
                output_path = self.output_dir / "tasks" / "action_space.yaml"
                output_path.parent.mkdir(parents=True, exist_ok=True)
                content = yaml.dump({"action_space": action_space}, default_flow_style=False, allow_unicode=True)
                output_path.write_text(content, encoding="utf-8")
                _sync_task_file_to_hub(self, output_path, content, "define_action_space")
                
                return ToolResult.ok({
                    "message": f"Action space '{action_space.get('name')}' saved",
                    "actions_count": len(action_space.get("actions", {})),
                    "file": str(output_path)
                })
            
            return ToolResult.ok({
                "message": f"Action space '{action_space.get('name')}' defined",
                "actions_count": len(action_space.get("actions", {}))
            })
            
        except Exception as e:
            return ToolResult.fail(f"Error: {e}")


class DefineTaskTool(BaseTool):
    """Define a task with state machine."""
    
    NAME = "define_task"
    DESCRIPTION = """Define a task with custom states and transitions.

YOU design the state machine - no restrictions on states or actions!

Example:
```python
define_task({
    "id": "purchase_game",
    "name": "Purchase a Game",
    "description": "Find and purchase a specific game",
    "category": "e-commerce",
    
    "states": {
        "start": {"type": "initial"},
        "search": {
            "type": "action",
            "actions": [{"type": "search_games", "params": {"query": "target_game"}}]
        },
        "select": {
            "type": "action", 
            "actions": [{"type": "view_game_details", "params": {"game_id": "..."}}]
        },
        "add_to_cart": {
            "type": "action",
            "actions": [{"type": "add_to_cart", "params": {"game_id": "..."}}]
        },
        "checkout": {
            "type": "action",
            "actions": [{"type": "purchase_game", "params": {"payment": "credit_card"}}]
        },
        "success": {"type": "terminal", "metadata": {"result": "success"}},
        "failure": {"type": "terminal", "metadata": {"result": "failure"}}
    },
    
    "transitions": [
        {"from": "start", "to": "search"},
        {"from": "search", "to": "select"},
        {"from": "select", "to": "add_to_cart"},
        {"from": "add_to_cart", "to": "checkout"},
        {"from": "checkout", "to": "success", "condition": {"type": "order_confirmed"}},
        {"from": "checkout", "to": "failure", "condition": {"type": "payment_failed"}}
    ],
    
    "initial_state": "start",
    
    "rewards": {
        "success": 10.0,
        "failure": -5.0,
        "step": -0.1,
        "timeout": -3.0
    },
    
    "max_steps": 30
})
```
"""
    
    def __init__(self, output_dir: Path = None):
        super().__init__(name=self.NAME, category=ToolCategory.AGENT)
        self.output_dir = output_dir
        self._tasks = []
    
    def get_tool_param(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.NAME,
                "description": self.DESCRIPTION,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "task": {
                            "type": "object",
                            "description": "Task definition with id, name, states, transitions, rewards"
                        },
                        "id": {"type": "string", "description": "Task id (flat form)."},
                        "name": {"type": "string", "description": "Task name (flat form)."},
                        "description": {"type": "string", "description": "Task description (flat form)."},
                        "category": {"type": "string", "description": "Task category (flat form)."},
                        "states": {"type": "object", "description": "State machine states (flat form)."},
                        "transitions": {"type": "array", "items": {"type": "object"}, "description": "State transitions (flat form)."},
                        "initial_state": {"type": "string", "description": "Initial state id (flat form)."},
                        "rewards": {"type": "object", "description": "Reward configuration (flat form)."},
                        "max_steps": {"type": "integer", "description": "Maximum steps (flat form)."},
                    },
                    "additionalProperties": True
                }
            }
        }
    
    def tool_definition(self):
        return self.get_tool_param()
    
    def execute(self, task: Optional[Dict] = None, **kwargs) -> ToolResult:
        """Define a task."""
        try:
            # Accept both formats:
            # 1) define_task(task={...})
            # 2) define_task(id=..., name=..., states=..., ...)
            if task is None:
                if kwargs:
                    task = {
                        "id": kwargs.get("id"),
                        "name": kwargs.get("name"),
                        "description": kwargs.get("description", ""),
                        "category": kwargs.get("category", ""),
                        "states": kwargs.get("states", {}),
                        "transitions": kwargs.get("transitions", []),
                        "initial_state": kwargs.get("initial_state"),
                        "rewards": kwargs.get("rewards", {}),
                        "max_steps": kwargs.get("max_steps"),
                    }
                    # Preserve additional caller-provided fields.
                    for key, value in kwargs.items():
                        if key not in task:
                            task[key] = value
                else:
                    return ToolResult.fail(
                        "Missing task payload. Provide task={...} or flat fields "
                        "(id/name/states/transitions/initial_state...)."
                    )

            if not isinstance(task, dict):
                return ToolResult.fail("task must be an object/dict")

            # Best-effort normalization for partial payloads
            if not task.get("id") and task.get("name"):
                task["id"] = str(task.get("name")).strip().lower().replace(" ", "_")

            states = task.get("states")
            if isinstance(states, dict) and states:
                if not task.get("initial_state"):
                    task["initial_state"] = "start" if "start" in states else next(iter(states.keys()))

            # Validate basic structure
            errors = []
            if not task.get("id"):
                errors.append("Missing task id")
            if not task.get("states"):
                errors.append("Missing states")
            if not task.get("initial_state"):
                errors.append("Missing initial_state")
            if task.get("initial_state") and task["initial_state"] not in task.get("states", {}):
                errors.append(f"Initial state '{task['initial_state']}' not found in states")
            
            if errors:
                return ToolResult.fail(f"Validation errors: {errors}")
            
            self._tasks.append(task)
            
            return ToolResult.ok({
                "message": f"Task '{task.get('name', task['id'])}' defined",
                "states_count": len(task.get("states", {})),
                "transitions_count": len(task.get("transitions", [])),
                "total_tasks": len(self._tasks)
            })
            
        except Exception as e:
            return ToolResult.fail(f"Error: {e}")


class SaveTaskSuiteTool(BaseTool):
    """Save all defined tasks to file."""
    
    NAME = "save_task_suite"
    DESCRIPTION = """Save all defined tasks to tasks/tasks.yaml.

Example:
```python
save_task_suite(
    name="GameVault Test Suite",
    description="Tasks for testing GameVault application"
)
```
"""
    
    def __init__(self, output_dir: Path, define_task_tool: DefineTaskTool):
        super().__init__(name=self.NAME, category=ToolCategory.AGENT)
        self.output_dir = output_dir
        self.define_task_tool = define_task_tool
    
    def get_tool_param(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.NAME,
                "description": self.DESCRIPTION,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Task suite name"},
                        "description": {"type": "string", "description": "Suite description"}
                    },
                    "required": ["name"]
                }
            }
        }
    
    def tool_definition(self):
        return self.get_tool_param()
    
    def execute(self, name: str, description: str = "") -> ToolResult:
        """Save task suite."""
        try:
            suite = {
                "name": name,
                "description": description,
                "tasks": self.define_task_tool._tasks
            }
            
            output_path = self.output_dir / "tasks" / "tasks.yaml"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            content = yaml.dump(suite, default_flow_style=False, allow_unicode=True)
            output_path.write_text(content, encoding="utf-8")
            _sync_task_file_to_hub(self, output_path, content, "save_task_suite")
            
            return ToolResult.ok({
                "message": f"Task suite '{name}' saved",
                "tasks_count": len(self.define_task_tool._tasks),
                "file": str(output_path)
            })
            
        except Exception as e:
            return ToolResult.fail(f"Error: {e}")


class GetExamplePatternsTool(BaseTool):
    """Get example patterns for reference (not restrictions!)."""
    
    NAME = "get_example_patterns"
    DESCRIPTION = """Get example action/task patterns for REFERENCE.

These are examples to inspire you, NOT templates to copy!
Design your own actions specific to the application.

Example:
```python
get_example_patterns(pattern_type="actions")  # Example actions
get_example_patterns(pattern_type="tasks")    # Example tasks
get_example_patterns(pattern_type="all")      # Everything
```
"""
    
    def __init__(self):
        super().__init__(name=self.NAME, category=ToolCategory.AGENT)
    
    def get_tool_param(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.NAME,
                "description": self.DESCRIPTION,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pattern_type": {
                            "type": "string",
                            "enum": ["actions", "tasks", "conditions", "all"],
                            "description": "What examples to get"
                        }
                    },
                    "required": ["pattern_type"]
                }
            }
        }
    
    def tool_definition(self):
        return self.get_tool_param()
    
    def execute(self, pattern_type: str = "all") -> ToolResult:
        """Get example patterns."""
        try:
            from env_generator.llm_generator.multi_agent.task_definition import (
                get_example_action_space,
                get_example_task,
                EXAMPLE_UI_ACTIONS,
                EXAMPLE_API_ACTIONS,
                EXAMPLE_CONDITIONS,
            )
        except Exception:
            # Compatibility fallback for alternative sys.path layouts.
            from multi_agent.task_definition import (  # type: ignore
                get_example_action_space,
                get_example_task,
                EXAMPLE_UI_ACTIONS,
                EXAMPLE_API_ACTIONS,
                EXAMPLE_CONDITIONS,
            )
        
        result = ["# Example Patterns (REFERENCE ONLY - Design your own!)\n"]
        
        if pattern_type in ["actions", "all"]:
            result.append("## Example UI Actions\n")
            result.append("```yaml")
            result.append(yaml.dump(EXAMPLE_UI_ACTIONS, default_flow_style=False))
            result.append("```\n")
            
            result.append("## Example API Actions\n")
            result.append("```yaml")
            result.append(yaml.dump(EXAMPLE_API_ACTIONS, default_flow_style=False))
            result.append("```\n")
        
        if pattern_type in ["conditions", "all"]:
            result.append("## Example Conditions\n")
            result.append("```yaml")
            result.append(yaml.dump(EXAMPLE_CONDITIONS, default_flow_style=False))
            result.append("```\n")
        
        if pattern_type in ["tasks", "all"]:
            result.append("## Example Task\n")
            result.append(get_example_task())
        
        if pattern_type == "all":
            result.append("\n## Example Action Space\n")
            result.append(get_example_action_space())
        
        return ToolResult.ok("\n".join(result))


class ListDefinedTasksTool(BaseTool):
    """List all defined tasks."""
    
    NAME = "list_defined_tasks"
    DESCRIPTION = "List all tasks that have been defined so far."
    
    def __init__(self, define_task_tool: DefineTaskTool):
        super().__init__(name=self.NAME, category=ToolCategory.AGENT)
        self.define_task_tool = define_task_tool
    
    def get_tool_param(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.NAME,
                "description": self.DESCRIPTION,
                "parameters": {"type": "object", "properties": {}}
            }
        }
    
    def tool_definition(self):
        return self.get_tool_param()
    
    def execute(self) -> ToolResult:
        """List defined tasks."""
        tasks = self.define_task_tool._tasks
        
        if not tasks:
            return ToolResult.ok("No tasks defined yet.")
        
        lines = [f"Defined Tasks ({len(tasks)} total):"]
        for task in tasks:
            states = len(task.get("states", {}))
            trans = len(task.get("transitions", []))
            lines.append(f"  - {task.get('id')}: {task.get('name')} ({states} states, {trans} transitions)")
        
        return ToolResult.ok("\n".join(lines))


def create_task_definition_tools(output_dir: Path) -> List[BaseTool]:
    """Create task definition tools."""
    define_action_space = DefineActionSpaceTool(output_dir)
    define_task = DefineTaskTool(output_dir)
    
    return [
        define_action_space,
        define_task,
        SaveTaskSuiteTool(output_dir, define_task),
        GetExamplePatternsTool(),
        ListDefinedTasksTool(define_task),
    ]
