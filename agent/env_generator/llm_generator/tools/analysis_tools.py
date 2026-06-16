"""
Code Analysis Tools

Tools for understanding code structure:
- find_definition: Find where a symbol is defined
- find_references: Find all usages of a symbol
- get_symbols: List functions/classes in a file
"""

import ast
import re
import sys
from pathlib import Path
from typing import List, Optional, Dict, Any, Union

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.tool import BaseTool, ToolResult, ToolCategory, create_tool_param
from workspace import Workspace


class FindDefinitionTool(BaseTool):
    """Find where a symbol (function, class, variable) is defined."""
    
    NAME = "find_definition"
    DESCRIPTION = """Find the definition of a symbol (function, class, variable).

Use this to understand where something is defined before modifying it.
Works with Python and JavaScript/TypeScript files.

Example:
  find_definition(symbol="UserModel", path="app/backend/src")
"""
    
    def __init__(self, *, workspace: Workspace):
        super().__init__(name=self.NAME, category=ToolCategory.CODE)
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
                    "symbol": {
                        "type": "string",
                        "description": "The symbol name to find (function, class, variable)"
                    },
                    "path": {
                        "type": "string",
                        "description": "Directory or file to search in (default: entire project)"
                    },
                },
                "required": ["symbol"],
            },
        )
    
    async def execute(self, symbol: str, path: str = "") -> ToolResult:
        search_path = self.workspace.resolve(path)
        
        if not search_path.exists():
            return ToolResult.fail(f"Path not found: {path or '.'}. Use relative paths like 'app/', 'docker/'")
        
        definitions = []
        
        # Patterns for different languages
        patterns = {
            ".py": [
                rf"^class\s+{re.escape(symbol)}\s*[\(:]",  # class Foo:
                rf"^def\s+{re.escape(symbol)}\s*\(",       # def foo(
                rf"^{re.escape(symbol)}\s*=",              # FOO = 
                rf"^async\s+def\s+{re.escape(symbol)}\s*\(",  # async def foo(
            ],
            ".js": [
                rf"^(export\s+)?(const|let|var|function|class)\s+{re.escape(symbol)}\b",
                rf"^(export\s+)?async\s+function\s+{re.escape(symbol)}\b",
                rf"^module\.exports\s*=.*{re.escape(symbol)}",
            ],
            ".jsx": [
                rf"^(export\s+)?(const|let|var|function|class)\s+{re.escape(symbol)}\b",
                rf"^(export\s+)?function\s+{re.escape(symbol)}\s*\(",
            ],
            ".ts": [
                rf"^(export\s+)?(const|let|var|function|class|interface|type)\s+{re.escape(symbol)}\b",
            ],
            ".tsx": [
                rf"^(export\s+)?(const|let|var|function|class|interface|type)\s+{re.escape(symbol)}\b",
            ],
        }
        
        files = search_path.rglob("*") if search_path.is_dir() else [search_path]
        
        for file_path in files:
            if not file_path.is_file():
                continue
            
            suffix = file_path.suffix.lower()
            if suffix not in patterns:
                continue
            
            # Skip node_modules, __pycache__, etc
            if any(p in str(file_path) for p in ["node_modules", "__pycache__", ".git", "venv"]):
                continue
            
            try:
                content = file_path.read_text(encoding="utf-8")
                lines = content.split("\n")
                
                for line_num, line in enumerate(lines, 1):
                    stripped = line.strip()
                    for pattern in patterns[suffix]:
                        if re.match(pattern, stripped, re.MULTILINE):
                            rel_path = self.workspace.relative(file_path)
                            definitions.append({
                                "file": str(rel_path),
                                "line": line_num,
                                "content": stripped[:100],
                            })
            except Exception:
                continue
        
        if not definitions:
            return ToolResult.ok(data={
                "symbol": symbol,
                "found": False,
                "message": f"No definition found for '{symbol}'"
            })
        
        return ToolResult.ok(data={
            "symbol": symbol,
            "found": True,
            "definitions": definitions,
            "count": len(definitions),
        })


class FindReferencesTool(BaseTool):
    """Find all references/usages of a symbol."""
    
    NAME = "find_references"
    DESCRIPTION = """Find all usages of a symbol in the codebase.

Use this to understand the impact of changing something.

Example:
  find_references(symbol="handleLogin", path="app/frontend/src")
"""
    
    def __init__(self, *, workspace: Workspace):
        super().__init__(name=self.NAME, category=ToolCategory.CODE)
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
                    "symbol": {
                        "type": "string",
                        "description": "The symbol name to find references for"
                    },
                    "path": {
                        "type": "string",
                        "description": "Directory or file to search in"
                    },
                },
                "required": ["symbol"],
            },
        )
    
    async def execute(self, symbol: str, path: str = "") -> ToolResult:
        search_path = self.workspace.resolve(path)
        
        if not search_path.exists():
            return ToolResult.fail(f"Path not found: {path or '.'}. Use relative paths like 'app/', 'docker/'")
        
        references = []
        extensions = {".py", ".js", ".jsx", ".ts", ".tsx", ".json", ".sql"}
        
        # Pattern to match symbol as a word
        pattern = re.compile(rf"\b{re.escape(symbol)}\b")
        
        files = search_path.rglob("*") if search_path.is_dir() else [search_path]
        
        for file_path in files:
            if not file_path.is_file():
                continue
            
            if file_path.suffix.lower() not in extensions:
                continue
            
            if any(p in str(file_path) for p in ["node_modules", "__pycache__", ".git", "venv"]):
                continue
            
            try:
                content = file_path.read_text(encoding="utf-8")
                lines = content.split("\n")
                
                for line_num, line in enumerate(lines, 1):
                    if pattern.search(line):
                        rel_path = self.workspace.relative(file_path)
                        references.append({
                            "file": str(rel_path),
                            "line": line_num,
                            "content": line.strip()[:100],
                        })
            except Exception:
                continue
        
        return ToolResult.ok(data={
            "symbol": symbol,
            "references": references,
            "count": len(references),
        })


class GetSymbolsTool(BaseTool):
    """List all functions, classes, and exports in a file."""
    
    NAME = "get_symbols"
    DESCRIPTION = """List all symbols (functions, classes, variables) defined in a file.

Use this to understand file structure before editing.

Example:
  get_symbols(file="app/backend/src/routes/auth.js")
"""
    
    def __init__(self, *, workspace: Workspace):
        super().__init__(name=self.NAME, category=ToolCategory.CODE)
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
                    "file": {
                        "type": "string",
                        "description": "Path to the file to analyze"
                    },
                },
                "required": ["file"],
            },
        )
    
    async def execute(self, file: str) -> ToolResult:
        file_path = self.workspace.resolve(file)
        
        if not file_path.exists():
            return ToolResult.fail(f"File not found: {file}")
        
        try:
            content = file_path.read_text(encoding="utf-8")
        except Exception as e:
            return ToolResult.fail(f"Error reading file: {e}")
        
        symbols = {
            "classes": [],
            "functions": [],
            "variables": [],
            "exports": [],
        }
        
        suffix = file_path.suffix.lower()
        
        if suffix == ".py":
            symbols = self._analyze_python(content)
        elif suffix in [".js", ".jsx", ".ts", ".tsx"]:
            symbols = self._analyze_javascript(content)
        else:
            return ToolResult.fail(f"Unsupported file type: {suffix}")
        
        return ToolResult.ok(data={
            "file": file,
            "symbols": symbols,
            "total": sum(len(v) for v in symbols.values()),
        })
    
    def _analyze_python(self, content: str) -> Dict[str, List]:
        symbols = {"classes": [], "functions": [], "variables": [], "exports": []}
        
        try:
            tree = ast.parse(content)
            
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    symbols["classes"].append({
                        "name": node.name,
                        "line": node.lineno,
                    })
                elif isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
                    # Only top-level functions
                    if hasattr(node, 'col_offset') and node.col_offset == 0:
                        symbols["functions"].append({
                            "name": node.name,
                            "line": node.lineno,
                            "async": isinstance(node, ast.AsyncFunctionDef),
                        })
                elif isinstance(node, ast.Assign):
                    if hasattr(node, 'col_offset') and node.col_offset == 0:
                        for target in node.targets:
                            if isinstance(target, ast.Name):
                                symbols["variables"].append({
                                    "name": target.id,
                                    "line": node.lineno,
                                })
        except SyntaxError:
            # Fall back to regex
            for match in re.finditer(r"^class\s+(\w+)", content, re.MULTILINE):
                symbols["classes"].append({"name": match.group(1)})
            for match in re.finditer(r"^(async\s+)?def\s+(\w+)", content, re.MULTILINE):
                symbols["functions"].append({"name": match.group(2)})
        
        return symbols
    
    def _analyze_javascript(self, content: str) -> Dict[str, List]:
        symbols = {"classes": [], "functions": [], "variables": [], "exports": []}
        
        # Classes
        for match in re.finditer(r"^(export\s+)?class\s+(\w+)", content, re.MULTILINE):
            symbols["classes"].append({
                "name": match.group(2),
                "exported": bool(match.group(1)),
            })
        
        # Functions
        for match in re.finditer(
            r"^(export\s+)?(async\s+)?function\s+(\w+)",
            content,
            re.MULTILINE
        ):
            symbols["functions"].append({
                "name": match.group(3),
                "exported": bool(match.group(1)),
                "async": bool(match.group(2)),
            })
        
        # Arrow functions / const functions
        for match in re.finditer(
            r"^(export\s+)?(const|let|var)\s+(\w+)\s*=\s*(async\s+)?\(?",
            content,
            re.MULTILINE
        ):
            symbols["variables"].append({
                "name": match.group(3),
                "exported": bool(match.group(1)),
            })
        
        # module.exports
        for match in re.finditer(r"module\.exports\s*=\s*(\w+)", content):
            symbols["exports"].append({"name": match.group(1)})
        
        return symbols


def create_analysis_tools(*, workspace: Workspace) -> List[BaseTool]:
    """Create all code analysis tools."""
    return [
        FindDefinitionTool(workspace=workspace),
        FindReferencesTool(workspace=workspace),
        GetSymbolsTool(workspace=workspace),
    ]

