"""
Workspace - Centralized path management for LLM Generator

The Workspace defines the sandbox root for all file operations.
All tools and agents operate relative to this root and cannot access
paths outside the workspace.

Design Principles:
1. Single source of truth for project root
2. All paths resolved relative to workspace root
3. Security: no path escape allowed
4. Consistent path normalization
"""

from pathlib import Path
from typing import Union, Optional
import os


class WorkspaceError(Exception):
    """Error related to workspace operations."""
    pass


class PathEscapeError(WorkspaceError):
    """Raised when a path attempts to escape the workspace."""
    pass


class Workspace:
    """
    Workspace manages the project root directory.
    
    All file operations are sandboxed to this directory.
    The agent only sees paths relative to the workspace root (./...).
    
    Example:
        workspace = Workspace("/path/to/generated/my_project")
        
        # Resolve user path to absolute
        abs_path = workspace.resolve("app/server.js")
        # -> /path/to/generated/my_project/app/server.js
        
        # Convert absolute to relative (for display to agent)
        rel_path = workspace.relative("/path/to/generated/my_project/app/server.js")
        # -> "app/server.js"
        
        # Check if path is within workspace
        workspace.contains("/path/to/generated/my_project/app/server.js")  # True
        workspace.contains("/etc/passwd")  # False
    """
    
    def __init__(self, root: Union[str, Path]):
        """
        Initialize workspace with root directory.
        
        Args:
            root: Absolute path to the workspace root directory.
                  This is the project directory (e.g., generated/atlassian_home).
        """
        self._root = Path(root).resolve()
        
        # Ensure root exists
        self._root.mkdir(parents=True, exist_ok=True)
    
    @property
    def root(self) -> Path:
        """Get the workspace root path.

        DEPRECATED for new code: use ``resolve(path)`` for path resolution,
        ``code_root`` / ``base_root`` when you genuinely need a named
        directory. ``.root`` is kept only so the plain ``Workspace``
        stays quack-compatible with ``PathRoutedWorkspace`` during the
        migration. A lint guard in PR 3 will fail the build if any
        module outside ``workspace.py`` /
        ``path_routed_workspace.py`` reads it directly.
        """
        return self._root

    @property
    def code_root(self) -> Path:
        """The directory the agent writes its own code to.

        For a plain ``Workspace`` this is the same as ``base_root`` —
        only ``PathRoutedWorkspace`` diverges (worktree vs project
        base). Provided so callers can use the same API on either type
        and the routed case is the one that physically differs.
        """
        return self._root

    @property
    def base_root(self) -> Path:
        """The shared project root (where ``design/``, ``screenshots/``,
        etc. live). Same as ``code_root`` for a plain ``Workspace``."""
        return self._root

    @property
    def name(self) -> str:
        """Get the project name (last component of root path)."""
        return self._root.name
    
    def resolve(self, path: Union[str, Path, None]) -> Path:
        """
        Resolve a user-provided path to an absolute path within the workspace.
        
        Very forgiving - handles many path formats and tries to find valid paths:
        - Empty/None: returns workspace root
        - Relative path: "app/server.js" -> /root/app/server.js
        - Absolute path within workspace: returned as-is
        - Path with redundant prefixes: cleaned and resolved
        - Tries fuzzy matching if exact path not found
        
        Args:
            path: User-provided path (from LLM or tool call)
            
        Returns:
            Absolute path within the workspace
            
        Raises:
            PathEscapeError: If resolved path would escape workspace (only if really outside)
        """
        if not path:
            return self._root
        
        path_str = str(path).strip()
        
        # Handle empty string
        if not path_str or path_str == ".":
            return self._root
        
        # Clean the path - remove any redundant prefixes
        clean_path = self._clean_path(path_str)
        
        # If it's absolute and within workspace, use it
        if clean_path.startswith("/"):
            abs_path = Path(clean_path).resolve()
            # Check if this absolute path is within workspace
            if self.contains(abs_path):
                return abs_path
            # If not, extract the relative part and try again
            # e.g., /some/wrong/path/app/server.js -> try app/server.js
            clean_path = self._extract_relative_from_absolute(clean_path)
            # Join with root
            abs_path = (self._root / clean_path).resolve()
        else:
            # Relative path - join with root
            abs_path = (self._root / clean_path).resolve()
        
        # Security check: ensure path is within workspace
        if not self.contains(abs_path):
            # Last resort: try to extract just the filename or last few components
            parts = Path(clean_path).parts
            if len(parts) > 1:
                # Try with fewer path components
                for i in range(1, len(parts)):
                    shorter_path = Path(*parts[i:])
                    test_path = (self._root / shorter_path).resolve()
                    if self.contains(test_path):
                        return test_path
            
            raise PathEscapeError(
                f"Path '{path}' resolves to '{abs_path}' which is outside workspace '{self._root}'"
            )
        
        return abs_path
    
    def _extract_relative_from_absolute(self, abs_path: str) -> str:
        """
        Extract a relative path from an absolute path that's outside the workspace.
        
        Looks for common directory patterns like 'app/', 'src/', 'design/', etc.
        """
        common_dirs = ['app', 'src', 'design', 'docker', 'config', 'tests', 'lib', 'docs']
        parts = Path(abs_path).parts
        
        for i, part in enumerate(parts):
            if part in common_dirs:
                return str(Path(*parts[i:]))
        
        # If no common dir found, return the last component
        return parts[-1] if parts else ""
    
    def _clean_path(self, path: str) -> str:
        """
        Clean a path by removing redundant prefixes.
        
        Very forgiving - handles many common LLM mistakes:
        - "generated/atlassian_home/app/..." -> "app/..."
        - "atlassian_home/app/..." -> "app/..."
        - "./app/..." -> "app/..."
        - "env_generator/generated/atlassian_home/app/..." -> "app/..."
        - "/Users/.../generated/project/app/..." -> "app/..."
        - "llm_generator/generated/project/app/..." -> "app/..."
        """
        clean = path
        project_name = self._root.name
        root_str = str(self._root)
        
        # Remove leading ./
        while clean.startswith("./"):
            clean = clean[2:]
        
        # Remove leading ../  (often mistakenly added)
        while clean.startswith("../"):
            clean = clean[3:]
        
        # Remove full root path prefix (absolute path)
        if clean.startswith(root_str + "/"):
            clean = clean[len(root_str) + 1:]
        elif clean.startswith(root_str):
            clean = clean[len(root_str):].lstrip("/")
        
        # Remove any absolute path that ends with /generated/project_name/
        # e.g., /Users/xxx/Desktop/xxx/generated/expedia/app/...
        import re
        abs_pattern = rf'^.*[/\\]generated[/\\]{re.escape(project_name)}[/\\](.*)$'
        match = re.match(abs_pattern, clean)
        if match:
            clean = match.group(1)
        
        # Remove "llm_generator/generated/project_name" prefix
        llm_gen_prefix = f"llm_generator/generated/{project_name}"
        if clean.startswith(llm_gen_prefix + "/"):
            clean = clean[len(llm_gen_prefix) + 1:]
        elif clean.startswith(llm_gen_prefix):
            clean = clean[len(llm_gen_prefix):].lstrip("/")
        
        # Remove "env_generator/generated/project_name" prefix
        env_gen_prefix = f"env_generator/generated/{project_name}"
        if clean.startswith(env_gen_prefix + "/"):
            clean = clean[len(env_gen_prefix) + 1:]
        elif clean.startswith(env_gen_prefix):
            clean = clean[len(env_gen_prefix):].lstrip("/")
        
        # Remove "Agents/env_generator/llm_generator/generated/project_name" prefix
        agents_prefix = f"Agents/env_generator/llm_generator/generated/{project_name}"
        if clean.startswith(agents_prefix + "/"):
            clean = clean[len(agents_prefix) + 1:]
        elif clean.startswith(agents_prefix):
            clean = clean[len(agents_prefix):].lstrip("/")
        
        # Remove "generated/project_name" or "generated-X/project_name" prefix (multiple times if nested)
        # Handle both "generated/expedia" and "generated-2/expedia" patterns
        generated_prefix = f"generated/{project_name}"
        while clean.startswith(generated_prefix + "/"):
            clean = clean[len(generated_prefix) + 1:]
        if clean.startswith(generated_prefix):
            clean = clean[len(generated_prefix):].lstrip("/")
        
        # Handle "generated-X/project_name" pattern (e.g., "generated-2/expedia")
        generated_pattern = re.match(rf'^generated-\d+/{re.escape(project_name)}/(.*)$', clean)
        if generated_pattern:
            clean = generated_pattern.group(1)
        elif re.match(rf'^generated-\d+/{re.escape(project_name)}$', clean):
            clean = ""
        
        # Remove just project_name prefix (multiple times if nested)
        while clean.startswith(project_name + "/"):
            clean = clean[len(project_name) + 1:]
        if clean == project_name:
            clean = ""
        
        # Remove any remaining "generated/" or "generated-X/" prefix if followed by project name
        if clean.startswith("generated/"):
            remaining = clean[len("generated/"):]
            if remaining.startswith(project_name + "/"):
                clean = remaining[len(project_name) + 1:]
            elif remaining == project_name:
                clean = ""
        
        # Handle "generated-X/" pattern
        gen_x_match = re.match(r'^generated-\d+/(.*)$', clean)
        if gen_x_match:
            remaining = gen_x_match.group(1)
            if remaining.startswith(project_name + "/"):
                clean = remaining[len(project_name) + 1:]
            elif remaining == project_name:
                clean = ""
        
        return clean
    
    def relative(self, path: Union[str, Path]) -> str:
        """
        Convert an absolute path to a path relative to workspace root.
        
        Args:
            path: Absolute path within the workspace
            
        Returns:
            Path relative to workspace root (e.g., "app/server.js")
        """
        abs_path = Path(path).resolve()
        
        try:
            rel = abs_path.relative_to(self._root)
            return str(rel)
        except ValueError:
            # Path is not within workspace
            return str(path)
    
    def contains(self, path: Union[str, Path]) -> bool:
        """
        Check if a path is within the workspace.
        
        Args:
            path: Path to check (absolute or relative)
            
        Returns:
            True if path is within workspace
        """
        try:
            abs_path = Path(path).resolve()
            abs_path.relative_to(self._root)
            return True
        except ValueError:
            return False
    
    def is_write_allowed(self, path: Union[str, Path], agent_id: Optional[str]) -> bool:
        """Plain ``Workspace`` has no per-route write gate (orchestrator
        / early-init / test contexts). Routing-aware tools call this
        on every write attempt; ``PathRoutedWorkspace`` enforces real
        gates per ``ROUTING_TABLE``."""
        return True

    def exists(self, path: Union[str, Path, None] = None) -> bool:
        """Check if a path exists within the workspace."""
        resolved = self.resolve(path)
        return resolved.exists()
    
    def is_file(self, path: Union[str, Path]) -> bool:
        """Check if path is a file."""
        return self.resolve(path).is_file()
    
    def is_dir(self, path: Union[str, Path]) -> bool:
        """Check if path is a directory."""
        return self.resolve(path).is_dir()
    
    def mkdir(self, path: Union[str, Path], parents: bool = True, exist_ok: bool = True):
        """Create a directory within the workspace."""
        resolved = self.resolve(path)
        resolved.mkdir(parents=parents, exist_ok=exist_ok)
    
    def read_text(self, path: Union[str, Path], encoding: str = "utf-8") -> str:
        """Read text content from a file."""
        return self.resolve(path).read_text(encoding=encoding)
    
    def write_text(self, path: Union[str, Path], content: str, encoding: str = "utf-8"):
        """Write text content to a file (creates parent directories)."""
        resolved = self.resolve(path)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(content, encoding=encoding)
    
    def glob(self, pattern: str) -> list:
        """Find files matching a glob pattern within the workspace."""
        return list(self._root.glob(pattern))
    
    def walk(self):
        """Walk the workspace directory tree."""
        for root, dirs, files in os.walk(self._root):
            yield Path(root), dirs, files
    
    def __str__(self) -> str:
        return str(self._root)
    
    def __repr__(self) -> str:
        return f"Workspace('{self._root}')"
    
    def __fspath__(self) -> str:
        """Support os.fspath() for path-like operations."""
        return str(self._root)


# Convenience function for creating workspace
def create_workspace(root: Union[str, Path]) -> Workspace:
    """
    Create a new Workspace instance.
    
    Args:
        root: Path to the workspace root directory
        
    Returns:
        Workspace instance
    """
    return Workspace(root)

