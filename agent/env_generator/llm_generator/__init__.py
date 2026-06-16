"""
LLM Generator - Generate OpenEnv-compatible web environments using LLM

Architecture (Multi-Agent):
- ConfigurableAgent: All agents loaded from agents_config.yaml
- Orchestrator: Coordinates multi-agent interaction
- MessageBus: Event-driven communication between agents

Available Agents (defined in config):
- orchestrator: Plans tasks, coordinates lanes, and delivers the project
- design: Creates design specifications
- database: Generates database code
- backend: Generates backend code
- frontend: Generates frontend code
- verifier: Runs validation and routes issues
- knowledge: Collects and manages knowledge

Usage:
    from llm_generator import Orchestrator
    from utils.config import LLMConfig
    
    orchestrator = Orchestrator(llm_config, output_dir, project_name)
    result = await orchestrator.run(requirements="Build a calendar app")
"""

from .agents import (
    Orchestrator,
    ConfigurableAgent,
    create_agent,
)
from .messages import Task, TaskType, Issue, IssueSeverity, TaskResult, VerifyResult
from .context import GenerationContext
from .progress import EventEmitter, EventType

__all__ = [
    # Multi-Agent System
    "Orchestrator",
    "ConfigurableAgent",
    "create_agent",

    # Messages
    "Task",
    "TaskType",
    "Issue",
    "IssueSeverity",
    "TaskResult",
    "VerifyResult",

    # Context
    "GenerationContext",

    # Events
    "EventEmitter",
    "EventType",
]
