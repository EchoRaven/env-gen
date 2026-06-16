"""
Multi-Agent Environment Generation System.

Keep this package init lightweight so sibling packages can import submodules like
`multi_agent.skill_loader` without triggering the full orchestrator stack and
causing circular imports during tool registration.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .agents import ConfigurableAgent, EnvGenAgent, create_agent
    from .orchestrator import GenerationResult, Orchestrator
    from .workspace_manager import WorkspaceManager

__all__ = [
    "Orchestrator",
    "GenerationResult",
    "WorkspaceManager",
    "EnvGenAgent",
    "ConfigurableAgent",
    "create_agent",
]


def __getattr__(name: str):
    if name in {"Orchestrator", "GenerationResult"}:
        from .orchestrator import GenerationResult, Orchestrator

        exports = {
            "Orchestrator": Orchestrator,
            "GenerationResult": GenerationResult,
        }
        return exports[name]

    if name == "WorkspaceManager":
        from .workspace_manager import WorkspaceManager

        return WorkspaceManager

    if name in {"EnvGenAgent", "ConfigurableAgent", "create_agent"}:
        from .agents import ConfigurableAgent, EnvGenAgent, create_agent

        exports = {
            "EnvGenAgent": EnvGenAgent,
            "ConfigurableAgent": ConfigurableAgent,
            "create_agent": create_agent,
        }
        return exports[name]

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
