"""
Task Definition - Flexible task definitions for RL training

Design Philosophy:
- Task Agent can freely define ANY action types
- No hardcoded enums - actions are just dicts
- Agent decides what makes sense for the specific application
- Provides patterns and examples, not restrictions

This supports:
1. Web UI actions (click, type, navigate, etc.)
2. API/MCP actions (tool calls)
3. Custom application-specific actions
4. Composite actions (macros)
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Union
import yaml


logger = logging.getLogger("task_definition")


# ==================== Flexible Action System ====================

@dataclass
class Action:
    """
    A flexible action definition - Task Agent decides the structure.
    
    Common fields:
        type: Action type (any string, e.g., "click", "api_call", "custom_action")
        target: What to act on (selector, endpoint, etc.)
        params: Additional parameters
        description: Human-readable description
        
    The actual fields depend on the action type - Agent defines them freely.
    """
    type: str
    params: Dict[str, Any] = field(default_factory=dict)
    description: str = ""
    
    def to_dict(self) -> Dict:
        return {
            "type": self.type,
            "params": self.params,
            "description": self.description,
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> "Action":
        return cls(
            type=data.get("type", "unknown"),
            params=data.get("params", {}),
            description=data.get("description", ""),
        )


# ==================== Action Space Definition ====================

@dataclass 
class ActionDefinition:
    """
    Definition of a single action type in the action space.
    
    Task Agent creates these to define what actions are possible.
    """
    name: str                              # Action name (e.g., "click_button")
    type: str                              # Category (ui, api, custom)
    description: str                       # What this action does
    parameters: Dict[str, Any] = field(default_factory=dict)  # Parameter schema
    preconditions: List[str] = field(default_factory=list)    # Required state
    effects: List[str] = field(default_factory=list)          # State changes
    examples: List[Dict] = field(default_factory=list)        # Usage examples
    
    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "type": self.type,
            "description": self.description,
            "parameters": self.parameters,
            "preconditions": self.preconditions,
            "effects": self.effects,
            "examples": self.examples,
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> "ActionDefinition":
        return cls(
            name=data.get("name", ""),
            type=data.get("type", "custom"),
            description=data.get("description", ""),
            parameters=data.get("parameters", {}),
            preconditions=data.get("preconditions", []),
            effects=data.get("effects", []),
            examples=data.get("examples", []),
        )


@dataclass
class ActionSpace:
    """
    Complete action space for an application.
    
    Task Agent defines this based on:
    - UI components found in frontend
    - API endpoints from backend
    - Custom domain-specific actions
    """
    name: str
    description: str
    actions: Dict[str, ActionDefinition] = field(default_factory=dict)
    
    # Categorization
    ui_actions: List[str] = field(default_factory=list)
    api_actions: List[str] = field(default_factory=list)
    custom_actions: List[str] = field(default_factory=list)
    
    # Metadata
    version: str = "1.0.0"
    generated_at: str = ""
    
    def add_action(self, action: ActionDefinition):
        """Add an action definition."""
        self.actions[action.name] = action
        
        # Categorize
        if action.type == "ui":
            if action.name not in self.ui_actions:
                self.ui_actions.append(action.name)
        elif action.type == "api":
            if action.name not in self.api_actions:
                self.api_actions.append(action.name)
        else:
            if action.name not in self.custom_actions:
                self.custom_actions.append(action.name)
    
    def get_action(self, name: str) -> Optional[ActionDefinition]:
        """Get action definition by name."""
        return self.actions.get(name)
    
    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "description": self.description,
            "actions": {k: v.to_dict() for k, v in self.actions.items()},
            "ui_actions": self.ui_actions,
            "api_actions": self.api_actions,
            "custom_actions": self.custom_actions,
            "version": self.version,
            "generated_at": self.generated_at or datetime.now().isoformat(),
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> "ActionSpace":
        space = cls(
            name=data.get("name", ""),
            description=data.get("description", ""),
            version=data.get("version", "1.0.0"),
            generated_at=data.get("generated_at", ""),
        )
        
        for name, action_data in data.get("actions", {}).items():
            space.add_action(ActionDefinition.from_dict(action_data))
        
        return space


# ==================== Task Definition ====================

@dataclass
class State:
    """
    A state in the task state machine.
    
    States can be:
    - initial: Starting point
    - action: Perform actions
    - observation: Check conditions
    - terminal: End state (success/failure/timeout)
    """
    id: str
    type: str = "action"  # initial, action, observation, terminal
    description: str = ""
    
    # Actions to perform in this state (for action states)
    actions: List[Dict] = field(default_factory=list)
    
    # Conditions to check (for observation states)
    conditions: List[Dict] = field(default_factory=list)
    
    # Timeout
    timeout_seconds: int = 30
    
    # Metadata
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "type": self.type,
            "description": self.description,
            "actions": self.actions,
            "conditions": self.conditions,
            "timeout_seconds": self.timeout_seconds,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> "State":
        return cls(
            id=data.get("id", ""),
            type=data.get("type", "action"),
            description=data.get("description", ""),
            actions=data.get("actions", []),
            conditions=data.get("conditions", []),
            timeout_seconds=data.get("timeout_seconds", 30),
            metadata=data.get("metadata", {}),
        )


@dataclass
class Transition:
    """Transition between states."""
    from_state: str
    to_state: str
    condition: Dict = field(default_factory=dict)  # When to transition
    priority: int = 0  # Higher = checked first
    
    def to_dict(self) -> Dict:
        return {
            "from": self.from_state,
            "to": self.to_state,
            "condition": self.condition,
            "priority": self.priority,
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> "Transition":
        return cls(
            from_state=data.get("from", ""),
            to_state=data.get("to", ""),
            condition=data.get("condition", {}),
            priority=data.get("priority", 0),
        )


@dataclass
class Task:
    """
    A complete task definition.
    
    Task Agent defines:
    - What the task is trying to accomplish
    - States and transitions (state machine)
    - Success/failure criteria
    - Reward signals for RL
    - Execution mode (browser, mcp, or hybrid)
    """
    id: str
    name: str
    description: str
    category: str = "general"  # auth, crud, search, navigation, custom
    
    # Execution mode - tells User Agent HOW to execute
    # - "browser": Use browser automation (click, type, navigate)
    # - "mcp": Use MCP tool calls
    # - "hybrid": Task contains both browser and MCP actions
    # - "auto": User Agent decides based on action types
    execution_mode: str = "auto"
    
    # MCP configuration (when execution_mode is "mcp" or "hybrid")
    mcp_config: Dict = field(default_factory=lambda: {
        "server_url": "http://localhost:8080",  # MCP server URL
        "auth_token": None,  # Optional auth
    })
    
    # State machine
    states: Dict[str, State] = field(default_factory=dict)
    transitions: List[Transition] = field(default_factory=list)
    initial_state: str = ""
    
    # Success criteria
    success_conditions: List[Dict] = field(default_factory=list)
    failure_conditions: List[Dict] = field(default_factory=list)
    
    # Rewards
    rewards: Dict[str, float] = field(default_factory=lambda: {
        "success": 1.0,
        "failure": -1.0,
        "step": -0.01,
        "timeout": -0.5,
    })
    
    # Metadata
    priority: int = 0
    tags: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    max_steps: int = 50
    timeout_seconds: int = 300
    
    def add_state(self, state: State):
        """Add a state."""
        self.states[state.id] = state
        if state.type == "initial" and not self.initial_state:
            self.initial_state = state.id
    
    def add_transition(self, from_state: str, to_state: str, condition: Dict = None, priority: int = 0):
        """Add a transition."""
        self.transitions.append(Transition(
            from_state=from_state,
            to_state=to_state,
            condition=condition or {},
            priority=priority,
        ))
    
    def validate(self) -> List[str]:
        """Validate task definition."""
        errors = []
        
        if not self.initial_state:
            errors.append("No initial state")
        elif self.initial_state not in self.states:
            errors.append(f"Initial state '{self.initial_state}' not found")
        
        # Check transitions reference valid states
        for t in self.transitions:
            if t.from_state not in self.states:
                errors.append(f"Transition from unknown state: {t.from_state}")
            if t.to_state not in self.states:
                errors.append(f"Transition to unknown state: {t.to_state}")
        
        # Check for terminal states
        terminals = [s for s in self.states.values() if s.type == "terminal"]
        if not terminals:
            errors.append("No terminal states")
        
        return errors
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "execution_mode": self.execution_mode,
            "mcp_config": self.mcp_config,
            "states": {k: v.to_dict() for k, v in self.states.items()},
            "transitions": [t.to_dict() for t in self.transitions],
            "initial_state": self.initial_state,
            "success_conditions": self.success_conditions,
            "failure_conditions": self.failure_conditions,
            "rewards": self.rewards,
            "priority": self.priority,
            "tags": self.tags,
            "dependencies": self.dependencies,
            "max_steps": self.max_steps,
            "timeout_seconds": self.timeout_seconds,
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> "Task":
        task = cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            description=data.get("description", ""),
            category=data.get("category", "general"),
            execution_mode=data.get("execution_mode", "auto"),
            mcp_config=data.get("mcp_config", {}),
            initial_state=data.get("initial_state", ""),
            success_conditions=data.get("success_conditions", []),
            failure_conditions=data.get("failure_conditions", []),
            rewards=data.get("rewards", {}),
            priority=data.get("priority", 0),
            tags=data.get("tags", []),
            dependencies=data.get("dependencies", []),
            max_steps=data.get("max_steps", 50),
            timeout_seconds=data.get("timeout_seconds", 300),
        )
        
        for state_id, state_data in data.get("states", {}).items():
            state_data["id"] = state_id
            task.states[state_id] = State.from_dict(state_data)
        
        for t_data in data.get("transitions", []):
            task.transitions.append(Transition.from_dict(t_data))
        
        return task
    
    def get_execution_hint(self) -> str:
        """
        Get execution hint for User Agent.
        
        Returns a string explaining how to execute this task.
        """
        if self.execution_mode == "browser":
            return "Execute using browser automation (click, type, navigate)"
        elif self.execution_mode == "mcp":
            url = self.mcp_config.get("server_url", "http://localhost:8080")
            return f"Execute using MCP tools at {url}"
        elif self.execution_mode == "hybrid":
            return "Mixed mode: use browser for UI actions, MCP for API actions"
        else:  # auto
            # Analyze actions to suggest
            ui_count = 0
            mcp_count = 0
            for state in self.states.values():
                for action in state.actions:
                    action_type = action.get("type", "")
                    if action_type in ["ui", "click", "type", "navigate", "scroll", "hover"]:
                        ui_count += 1
                    elif action_type in ["api", "mcp", "tool_call"]:
                        mcp_count += 1
            
            if mcp_count == 0:
                return "Auto-detected: Browser mode (all UI actions)"
            elif ui_count == 0:
                return "Auto-detected: MCP mode (all API actions)"
            else:
                return f"Auto-detected: Hybrid mode ({ui_count} UI, {mcp_count} MCP actions)"


@dataclass
class TaskSuite:
    """Collection of tasks for an application."""
    name: str
    description: str
    action_space: ActionSpace = None
    tasks: List[Task] = field(default_factory=list)
    
    def add_task(self, task: Task):
        """Add a task."""
        self.tasks.append(task)
    
    def get_task(self, task_id: str) -> Optional[Task]:
        """Get task by ID."""
        for task in self.tasks:
            if task.id == task_id:
                return task
        return None
    
    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "description": self.description,
            "action_space": self.action_space.to_dict() if self.action_space else None,
            "tasks": [t.to_dict() for t in self.tasks],
        }
    
    def save(self, path: Path):
        """Save to YAML file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            yaml.dump(self.to_dict(), f, default_flow_style=False, allow_unicode=True)
    
    @classmethod
    def load(cls, path: Path) -> "TaskSuite":
        """Load from YAML file."""
        with open(path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        
        suite = cls(
            name=data.get("name", ""),
            description=data.get("description", ""),
        )
        
        if data.get("action_space"):
            suite.action_space = ActionSpace.from_dict(data["action_space"])
        
        for task_data in data.get("tasks", []):
            suite.tasks.append(Task.from_dict(task_data))
        
        return suite


# ==================== Reference Patterns (Not Restrictions!) ====================

# These are examples, Task Agent can define completely different actions

EXAMPLE_UI_ACTIONS = {
    "click": {
        "description": "Click on an element",
        "parameters": {
            "selector": {"type": "string", "description": "CSS/XPath selector"},
            "button": {"type": "string", "enum": ["left", "right", "middle"], "default": "left"}
        }
    },
    "type": {
        "description": "Type text into an element",
        "parameters": {
            "selector": {"type": "string"},
            "text": {"type": "string"},
            "clear_first": {"type": "boolean", "default": True}
        }
    },
    "navigate": {
        "description": "Navigate to a URL",
        "parameters": {
            "url": {"type": "string"}
        }
    },
    "select": {
        "description": "Select option from dropdown",
        "parameters": {
            "selector": {"type": "string"},
            "value": {"type": "string"}
        }
    },
    "scroll": {
        "description": "Scroll the page",
        "parameters": {
            "direction": {"type": "string", "enum": ["up", "down", "left", "right"]},
            "amount": {"type": "integer", "default": 300}
        }
    },
    "wait": {
        "description": "Wait for condition",
        "parameters": {
            "seconds": {"type": "number"},
            "condition": {"type": "object", "description": "Condition to wait for"}
        }
    },
    "hover": {
        "description": "Hover over an element",
        "parameters": {
            "selector": {"type": "string"}
        }
    },
    "drag_drop": {
        "description": "Drag from one element to another",
        "parameters": {
            "from_selector": {"type": "string"},
            "to_selector": {"type": "string"}
        }
    }
}

EXAMPLE_API_ACTIONS = {
    "api_get": {
        "description": "Make GET request",
        "parameters": {
            "endpoint": {"type": "string"},
            "params": {"type": "object"}
        }
    },
    "api_post": {
        "description": "Make POST request",
        "parameters": {
            "endpoint": {"type": "string"},
            "body": {"type": "object"}
        }
    },
    "mcp_call": {
        "description": "Call MCP tool",
        "parameters": {
            "tool_name": {"type": "string"},
            "arguments": {"type": "object"}
        }
    }
}

EXAMPLE_CONDITIONS = {
    "url_contains": {"url_substring": "string"},
    "url_equals": {"expected_url": "string"},
    "element_exists": {"selector": "string"},
    "element_visible": {"selector": "string"},
    "element_text_contains": {"selector": "string", "text": "string"},
    "element_count": {"selector": "string", "min": "int", "max": "int"},
    "api_returns": {"endpoint": "string", "status": "int"},
    "localStorage_has": {"key": "string"},
    "custom": {"code": "string"}  # Custom Python code
}


def get_example_action_space() -> str:
    """Get example action space definition for Task Agent reference."""
    return '''
# Example Action Space - Task Agent can modify or create completely new ones

action_space:
  name: "GameVault Actions"
  description: "Actions for GameVault application"
  
  actions:
    # UI Actions - interacting with the web interface
    click_game_card:
      type: ui
      description: "Click on a game card to view details"
      parameters:
        game_id: {type: string, description: "Game ID to click"}
      preconditions: ["on_games_page"]
      effects: ["navigated_to_game_detail"]
      examples:
        - {game_id: "game_123"}
    
    search_games:
      type: ui
      description: "Search for games using the search bar"
      parameters:
        query: {type: string}
      preconditions: ["search_bar_visible"]
      effects: ["search_results_displayed"]
    
    add_to_cart:
      type: ui
      description: "Add a game to shopping cart"
      parameters:
        game_id: {type: string}
      preconditions: ["on_game_detail", "user_logged_in"]
      effects: ["game_in_cart"]
    
    # API Actions - direct API calls
    api_list_games:
      type: api
      description: "Get list of games from API"
      parameters:
        page: {type: int, default: 1}
        limit: {type: int, default: 20}
        genre: {type: string, optional: true}
      effects: ["games_data_retrieved"]
    
    api_login:
      type: api
      description: "Login via API"
      parameters:
        email: {type: string}
        password: {type: string}
      effects: ["user_authenticated"]
    
    # Custom Actions - application-specific
    apply_filter:
      type: custom
      description: "Apply a filter combination"
      parameters:
        genre: {type: string, optional: true}
        price_min: {type: float, optional: true}
        price_max: {type: float, optional: true}
        on_sale: {type: bool, optional: true}
      effects: ["filters_applied", "results_updated"]
    
    checkout:
      type: custom
      description: "Complete the checkout process"
      parameters:
        payment_method: {type: string, enum: [credit_card, paypal]}
      preconditions: ["cart_not_empty", "user_logged_in"]
      effects: ["order_placed"]
'''


def get_example_task() -> str:
    """Get example task definition for Task Agent reference."""
    return '''
# Example Task - Task Agent can create completely custom tasks

task:
  id: "purchase_game"
  name: "Purchase a Game"
  description: "Find a specific game and complete the purchase"
  category: "e-commerce"
  
  # Task Agent defines states freely
  states:
    start:
      type: initial
      description: "Starting on homepage"
      actions: []
    
    search:
      type: action
      description: "Search for the game"
      actions:
        - type: search_games
          params: {query: "{{target_game}}"}
    
    select_game:
      type: action
      description: "Click on the game from results"
      actions:
        - type: click_game_card
          params: {game_id: "{{target_game_id}}"}
    
    add_to_cart:
      type: action
      description: "Add game to cart"
      actions:
        - type: add_to_cart
          params: {game_id: "{{target_game_id}}"}
    
    verify_cart:
      type: observation
      description: "Verify game is in cart"
      conditions:
        - type: element_exists
          params: {selector: ".cart-item[data-id='{{target_game_id}}']"}
    
    checkout:
      type: action
      actions:
        - type: checkout
          params: {payment_method: "credit_card"}
    
    success:
      type: terminal
      metadata: {result: "success"}
    
    failure:
      type: terminal
      metadata: {result: "failure"}
  
  # Task Agent defines transitions
  transitions:
    - {from: start, to: search}
    - {from: search, to: select_game}
    - {from: select_game, to: add_to_cart}
    - {from: add_to_cart, to: verify_cart}
    - {from: verify_cart, to: checkout, condition: {type: cart_has_item}}
    - {from: verify_cart, to: failure, condition: {type: cart_empty}}
    - {from: checkout, to: success, condition: {type: order_confirmed}}
    - {from: checkout, to: failure, condition: {type: payment_failed}}
  
  initial_state: start
  
  # Flexible success/failure conditions
  success_conditions:
    - {type: url_contains, value: "/order-confirmation"}
    - {type: element_exists, selector: ".order-success"}
  
  failure_conditions:
    - {type: element_exists, selector: ".error-message"}
    - {type: timeout}
  
  # Rewards for RL
  rewards:
    success: 10.0
    failure: -5.0
    step: -0.1
    timeout: -3.0
    
  max_steps: 30
  timeout_seconds: 180
'''
