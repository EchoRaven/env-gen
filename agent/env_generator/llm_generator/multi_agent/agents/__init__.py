"""
Multi-Agent Environment Generation Agents

Architecture:
- ConfigurableAgent: Generic agent loaded from YAML config
- All behavior comes from: j2 prompts + tool categories + config flags
- No custom subclasses needed - just add to agents_config.yaml

Config-Driven Design:
- agents_config.yaml defines all agents
- Each agent specifies: prompt template, tools, timeout, flags
- create_agent() instantiates any agent from config

Inherited from utils:
- BaseAgent: State management, message queue, stuck detection, retry, metrics
- MessageBus: Agent communication
- ToolRegistry: Tool management
"""

# Re-export utils base classes for convenience
from utils.base_agent import BaseAgent, AgentRole, AgentCapability, AgentMetrics
from utils.state import AgentState
from utils.communication import MessageBus, EventEmitter

# Environment generation specific
from .base import EnvGenAgent, safe_json_dumps

# Config-driven agent - the only way to create agents
from .configurable_agent import (
    ConfigurableAgent,
    create_agent,
    get_agent_config,
    get_resident_lane_specs,
    list_available_agents,
    load_config,
    resolve_agent_profile_id,
)

__all__ = [
    # Utils base classes
    "BaseAgent",
    "AgentRole",
    "AgentCapability",
    "AgentMetrics",
    "AgentState",
    "MessageBus",
    "EventEmitter",
    # EnvGen base
    "EnvGenAgent",
    "safe_json_dumps",
    # Config-driven agents
    "ConfigurableAgent",
    "create_agent",
    "get_agent_config",
    "get_resident_lane_specs",
    "list_available_agents",
    "load_config",
    "resolve_agent_profile_id",
]
