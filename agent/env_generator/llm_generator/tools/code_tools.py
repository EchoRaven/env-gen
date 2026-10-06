"""
Code Tools - Search, edit, and analyze code

Provides:
- GrepTool: Regex content search
- LintTool: Syntax checking (Python, JavaScript, TypeScript)

File editing for agents uses `canonical_edit_tools` (`read` / `write` / `edit` / `apply_patch`).

For reasoning tools (think, plan), see reasoning_tools.py
For interaction tools (finish, deliver_project), see agent_interaction_tools.py
"""

import shutil
import subprocess

from ._base import (
    os,
    re,
    json,
    Path,
    Optional,
    BaseTool,
    ToolResult,
    ToolCategory,
    create_tool_param,
    Workspace,
)
from .file_tools import _resolve_workspace_path, _workspace_rel

# Re-export from split modules for backward compatibility
from .reasoning_tools import PlanTool, VerifyPlanTool
from .agent_interaction_tools import (
    ReadMemoryBankTool,
    FinishTool,
)
from .communication_tools import (
    SendMessageTool,
    AskAgentTool,
    BroadcastTool,
    CheckInboxTool,
    ListAgentsTool,
    SubscribeMessagesTool,
)
from typing import Optional


# ===== Grep Tool =====

class GrepTool(BaseTool):
    """
    Search file contents using regex.
    
    Inspired by OpenHands grep tool and SWE-agent search design.
    
    ACI Optimizations:
    - Result limit to prevent context explosion
    - Compact output format showing file (N matches)
    - Suggests narrowing query when too many results
    """
    
    NAME = "grep"
    
    DESCRIPTION = """Search file contents using regular expressions.

* Full regex support: "def\\s+\\w+", "class.*Model"
* Filter by file pattern: include="*.py"
* Shows file:line:content format
* Searches recursively
* Limits to 100 results to keep context manageable

Examples:
    grep "import" /src                    # Find all imports
    grep "def main" /src "*.py"           # Find main in Python files
    grep "TODO|FIXME" /project            # Find todos
"""
    
    MAX_RESULTS = 100
    MAX_LINE_LENGTH = 200
    MAX_FILES_MATCHED = 100  # SWE-agent style limit
    
    def __init__(self, *, workspace: Workspace):
        super().__init__(name=self.NAME, category=ToolCategory.CODE)
        if workspace is None:
            raise ValueError(f"{self.NAME}: workspace is required (no bypass construction)")
        self.workspace = workspace
    
    @property
    def tool_definition(self):
        return self.get_tool_param()
    
    def get_tool_param(self):
        return create_tool_param(
            name=self.NAME,
            description=self.DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Regex pattern to search for"
                    },
                    "path": {
                        "type": "string",
                        "description": "Directory or file search scope (default: workspace root)"
                    },
                    "include": {
                        "type": "string",
                        "description": "File pattern to include (e.g., '*.py')"
                    }
                },
                "required": ["pattern"]
            }
        )
    
    def execute(self, pattern: str, path: str = "", include: str = "*") -> ToolResult:
        # `path` is OPTIONAL (schema: "default: workspace root"). When omitted, search
        # the whole workspace — pass "." (NOT ""), since _resolve_workspace_path rejects
        # an empty path with "path is required". (Prior bug: search_scope computed "." but
        # the resolver was handed `path or ""` → an omitted path errored "grep: path is
        # required", so agents couldn't grep-by-pattern to LOCATE a file before reading.)
        search_scope = path or "."
        search_path, err = _resolve_workspace_path(
            self.workspace,
            search_scope,
            op_name="grep",
            must_exist=True,
            expect_file=None,
        )
        if err:
            return ToolResult(success=False, error_message=err)
        
        try:
            regex = re.compile(pattern)
        except re.error as e:
            return ToolResult(success=False, error_message=f"Invalid regex: {e}")
        
        results = []
        files_searched = 0
        files_with_matches = {}  # SWE-agent style: track matches per file
        
        # Determine files to search
        if search_path.is_file():
            files = [search_path]
        else:
            import fnmatch
            files = []
            for root, dirs, filenames in os.walk(search_path):
                # Skip hidden and common ignore dirs
                dirs[:] = [d for d in dirs if not d.startswith('.') and d not in 
                          ('node_modules', '__pycache__', 'venv', '.git', 'dist', 'build')]
                
                for f in filenames:
                    if fnmatch.fnmatch(f, include):
                        files.append(Path(root) / f)
        
        # Search files
        for file_path in files:
            files_searched += 1
            file_matches = 0
            
            try:
                with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                    for line_num, line in enumerate(f, 1):
                        if regex.search(line):
                            file_matches += 1
                            
                            if search_path.is_file():
                                rel_path = _workspace_rel(self.workspace, file_path)
                            else:
                                try:
                                    rel_path = str(file_path.relative_to(search_path))
                                except ValueError:
                                    rel_path = _workspace_rel(self.workspace, file_path)
                            
                            # Track per-file matches
                            if rel_path not in files_with_matches:
                                files_with_matches[rel_path] = 0
                            files_with_matches[rel_path] += 1
                            
                            line_content = line.strip()[:self.MAX_LINE_LENGTH]
                            results.append(f"{rel_path}:{line_num}: {line_content}")
                            
                            if len(results) >= self.MAX_RESULTS:
                                break
            except Exception:
                continue
            
            if len(results) >= self.MAX_RESULTS:
                break
        
        # === ACI Optimization: Check if too many files matched ===
        if len(files_with_matches) > self.MAX_FILES_MATCHED:
            # SWE-agent style: suggest narrowing search
            file_summary = [f"{f} ({n} matches)" for f, n in sorted(files_with_matches.items())[:20]]
            return ToolResult(
                success=True,
                data={
                    "matches": len(results),
                    "files_matched": len(files_with_matches),
                    "output": f"More than {self.MAX_FILES_MATCHED} files matched for \"{pattern}\" in {search_scope}. "
                              f"Please narrow your search.\n\nFirst 20 files:\n" + "\n".join(file_summary)
                }
            )
        
        if not results:
            return ToolResult(
                success=True,
                data={"matches": 0, "info": f"No matches for '{pattern}' in {search_scope} ({files_searched} files searched)"}
            )
        
        # SWE-agent style output: summary + detailed matches
        output = [f"Found {len(results)} matches for \"{pattern}\" in {search_scope}:"]
        
        # First show file summary (SWE-agent style)
        if len(files_with_matches) > 1:
            output.append("")
            output.append("Files with matches:")
            for f, n in sorted(files_with_matches.items()):
                output.append(f"  {f} ({n} matches)")
            output.append("")
        
        # Then show detailed matches
        output.append("Detailed matches:")
        output.extend(results)
        
        if len(results) >= self.MAX_RESULTS:
            output.append(f"\n... (showing first {self.MAX_RESULTS} results, more exist)")
        
        output.append(f"End of matches for \"{pattern}\" in {search_scope}")
        
        return ToolResult(
            success=True,
            data={"matches": len(results), "files_matched": len(files_with_matches), "output": "\n".join(output)}
        )


# ===== Lint Tool =====

class LintTool(BaseTool):
    """
    Enhanced lint tool using real linters (ruff, eslint, sqlfluff).
    Uses strict tool checks and returns explicit failures if unavailable.
    """
    
    NAME = "lint"
    
    DESCRIPTION = """Check code for syntax errors and style issues.

Supports:
- Python: Uses ruff (fast linter)
- JavaScript/TypeScript: Uses eslint if available
- JSON: Validates JSON structure
- SQL: Uses sqlfluff if available

Returns errors with line numbers and suggestions.
"""
    
    def __init__(self, *, workspace: Workspace):
        super().__init__(name=self.NAME, category=ToolCategory.CODE)
        if workspace is None:
            raise ValueError(f"{self.NAME}: workspace is required (no bypass construction)")
        self.workspace = workspace
        self._tool_cache = {}  # Cache which tools are available
        self._lint_cache_1203g5 = {}   # #1203g5: content-hash -> ToolResult
    
    @property
    def tool_definition(self):
        return self.get_tool_param()
    
    def get_tool_param(self):
        return create_tool_param(
            name=self.NAME,
            description=self.DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "File path to check"
                    }
                },
                "required": ["path"]
            }
        )
    
    def _check_tool_available(self, tool_name: str) -> bool:
        """Check if a linting tool is available."""
        if tool_name in self._tool_cache:
            return self._tool_cache[tool_name]
        
        # First check standard PATH
        available = shutil.which(tool_name) is not None

        # Check next to the running interpreter: Python-ecosystem tools (ruff,
        # black, mypy) install into the same bin/ as the python that imports
        # this module. The pipeline launches the interpreter by ABSOLUTE PATH
        # without the conda env on PATH, so shutil.which misses ruff even
        # though it's installed alongside (Instagram run #4: backend lint
        # spuriously reported "ruff is not available", wasting turns).
        if not available:
            import sys as _sys
            cand = Path(_sys.executable).resolve().parent / tool_name
            if cand.exists():
                available = True
                self._tool_cache[f"{tool_name}_path"] = str(cand)

        # Check nvm paths if not found
        if not available and tool_name in ['eslint', 'node', 'npm', 'npx']:
            nvm_dir = os.environ.get('NVM_DIR', os.path.expanduser('~/.nvm'))
            nvm_node_dir = Path(nvm_dir) / 'versions' / 'node'
            if nvm_node_dir.exists():
                # Find the latest node version
                node_versions = sorted(nvm_node_dir.iterdir(), reverse=True)
                for version_dir in node_versions:
                    tool_path = version_dir / 'bin' / tool_name
                    if tool_path.exists():
                        available = True
                        # Cache the full path for later use
                        self._tool_cache[f"{tool_name}_path"] = str(tool_path)
                        break
        
        self._tool_cache[tool_name] = available
        return available
    
    def _get_tool_path(self, tool_name: str) -> str:
        """Get the full path to a tool, checking nvm if needed."""
        # Check if we have a cached full path
        path_key = f"{tool_name}_path"
        if path_key in self._tool_cache:
            return self._tool_cache[path_key]
        
        # Try standard which
        path = shutil.which(tool_name)
        if path:
            return path
        
        # Check nvm
        nvm_dir = os.environ.get('NVM_DIR', os.path.expanduser('~/.nvm'))
        nvm_node_dir = Path(nvm_dir) / 'versions' / 'node'
        if nvm_node_dir.exists():
            node_versions = sorted(nvm_node_dir.iterdir(), reverse=True)
            for version_dir in node_versions:
                tool_path = version_dir / 'bin' / tool_name
                if tool_path.exists():
                    return str(tool_path)
        
        raise FileNotFoundError(f"Tool not found in PATH or NVM versions: {tool_name}")
    
    def execute(self, path: str) -> ToolResult:
        try:
            file_path = self.workspace.resolve(path)
        except Exception as e:
            return ToolResult(success=False, error_message=f"Invalid path: {e}")
        
        if not file_path.exists():
            return ToolResult(success=False, error_message=f"File not found: {path}")
        
        # #1203g5: LINTING THE SAME BYTES TWICE COSTS A SECOND AND ANSWERS THE SAME.
        #
        # `lint` is the single most expensive tool by wall clock in the corpus: of 7214s of
        # recorded tool time, 1156s is lint -- 16.0%, over 1165 calls at 992ms each. Measured
        # over r160-r164's agent logs with the writes attributed per file, 1004 of 1978 lint
        # calls (51%) re-lint a path that NOTHING has written since the previous lint, and
        # 1003 of those 1004 returned a byte-identical result. (The one exception is
        # `app/backend/main.py`, written by a DIFFERENT agent between the two calls -- which a
        # content hash handles correctly and a per-agent "unchanged?" flag would not.)
        #
        # 1003 x 992ms is ~16.6 minutes across five runs, ~3.3 per run, against a 7200s
        # per-milestone wall cap that r159 died on with zero delivery.
        #
        # The dedup of #1191 cannot help: it collapses a repeated RESULT in the context, and
        # lint results have a median length of 77 bytes -- far below its 1500-byte floor, whose
        # reasoning ("a pointer costs about as much as the body") is right for them. The cost
        # here is the subprocess, not the tokens, so the only way to not pay it is to not run it.
        #
        # Keyed on the CONTENT hash, not mtime: a hash cannot lie about a rewrite that kept the
        # timestamp, and `lint`'s only parameter is `path`, so identical bytes have no other
        # input that could change the verdict. Bounded so a long run cannot grow it without
        # limit; cleared wholesale rather than by age, because every entry is equally valid
        # while its hash matches.
        _cached_1203g5 = self._lint_cache_get_1203g5(file_path)
        if _cached_1203g5 is not None:
            return _cached_1203g5
        
        ext = file_path.suffix.lower()
        
        if ext == '.py':
            _res = self._lint_python(file_path)
        elif ext == '.json':
            _res = self._lint_json(file_path)
        elif ext in ['.js', '.jsx', '.ts', '.tsx']:
            _res = self._lint_javascript(file_path)
        elif ext == '.sql':
            _res = self._lint_sql(file_path)
        else:
            _res = ToolResult(
                success=True,
                data=f"No lint rules for {ext} files"
            )
        self._lint_cache_put_1203g5(file_path, _res)   # #1203g5
        return _res

    # ---- #1203g5 ---------------------------------------------------------------
    _LINT_CACHE_MAX_1203G5 = 256

    def _lint_content_key_1203g5(self, file_path) -> "str | None":
        """sha256 of the file's bytes, or None when it cannot be read.

        None disables the cache for this call rather than guessing a key -- a wrong key would
        serve one file's verdict for another's bytes, which is worse than paying the second.
        """
        try:
            import hashlib
            with open(file_path, "rb") as _fh:
                return hashlib.sha256(_fh.read()).hexdigest()
        except Exception:
            return None

    def _lint_cache_get_1203g5(self, file_path):
        """The verdict already computed for these exact bytes, or None."""
        try:
            _k = self._lint_content_key_1203g5(file_path)
            if not _k:
                return None
            _c = getattr(self, "_lint_cache_1203g5", None)
            if not isinstance(_c, dict):
                return None
            _hit = _c.get(_k)
            if _hit is None:
                return None
            # A COPY, not the stored object. #1203g4 had just been fixed for the same hazard
            # one layer up: a caller that annotates the result would otherwise be editing the
            # cache, and every later hit would serve the annotation as if lint had said it.
            # Lint reports have a median length of 77 bytes, so the copy is free beside the
            # ~992ms it replaces; a failure to copy returns None and pays the lint instead.
            try:
                import copy as _copy
                return _copy.deepcopy(_hit)
            except Exception:
                return None
        except Exception:
            return None

    def _lint_cache_put_1203g5(self, file_path, result) -> None:
        """Remember this verdict under the file's content hash. Never raises."""
        try:
            _k = self._lint_content_key_1203g5(file_path)
            if not _k or result is None:
                return
            _c = getattr(self, "_lint_cache_1203g5", None)
            if not isinstance(_c, dict):
                _c = {}
                self._lint_cache_1203g5 = _c
            if len(_c) >= self._LINT_CACHE_MAX_1203G5:
                _c.clear()
            _c[_k] = result
        except Exception:
            pass
    
    def _syntax_check_python_635(self, file_path: Path) -> ToolResult:
        """#635 — answer the question when ruff is absent, instead of refusing.

        `lint` on a Python file returned `success=False, "ruff is not available; install ruff to
        lint Python files."` — advice the agent cannot act on, in an environment where ruff is
        simply not installed. Sweeping the 56 run logs by error class, this fires **125 times in
        50 of 50 runs**: every run, every time, a turn spent learning nothing about the file.

        #705b VERIFIED 2026-08-14 against the full 253-log corpus. The premise was bigger than
        recorded — 1042 occurrences across 145 logs, not 125 across 50 — and, more usefully, the
        fix WORKS: era-split gives 496 in 90 logs before r100 and 456 in 42 after, and both
        post-fix runs are **0** (r145: 0, r146: 0). The string now survives in this file only as
        this docstring and the comment at :299; it is no longer a message anyone can receive.
        Recorded because a fix whose premise was never re-checked is indistinguishable from one
        that quietly stopped mattering.

        `ast.parse` needs no dependency and answers what the caller actually asked — *is this
        file valid?* — and a syntax error is exactly the failure that matters here: the corpus
        also carries 157 `write FAILED: your proposed edit has introduced syntax…` and P0s like
        "Frontend build fails — syntax error in GenreCategoryPage.jsx:35".

        Honest about its scope: the result says the style pass did not run, so a green verdict is
        never mistaken for a full lint.
        """
        import ast
        try:
            source = file_path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            return ToolResult(success=False, data={"errors": [], "tool": "syntax"},
                              error_message=f"could not read {file_path.name}: {exc}")
        try:
            ast.parse(source, filename=str(file_path))
        except SyntaxError as exc:
            err = {"line": exc.lineno or 0, "column": exc.offset or 0,
                   "code": "SyntaxError", "msg": exc.msg or "invalid syntax", "fix": None}
            return ToolResult(
                success=False, data={"errors": [err], "tool": "syntax"},
                error_message=(f"SyntaxError at L{err['line']}:{err['column']}: {err['msg']} "
                               f"(ruff unavailable — syntax checked only, no style rules)"))
        return ToolResult(success=True, data={
            "errors": [], "tool": "syntax",
            "message": (f"Python syntax OK: {file_path.name}. ruff is not installed in this "
                        f"environment, so STYLE rules were not run — do not read this as a "
                        f"full lint, and do not try to install ruff.")})

    def _lint_python(self, file_path: Path) -> ToolResult:
        """Lint Python using ruff, or fall back to a dependency-free syntax check (#635)."""
        if not self._check_tool_available('ruff'):
            return self._syntax_check_python_635(file_path)
        try:
            result = subprocess.run(
                [self._get_tool_path('ruff'), 'check', '--output-format=json', str(file_path)],
                capture_output=True,
                text=True,
                timeout=30,
                encoding='utf-8',
                errors='replace',
            )
            
            errors = []
            if result.stdout:
                try:
                    ruff_errors = json.loads(result.stdout)
                    for err in ruff_errors:
                        errors.append({
                            "line": err.get("location", {}).get("row", 0),
                            "column": err.get("location", {}).get("column", 0),
                            "code": err.get("code", ""),
                            "msg": err.get("message", ""),
                            "fix": err.get("fix", {}).get("message") if err.get("fix") else None
                        })
                except json.JSONDecodeError:
                    pass
            
            if errors:
                error_summary = "; ".join([f"L{e['line']}: [{e['code']}] {e['msg']}" for e in errors[:5]])
                return ToolResult(
                    success=False,
                    data={"errors": errors, "tool": "ruff"},
                    error_message=f"Found {len(errors)} issues: {error_summary}"
                )
            
            return ToolResult(
                success=True,
                data={"errors": [], "tool": "ruff", "message": f"Python lint OK: {file_path.name}"}
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False,
                data={"errors": [], "tool": "ruff"},
                error_message="ruff timed out"
            )
        except Exception as e:
            return ToolResult(
                success=False,
                data={"errors": [], "tool": "ruff"},
                error_message=f"ruff execution failed: {e}"
            )
    
    def _ensure_eslint_config(self, project_dir: Path) -> Optional[Path]:
        """
        Ensure an eslint config exists in the project directory.
        Creates a minimal config if none exists.
        Returns the path to config or None.
        """
        # Check for existing eslint configs (v9 flat config or legacy)
        config_files = [
            'eslint.config.js',
            'eslint.config.mjs', 
            '.eslintrc.js',
            '.eslintrc.json',
            '.eslintrc.yaml',
            '.eslintrc.yml',
            '.eslintrc'
        ]
        
        for config_file in config_files:
            config_path = project_dir / config_file
            if config_path.exists():
                return config_path
        
        # Create a minimal eslint config
        eslint_config = project_dir / 'eslint.config.js'
        eslint_config_content = '''// Auto-generated eslint config
import js from '@eslint/js';

export default [
  js.configs.recommended,
  {
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: 'module',
      globals: {
        // Node.js globals
        require: 'readonly',
        module: 'readonly',
        exports: 'readonly',
        process: 'readonly',
        __dirname: 'readonly',
        __filename: 'readonly',
        console: 'readonly',
        Buffer: 'readonly',
        setTimeout: 'readonly',
        setInterval: 'readonly',
        clearTimeout: 'readonly',
        clearInterval: 'readonly',
      }
    },
    rules: {
      'no-unused-vars': 'warn',
      'no-undef': 'error',
      'semi': ['warn', 'always'],
    }
  }
];
'''
        try:
            eslint_config.write_text(eslint_config_content)
            return eslint_config
        except Exception:
            return None
    
    def _lint_javascript(self, file_path: Path) -> ToolResult:
        """Lint JavaScript/TypeScript using eslint."""
        # Find the project root (where package.json is)
        project_dir = file_path.parent
        for _ in range(10):  # Max 10 levels up
            if (project_dir / 'package.json').exists():
                break
            if project_dir.parent == project_dir:
                break
            project_dir = project_dir.parent
        
        # Try global eslint first, then npx
        eslint_cmd = None
        if self._check_tool_available('eslint'):
            eslint_path = self._get_tool_path('eslint')
            eslint_cmd = [eslint_path]
        elif self._check_tool_available('npx'):
            npx_path = self._get_tool_path('npx')
            eslint_cmd = [npx_path, '--yes', 'eslint']
        
        if eslint_cmd:
            try:
                # Ensure eslint config exists
                self._ensure_eslint_config(project_dir)
                
                # Run eslint
                result = subprocess.run(
                    eslint_cmd + ['--format=json', str(file_path)],
                    capture_output=True,
                    text=True,
                    timeout=120,
                    cwd=project_dir,
                    encoding='utf-8',
                    errors='replace',
                )
                
                errors = []
                if result.stdout:
                    try:
                        eslint_result = json.loads(result.stdout)
                        for file_result in eslint_result:
                            for msg in file_result.get("messages", []):
                                errors.append({
                                    "line": msg.get("line", 0),
                                    "column": msg.get("column", 0),
                                    "code": msg.get("ruleId", ""),
                                    "msg": msg.get("message", ""),
                                    "severity": "error" if msg.get("severity") == 2 else "warning"
                                })
                    except json.JSONDecodeError:
                        # eslint might output non-JSON on certain errors
                        if result.returncode != 0 and result.stderr:
                            return ToolResult(
                                success=False,
                                data={"errors": [], "tool": "eslint"},
                                error_message=f"ESLint error: {result.stderr[:200]}"
                            )
                
                if errors:
                    error_summary = "; ".join([f"L{e['line']}: {e['msg']}" for e in errors[:5]])
                    return ToolResult(
                        success=False,
                        data={"errors": errors, "tool": "eslint"},
                        error_message=f"Found {len(errors)} issues: {error_summary}"
                    )
                
                return ToolResult(
                    success=True,
                    data={"errors": [], "tool": "eslint", "message": f"JS/TS lint OK: {file_path.name}"}
                )
            except subprocess.TimeoutExpired:
                return ToolResult(
                    success=False,
                    data={"errors": [], "tool": "eslint"},
                    error_message="ESLint timed out"
                )
            except Exception as e:
                pass
        
        return ToolResult(
            success=False,
            data={"errors": [], "tool": "none", "message": f"No JS linter available for: {file_path.name}"},
            error_message="No JavaScript linter available. Install eslint or ensure npx is available."
        )
    
    def _lint_sql(self, file_path: Path) -> ToolResult:
        """Lint SQL using sqlfluff."""
        if self._check_tool_available('sqlfluff'):
            try:
                result = subprocess.run(
                    ['sqlfluff', 'lint', '--format=json', str(file_path)],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    encoding='utf-8',
                    errors='replace',
                )
                
                errors = []
                if result.stdout:
                    try:
                        sqlfluff_result = json.loads(result.stdout)
                        for violation in sqlfluff_result:
                            for v in violation.get("violations", []):
                                errors.append({
                                    "line": v.get("start_line_no", 0),
                                    "column": v.get("start_line_pos", 0),
                                    "code": v.get("code", ""),
                                    "msg": v.get("description", "")
                                })
                    except json.JSONDecodeError:
                        pass
                
                if errors:
                    error_summary = "; ".join([f"L{e['line']}: [{e['code']}] {e['msg']}" for e in errors[:5]])
                    return ToolResult(
                        success=False,
                        data={"errors": errors, "tool": "sqlfluff"},
                        error_message=f"Found {len(errors)} issues: {error_summary}"
                    )
                
                return ToolResult(
                    success=True,
                    data={"errors": [], "tool": "sqlfluff", "message": f"SQL lint OK: {file_path.name}"}
                )
            except subprocess.TimeoutExpired:
                pass
            except Exception:
                pass
        
        # Fallback: no SQL linting
        return ToolResult(
            success=True,
            data={"errors": [], "tool": "none", "message": f"No SQL linter available for: {file_path.name}"}
        )
    
    def _lint_json(self, file_path: Path) -> ToolResult:
        """Lint JSON (basic validation)."""
        try:
            content = file_path.read_text(encoding='utf-8')
            json.loads(content)
            return ToolResult(
                success=True,
                data={"errors": [], "tool": "json", "message": f"JSON syntax OK: {file_path.name}"}
            )
        except json.JSONDecodeError as e:
            return ToolResult(
                success=False,
                data={"errors": [{"line": e.lineno, "column": e.colno, "msg": e.msg}], "tool": "json"},
                error_message=f"JSON error at line {e.lineno}: {e.msg}"
            )


# ============================================================================
# Exports
# ============================================================================

# Core tools defined in this file
__all__ = [
    # Core code tools (defined here)
    "GrepTool",
    "LintTool",
    
    # Re-exported from reasoning_tools.py
    "PlanTool",
    "VerifyPlanTool",
    
    # Re-exported from agent_interaction_tools.py
    "ReadMemoryBankTool",
    "FinishTool",
    
    # Re-exported from communication_tools.py
    "SendMessageTool",
    "AskAgentTool",
    "BroadcastTool",
    "CheckInboxTool",
    "ListAgentsTool",
    "SubscribeMessagesTool",
]


# NOTE: PlanTool, VerifyPlanTool are in reasoning_tools.py
# NOTE: ReadMemoryBankTool, FinishTool are in agent_interaction_tools.py
# NOTE: SendMessageTool, AskAgentTool, etc. are in communication_tools.py
# They are re-exported here for backward compatibility.
