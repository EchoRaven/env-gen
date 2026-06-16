"""Shared imports/helpers for split team tool modules."""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.tool import BaseTool, ToolResult, create_tool_param, ToolCategory

def _merge_team_member_context(
    context: Optional[Dict[str, Any]] = None,
    writing_style: Optional[str] = None,
    supervision: Optional[str] = None,
) -> Dict[str, Any]:
    """Merge high-level collaboration directives into member context."""
    merged = dict(context or {})
    if writing_style:
        merged["writing_style"] = writing_style
    if supervision:
        merged["supervision"] = supervision
    return merged


def _managed_team_member_schema_properties() -> Dict[str, Any]:
    return {
        "agent_id": {"type": "string"},
        "description": {"type": "string"},
        "agent_type": {"type": "string"},
        "config_profile": {"type": "string", "description": "Optional backing execution profile"},
        "role": {"type": "string"},
        "task": {"type": "string"},
        "writing_style": {"type": "string"},
        "supervision": {"type": "string"},
        "skills": {"type": "array", "items": {"type": "string"}},
        "inherit_parent_skills": {"type": "boolean"},
        "capabilities": {"type": "array", "items": {"type": "string"}},
        "model": {"type": "string"},
        "write_scopes": {"type": "array", "items": {"type": "string"}},
        "include_vision": {"type": "boolean"},
        "depends_on": {"type": "array", "items": {"type": "string"}},
        "disabled_tools": {"type": "array", "items": {"type": "string"}},
        "context": {"type": "object"},
    }

