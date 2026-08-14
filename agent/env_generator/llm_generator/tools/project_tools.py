"""
Project Structure Tools

Tools for the agent to understand and visualize the current project structure.
"""

import sys
from pathlib import Path
from typing import Optional, Dict, Any, List, Union
from dataclasses import dataclass

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.tool import BaseTool, ToolResult, ToolCategory, create_tool_param
from workspace import Workspace


# #607: binary/asset suffixes — never opened to count lines, collapsed to one row per dir
_ASSET_SUFFIXES_607 = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif", ".ico", ".bmp", ".svg",
    ".mp4", ".webm", ".mov", ".m4v", ".mp3", ".wav", ".ogg",
    ".woff", ".woff2", ".ttf", ".otf", ".eot",
    ".pdf", ".zip", ".gz", ".tar", ".jar", ".wasm",
})

class ProjectStructureTool(BaseTool):
    """
    Show the current project structure as a tree.
    
    Helps the agent understand:
    - What files have been generated
    - Current directory structure
    - Where to place new files
    - Avoid creating duplicates
    """
    
    NAME = "project_structure"
    
    DESCRIPTION = """Show the current project structure as a tree view.

Use this tool to:
- See what files already exist before planning new files
- Understand the project layout
- Avoid creating duplicate files in different locations
- Decide where to place new files

Returns a tree-like view of the project with file sizes and line counts.
"""
    
    def __init__(self, *, workspace: Workspace):
        super().__init__(name=self.NAME, category=ToolCategory.FILE)
        if workspace is None:
            raise ValueError(f"{self.NAME}: workspace is required (no bypass construction)")
        self.workspace = workspace
    
    @property
    def tool_definition(self):
        return create_tool_param(
            name=self.NAME,
            description=self.DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Subdirectory to show (optional, defaults to project root)"
                    },
                    "max_depth": {
                        "type": "integer",
                        "description": "Maximum depth to display (default: 5)"
                    },
                    "show_sizes": {
                        "type": "boolean",
                        "description": "Show file sizes and line counts (default: true)"
                    }
                },
                "required": []
            }
        )
    
    def execute(
        self, 
        path: str = "", 
        max_depth: int = 5,
        show_sizes: bool = True
    ) -> ToolResult:
        try:
            target_dir = self.workspace.resolve(path)
        except Exception as e:
            return ToolResult(success=False, error_message=f"Invalid path: {path}")
        
        if not target_dir.exists():
            # Show the user's input path, not the resolved absolute path
            return ToolResult(
                success=False,
                error_message=f"Directory not found: {path}. Use relative paths like 'app/', 'docker/', 'design/'"
            )
        
        lines = []
        stats = {"files": 0, "dirs": 0, "total_lines": 0}
        
        def format_size(size: int) -> str:
            if size < 1024:
                return f"{size}B"
            elif size < 1024 * 1024:
                return f"{size // 1024}KB"
            else:
                return f"{size // (1024 * 1024)}MB"
        
        def count_lines(file_path: Path) -> int:
            try:
                return len(file_path.read_text(encoding='utf-8').splitlines())
            except:
                return 0
        
        def build_tree(dir_path: Path, prefix: str = "", depth: int = 0):
            if depth > max_depth:
                lines.append(f"{prefix}... (max depth reached)")
                return
            
            try:
                entries = sorted(dir_path.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))
            except PermissionError:
                lines.append(f"{prefix}[Permission denied]")
                return
            
            # Filter out hidden files and common ignore patterns
            entries = [e for e in entries if not e.name.startswith('.') 
                      and e.name not in ['node_modules', '__pycache__', 'venv', '.git']]
            
            for i, entry in enumerate(entries):
                is_last = i == len(entries) - 1
                connector = "└── " if is_last else "├── "
                next_prefix = prefix + ("    " if is_last else "│   ")
                
                if entry.is_dir():
                    stats["dirs"] += 1
                    lines.append(f"{prefix}{connector}📁 {entry.name}/")
                    build_tree(entry, next_prefix, depth + 1)
                else:
                    stats["files"] += 1
                    size_info = ""
                    if show_sizes:
                        size = entry.stat().st_size
                        line_count = count_lines(entry)
                        stats["total_lines"] += line_count
                        size_info = f" ({format_size(size)}, {line_count} lines)"
                    
                    # Icon based on file type
                    ext = entry.suffix.lower()
                    icon = {
                        '.py': '🐍',
                        '.js': '📜',
                        '.jsx': '⚛️',
                        '.ts': '📘',
                        '.tsx': '⚛️',
                        '.json': '📋',
                        '.md': '📝',
                        '.sql': '🗃️',
                        '.css': '🎨',
                        '.html': '🌐',
                        '.yml': '⚙️',
                        '.yaml': '⚙️',
                        '': '📄',  # Dockerfile etc
                    }.get(ext, '📄')
                    
                    lines.append(f"{prefix}{connector}{icon} {entry.name}{size_info}")
        
        # Build the tree
        # Show relative path indicator to avoid LLM confusion
        if path:
            # Subdir query - show relative path
            rel_path = path.lstrip("./")
            lines.append(f"📦 ./{rel_path}/")
        else:
            # Root query - clearly indicate this is the workspace root
            lines.append(f"📦 ./ (workspace root)")
        build_tree(target_dir)
        
        # Summary
        summary = f"\n📊 Summary: {stats['files']} files, {stats['dirs']} directories"
        if show_sizes:
            summary += f", {stats['total_lines']} total lines"
        lines.append(summary)
        
        # Add path usage hint to prevent LLM confusion
        lines.append("\n💡 Paths: Use paths relative to workspace root (e.g., 'app/backend/src/routes/issues.js'), NOT absolute paths or paths starting with project name.")
        
        # Get relative path for display (never show absolute paths to LLM)
        try:
            rel_root = self.workspace.relative(target_dir)
            display_path = f"./{rel_root}" if str(rel_root) != "." else "./"
        except ValueError:
            display_path = "./"
        
        return ToolResult(
            success=True,
            data={
                "tree": "\n".join(lines),
                "stats": stats,
                "path": display_path,  # Relative path only - never expose absolute paths
                "note": "Use RELATIVE paths like 'app/backend/...' - do NOT prefix with project name or directory names"
            }
        )


class ListGeneratedFilesTool(BaseTool):
    """
    List all generated files with their status.
    """
    
    NAME = "list_generated_files"
    
    DESCRIPTION = """List all files that have been generated so far.

Returns a flat list of all generated files with:
- Full path
- Size
- Line count
- Category (frontend/backend/database/etc)

Use this to check what already exists before generating new files.
"""
    
    def __init__(self, *, workspace: Workspace):
        super().__init__(name=self.NAME, category=ToolCategory.FILE)
        if workspace is None:
            raise ValueError(f"{self.NAME}: workspace is required (no bypass construction)")
        self.workspace = workspace
    
    @property
    def tool_definition(self):
        return create_tool_param(
            name=self.NAME,
            description=self.DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "enum": ["all", "frontend", "backend", "env", "docker"],
                        "description": "Filter by category (default: all)"
                    }
                },
                "required": []
            }
        )
    
    def execute(self, category: str = "all") -> ToolResult:
        if not self.workspace.code_root.exists():
            return ToolResult(
                success=False,
                error_message="Output directory not found"
            )
        
        def categorize_file(path: str) -> str:
            if '/frontend/' in path or path.startswith('app/frontend'):
                return 'frontend'
            elif '/backend/' in path or path.startswith('app/backend'):
                return 'backend'
            elif '/database/' in path or path.startswith('app/database'):
                return 'database'
            elif '/env/' in path or path.startswith('env/'):
                return 'env'
            elif '/design/' in path or path.startswith('design/'):
                return 'design'
            elif '/docker/' in path or 'docker-compose' in path:
                return 'docker'
            else:
                return 'other'
        
        files_by_category = {
            'frontend': [],
            'backend': [],
            'database': [],
            'env': [],
            'design': [],
            'docker': [],
            'other': []
        }
        
        # #607 — A CODE LISTING SHOULD LIST CODE. This tool exists to answer "what already
        # exists before generating new files", and it was logged at 93,396 chars (~23k tokens)
        # per call. On a real delivered tree that is 589 files under `app/`, of which **503
        # are staged binary ASSETS** in `public/` — 330 .png, 119 .jpg, 38 .svg, 10 .woff2,
        # 6 .mp4 — none of which any agent will ever author or edit. They are collapsed to ONE
        # aggregate row per directory, which keeps everything a caller actually needs from
        # them (they exist, where, how many, how big) at ~1/100th the size.
        #
        # It also called `read_text()` on every one of those binaries just to count lines. The
        # decode raised and a bare `except` swallowed it — after the megabytes had already
        # been read off disk, on every call. Extension is checked FIRST now, so a binary is
        # never opened.
        _asset_dirs: Dict[str, Dict[str, Any]] = {}

        for file_path in self.workspace.code_root.rglob('*'):
            if file_path.is_file() and not file_path.name.startswith('.'):
                # Skip common ignore patterns
                path_str = str(file_path)
                if any(p in path_str for p in ['node_modules', '__pycache__', '.git', 'venv']):
                    continue

                relative_path = self.workspace.relative(file_path)
                cat = categorize_file(str(relative_path))

                if file_path.suffix.lower() in _ASSET_SUFFIXES_607:
                    _key = str(Path(relative_path).parent)
                    _agg = _asset_dirs.setdefault(
                        _key, {'category': cat, 'count': 0, 'size': 0, 'kinds': set()})
                    _agg['count'] += 1
                    _agg['kinds'].add(file_path.suffix.lower())
                    try:
                        _agg['size'] += file_path.stat().st_size
                    except OSError:
                        pass
                    continue

                try:
                    size = file_path.stat().st_size
                    lines = len(file_path.read_text(encoding='utf-8').splitlines())
                except Exception:
                    size = 0
                    lines = 0

                files_by_category[cat].append({
                    'path': str(relative_path),
                    'size': size,
                    'lines': lines
                })

        for _key, _agg in sorted(_asset_dirs.items()):
            files_by_category.setdefault(_agg['category'], []).append({
                'path': f"{_key}/ [{_agg['count']} asset files: "
                        f"{', '.join(sorted(_agg['kinds']))}]",
                'size': _agg['size'],
                'lines': 0,
                'asset_dir': True,
                'asset_count': _agg['count'],
            })

        # Filter by category if specified
        if category != "all":
            result = {category: files_by_category.get(category, [])}
        else:
            result = files_by_category
        
        # Build summary
        total_files = sum(len(f) for f in result.values())
        total_lines = sum(f['lines'] for files in result.values() for f in files)
        
        # Format output
        output_lines = [f"📁 Generated Files ({total_files} files, {total_lines} lines)\n"]
        for cat, files in result.items():
            if files:
                output_lines.append(f"\n{'='*40}")
                output_lines.append(f"📂 {cat.upper()} ({len(files)} files)")
                output_lines.append('='*40)
                for f in sorted(files, key=lambda x: x['path']):
                    output_lines.append(f"  {f['path']} ({f['lines']} lines)")
        
        return ToolResult(
            success=True,
            data={
                'summary': '\n'.join(output_lines),
                'files': result,
                'total_files': total_files,
                'total_lines': total_lines
            }
        )


class CheckDuplicatesTool(BaseTool):
    """
    Check for duplicate or similar files in the project.
    """
    
    NAME = "check_duplicates"
    
    DESCRIPTION = """Check for potentially duplicate files in the project.

Detects:
- Files with same name in different directories
- Similar file names (e.g., Layout.jsx vs MainLayout.jsx)
- Multiple implementations of the same component

Use this before creating new files to avoid duplicates.
"""
    
    def __init__(self, *, workspace: Workspace):
        super().__init__(name=self.NAME, category=ToolCategory.FILE)
        if workspace is None:
            raise ValueError(f"{self.NAME}: workspace is required (no bypass construction)")
        self.workspace = workspace
    
    @property
    def tool_definition(self):
        return create_tool_param(
            name=self.NAME,
            description=self.DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "file_name": {
                        "type": "string",
                        "description": "Specific file name to check (optional)"
                    }
                },
                "required": []
            }
        )
    
    def execute(self, file_name: Optional[str] = None) -> ToolResult:
        if not self.workspace.code_root.exists():
            return ToolResult(
                success=False,
                error_message="Output directory not found"
            )
        
        # Collect all files by name
        files_by_name: Dict[str, List[str]] = {}
        
        for file_path in self.workspace.code_root.rglob('*'):
            if file_path.is_file() and not file_path.name.startswith('.'):
                path_str = str(file_path)
                if any(p in path_str for p in ['node_modules', '__pycache__', '.git']):
                    continue
                
                name = file_path.name.lower()
                relative_path = str(self.workspace.relative(file_path))
                
                if name not in files_by_name:
                    files_by_name[name] = []
                files_by_name[name].append(relative_path)
        
        # Find duplicates
        duplicates = {}
        for name, paths in files_by_name.items():
            if len(paths) > 1:
                duplicates[name] = paths
        
        # Check for similar names (e.g., Header.jsx, AppHeader.jsx)
        similar = {}
        common_patterns = ['header', 'sidebar', 'layout', 'footer', 'nav', 'button', 'input', 'card']
        
        for pattern in common_patterns:
            matching = [
                (name, paths[0]) 
                for name, paths in files_by_name.items() 
                if pattern in name.lower()
            ]
            if len(matching) > 1:
                similar[pattern] = matching
        
        # If specific file_name requested, check for it
        if file_name:
            base_name = Path(file_name).stem.lower()
            matches = [
                path for name, paths in files_by_name.items() 
                for path in paths
                if base_name in name.lower()
            ]
            
            return ToolResult(
                success=True,
                data={
                    'query': file_name,
                    'matches': matches,
                    'has_duplicates': len(matches) > 0,
                    'message': f"Found {len(matches)} files similar to '{file_name}': {matches}" if matches else f"No files similar to '{file_name}' found."
                }
            )
        
        # General duplicate check
        issues = []
        if duplicates:
            issues.append(f"⚠️ DUPLICATE FILES ({len(duplicates)} groups):")
            for name, paths in duplicates.items():
                issues.append(f"  {name}:")
                for p in paths:
                    issues.append(f"    - {p}")
        
        if similar:
            issues.append(f"\n⚠️ SIMILAR FILES (potential duplicates):")
            for pattern, matches in similar.items():
                if len(matches) > 1:
                    issues.append(f"  '{pattern}' pattern:")
                    for name, path in matches:
                        issues.append(f"    - {path}")
        
        if not issues:
            issues.append("✅ No duplicate or similar files found.")
        
        return ToolResult(
            success=True,
            data={
                'duplicates': duplicates,
                'similar': similar,
                'has_issues': bool(duplicates or similar),
                'report': '\n'.join(issues)
            }
        )


def create_project_tools(*, workspace: Workspace) -> List[BaseTool]:
    """Create all project structure tools."""
    return [
        ProjectStructureTool(workspace=workspace),
        ListGeneratedFilesTool(workspace=workspace),
        CheckDuplicatesTool(workspace=workspace),
    ]

