"""
Base imports and utilities for all tools.

This module provides:
1. Centralized path setup
2. Common imports (BaseTool, ToolResult, Workspace, etc.)
3. Utility functions shared across tools

Usage in tool files:
    from ._base import *
    # or
    from ._base import BaseTool, ToolResult, Workspace, ToolCategory
"""

# Setup paths first
import sys
from pathlib import Path

# Path setup
_TOOLS_DIR = Path(__file__).parent.resolve()
_LLM_GEN_DIR = _TOOLS_DIR.parent
_AGENTS_DIR = _LLM_GEN_DIR.parent.parent

for _path in [str(_LLM_GEN_DIR), str(_AGENTS_DIR)]:
    if _path not in sys.path:
        sys.path.insert(0, _path)

# Core imports
from utils.tool import (
    BaseTool,
    ToolResult,
    ToolCategory,
    create_tool_param,
)

from workspace import Workspace

# Common standard library imports
import os
import re
import json
import asyncio
import logging
import subprocess
from typing import (
    Any,
    Dict,
    List,
    Optional,
    Tuple,
    Union,
)
from dataclasses import dataclass, field

# Exports
__all__ = [
    # Base classes
    "BaseTool",
    "ToolResult", 
    "ToolCategory",
    "create_tool_param",
    "Workspace",
    
    # Standard library
    "os",
    "re",
    "json",
    "asyncio",
    "logging",
    "subprocess",
    "Path",
    
    # Typing
    "Any",
    "Dict",
    "List",
    "Optional",
    "Tuple",
    "Union",
    
    # Dataclasses
    "dataclass",
    "field",
]


# Utility functions

def get_tool_logger(name: str) -> logging.Logger:
    """Get a logger for a tool module."""
    return logging.getLogger(f"tools.{name}")


def truncate_output(text: str, max_length: int = 5000) -> str:
    """Truncate long output for tool results."""
    if len(text) <= max_length:
        return text
    return text[:max_length] + f"\n...[truncated {len(text) - max_length} chars]..."

