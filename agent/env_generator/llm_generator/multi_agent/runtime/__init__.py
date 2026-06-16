"""
Runtime Module — post-Cutover 9 (CRDT scaffolding purged).

HubRegistry is the single runtime handle; JsonStore is the persistence primitive.

New code should import from:
  multi_agent.runtime.hub_registry  (HubRegistry)
  multi_agent.runtime.json_store    (JsonStore)
"""

from .hub_registry import HubRegistry  # noqa: F401
from .human_console import HumanConsole  # noqa: F401
from .json_store import JsonStore  # noqa: F401
from .project import (  # noqa: F401
    ProjectMetadata,
    ProjectIndex,
    list_projects,
    resume_project,
    load_project_metadata,
    save_project_metadata,
)

__all__ = [
    "HubRegistry",
    "HumanConsole",
    "JsonStore",
    "ProjectMetadata",
    "ProjectIndex",
    "list_projects",
    "resume_project",
    "load_project_metadata",
    "save_project_metadata",
]
