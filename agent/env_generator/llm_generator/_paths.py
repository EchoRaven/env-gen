"""
Path Configuration for LLM Generator

This module provides centralized path management to avoid scattered sys.path.insert calls.
Import this module at the top of files that need access to parent packages.

Usage:
    from _paths import setup_paths
    setup_paths()
    
    # Now you can import from utils, workspace, etc.
    from utils.tool import BaseTool
    from workspace import Workspace
"""

import sys
from pathlib import Path

# Key directories
LLM_GENERATOR_DIR = Path(__file__).parent.resolve()
ENV_GENERATOR_DIR = LLM_GENERATOR_DIR.parent
AGENTS_DIR = ENV_GENERATOR_DIR.parent

# Subdirectories
TOOLS_DIR = LLM_GENERATOR_DIR / "tools"
AGENTS_SUBDIR = LLM_GENERATOR_DIR / "agents"
MEMORY_DIR = LLM_GENERATOR_DIR / "memory"
RUNTIME_DIR = LLM_GENERATOR_DIR / "runtime"
SPECS_DIR = LLM_GENERATOR_DIR / "specs"
PROMPTS_DIR = LLM_GENERATOR_DIR / "multi_agent" / "prompts"  # Active prompts location
VERIFICATION_DIR = LLM_GENERATOR_DIR / "verification"

# Path setup flag to avoid duplicate insertions
_paths_setup = False


def setup_paths():
    """
    Setup Python path for imports.
    
    Call this once at the start of modules that need to import from:
    - utils (from AGENTS_DIR)
    - workspace (from LLM_GENERATOR_DIR)
    - memory, tools, etc. (from LLM_GENERATOR_DIR)
    """
    global _paths_setup
    
    if _paths_setup:
        return
    
    # Add paths in order of priority (most specific first)
    paths_to_add = [
        str(LLM_GENERATOR_DIR),  # For workspace, memory, tools, etc.
        str(AGENTS_DIR),          # For utils package
    ]
    
    for path in paths_to_add:
        if path not in sys.path:
            sys.path.insert(0, path)
    
    _paths_setup = True


def get_project_root() -> Path:
    """Get the root directory of the Gen-Env project."""
    return AGENTS_DIR.parent.parent


def get_screenshot_dir() -> Path:
    """Get the screenshot directory for reference images."""
    return LLM_GENERATOR_DIR / "screenshot"


def get_prompts_dir() -> Path:
    """Get the prompts directory."""
    return PROMPTS_DIR


# Auto-setup on import for convenience
setup_paths()

