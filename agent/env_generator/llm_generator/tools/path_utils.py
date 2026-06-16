"""
Path Utilities - Legacy compatibility layer

This module provides backward compatibility for tools using the old
path resolution API. New code should use the Workspace class directly.

Migration Guide:
    Old:
        from tools.path_utils import resolve_path, resolve_output_dir
        path = resolve_path(user_path, output_dir)
    
    New:
        from workspace import Workspace
        workspace = Workspace(output_dir)
        path = workspace.resolve(user_path)
"""

import warnings
from pathlib import Path
from typing import Union

# Import Workspace for delegation
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from workspace import Workspace


# Cache for Workspace instances (one per output_dir)
_workspace_cache: dict = {}


def _get_workspace(output_dir: Union[str, Path]) -> Workspace:
    """Get or create a Workspace instance for the given output_dir."""
    key = str(output_dir)
    if key not in _workspace_cache:
        _workspace_cache[key] = Workspace(output_dir)
    return _workspace_cache[key]


def resolve_path(path: str, output_dir: Path) -> Path:
    """
    Resolve a path relative to output_dir, avoiding double concatenation.
    
    DEPRECATED: Use Workspace.resolve() instead.
    
    Args:
        path: User-provided path (can be relative, absolute, or containing output_dir)
        output_dir: The base output directory
    
    Returns:
        Resolved absolute path within the workspace
    """
    workspace = _get_workspace(output_dir)
    try:
        return workspace.resolve(path)
    except Exception:
        # Fallback: if Workspace raises an error, use simple join
        # This maintains backward compatibility
        if not path:
            return Path(output_dir)
        return Path(output_dir) / path


def resolve_output_dir(output_dir: Union[str, Path, None]) -> Path:
    """
    Resolve and clean the output directory path.
    
    DEPRECATED: Just use Path(output_dir) or Workspace(output_dir).root
    
    Args:
        output_dir: The output directory path (string, Path, or None)
    
    Returns:
        Clean Path object
    """
    if not output_dir:
        return Path.cwd()
    
    path = Path(output_dir) if isinstance(output_dir, str) else output_dir
    return path.resolve()


def normalize_path_for_tracking(path: str, output_dir: Path) -> str:
    """
    Normalize a file path to be relative to output_dir.
    
    DEPRECATED: Use Workspace.relative() instead.
    
    Args:
        path: The path to normalize
        output_dir: The base output directory
    
    Returns:
        Path relative to output_dir as string
    """
    workspace = _get_workspace(output_dir)
    try:
        # First resolve to absolute, then get relative
        abs_path = workspace.resolve(path)
        return workspace.relative(abs_path)
    except Exception:
        # Fallback for edge cases
        return path


def clear_cache():
    """Clear the workspace cache. Useful for testing."""
    global _workspace_cache
    _workspace_cache.clear()


__all__ = [
    "resolve_path",
    "resolve_output_dir", 
    "normalize_path_for_tracking",
    "clear_cache",
]
