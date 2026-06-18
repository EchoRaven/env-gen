"""
Shared workspace file helpers and non-canonical file tools.

Canonical LLM editing surface lives in `canonical_edit_tools.py` (`read`/`write`/`edit`/`apply_patch`).
This module provides path resolution, lint-on-write, JSON/YAML helpers, images, and glob search.
"""

import os
import re
import difflib
import subprocess
import hashlib
import json
import time
import shutil
from pathlib import Path
from typing import Optional, Union, Tuple, List, Dict, Any
from dataclasses import dataclass

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.tool import BaseTool, ToolResult, create_tool_param, ToolCategory
from workspace import Workspace


# ===== Unified Path Gateway =====

def _workspace_rel(workspace: Workspace, abs_path: Path) -> str:
    """Render an absolute path as workspace-relative for user-facing messages."""
    try:
        return str(abs_path.relative_to(workspace.root))
    except Exception:
        return str(abs_path)


def _path_not_found_hint(workspace: Workspace, resolved: Path, raw_path: str) -> str:
    """A 'did-you-mean' hint for a missing path.

    Agents guess conventional layouts (``app/backend/models.py``,
    ``backend/package.json``) that a given generated project may not use, then
    get a bare "path not found" and re-guess — burning rounds. So when a path
    doesn't exist, point at what DOES: list the nearest existing ancestor
    directory's entries (+ the closest-named match). Same spirit as the
    closest-granted-tool suggestion. Best-effort; never raises.
    """
    try:
        root = workspace.root
        anc = resolved.parent
        # Climb to the nearest existing directory, never above the workspace root
        # (resolve() guarantees `resolved` is inside root, so this terminates).
        while not anc.exists() and anc != root:
            anc = anc.parent
        if not anc.exists() or not anc.is_dir():
            return ""
        entries = sorted(
            p.name + ("/" if p.is_dir() else "")
            for p in anc.iterdir() if not p.name.startswith(".")
        )
        rel = _workspace_rel(workspace, anc) or "."
        if not entries:
            return f" (nearest existing dir '{rel}/' is empty)"
        shown = entries[:40]
        more = f" …(+{len(entries) - len(shown)} more)" if len(entries) > len(shown) else ""
        names = [e.rstrip("/") for e in entries]
        close = difflib.get_close_matches(Path(raw_path).name, names, n=1, cutoff=0.6)
        did = f"; did you mean '{close[0]}'?" if close else ""
        return f" (nearest existing dir '{rel}/' contains: {', '.join(shown)}{more}{did})"
    except Exception:
        return ""


def _resolve_workspace_path(
    workspace: Workspace,
    raw_path: Optional[str],
    *,
    op_name: str,
    must_exist: bool = False,
    expect_file: Optional[bool] = None,
) -> Tuple[Optional[Path], Optional[str]]:
    """
    Resolve and validate a workspace path with consistent errors.

    Args:
        workspace: Workspace instance
        raw_path: User-provided path
        op_name: Operation name for error context
        must_exist: Require path to already exist
        expect_file: True=file only, False=directory only, None=either
    """
    if raw_path is None or not str(raw_path).strip():
        return None, f"{op_name}: path is required"
    try:
        resolved = workspace.resolve(raw_path)
    except Exception as e:
        return None, f"{op_name}: invalid path '{raw_path}': {e}"

    if must_exist and not resolved.exists():
        return None, f"{op_name}: path not found: {raw_path}" + _path_not_found_hint(workspace, resolved, raw_path)
    if expect_file is True and resolved.exists() and not resolved.is_file():
        return None, f"{op_name}: expected file, got directory: {_workspace_rel(workspace, resolved)}"
    if expect_file is False and resolved.exists() and not resolved.is_dir():
        return None, f"{op_name}: expected directory, got file: {_workspace_rel(workspace, resolved)}"
    return resolved, None


# ===== Lint Utilities =====

def run_lint(file_path: Path) -> Tuple[bool, str]:
    """
    Run linter on a file and return (success, errors).
    
    Based on SWE-agent's lint guardrail - prevents syntax errors from propagating.
    """
    suffix = file_path.suffix.lower()
    
    if suffix == '.py':
        # Python: use flake8 for syntax errors
        try:
            result = subprocess.run(
                ['python3', '-m', 'py_compile', str(file_path)],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode != 0:
                return False, result.stderr.strip()
            return True, ""
        except subprocess.TimeoutExpired:
            return True, ""  # Timeout = assume OK
        except FileNotFoundError:
            return True, ""  # No python = skip
    
    elif suffix in ('.js', '.jsx', '.ts', '.tsx'):
        # JavaScript/TypeScript: basic syntax check
        try:
            if suffix in ('.ts', '.tsx'):
                # TypeScript - use tsc if available
                result = subprocess.run(
                    ['npx', 'tsc', '--noEmit', '--skipLibCheck', str(file_path)],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    cwd=file_path.parent
                )
            elif suffix == '.jsx':
                # `node --check` does not support JSX syntax and will
                # always fail with ERR_UNKNOWN_FILE_EXTENSION on .jsx files.
                # Skip parser-level lint here; downstream project lint/build
                # will still catch real syntax issues.
                return True, ""
            else:
                # JavaScript - use node syntax check
                result = subprocess.run(
                    ['node', '--check', str(file_path)],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
            if result.returncode != 0:
                # Extract just the error lines
                errors = result.stderr.strip() or result.stdout.strip()
                # Truncate long error messages
                if len(errors) > 500:
                    errors = errors[:500] + "..."
                return False, errors
            return True, ""
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return True, ""  # Skip if tools not available
    
    elif suffix == '.json':
        # JSON: validate syntax
        import json
        try:
            with open(file_path, 'r') as f:
                json.load(f)
            return True, ""
        except json.JSONDecodeError as e:
            return False, f"JSON syntax error at line {e.lineno}: {e.msg}"
    elif suffix in ('.yaml', '.yml'):
        try:
            import yaml
            with open(file_path, 'r', encoding='utf-8') as f:
                yaml.safe_load(f)
            return True, ""
        except Exception as e:
            return False, f"YAML syntax error: {e}"
    
    # Other files: no lint
    return True, ""


def format_lint_error(file_path: str, errors: str, new_content: str, old_content: str) -> str:
    """
    Format lint error message with context (SWE-agent style).
    
    Shows what the edit would have looked like and why it failed.
    """
    # Get snippet of new content around error
    lines = new_content.split('\n')
    snippet_start = max(0, len(lines) // 2 - 5)
    snippet_end = min(len(lines), len(lines) // 2 + 5)
    snippet = '\n'.join(f"{i+snippet_start+1:4}|{line}" for i, line in enumerate(lines[snippet_start:snippet_end]))
    
    return f"""Your proposed edit has introduced syntax error(s). Please fix and try again.

ERRORS:
{errors}

This is how your edit would have looked (partial):
------------------------------------------------
{snippet}
------------------------------------------------

Your changes have NOT been applied. Please fix the syntax error and try again.
DO NOT re-run the same failed edit command."""


# ===== File History =====

class FileHistory:
    """Singleton for file undo history."""
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._history = {}
            cls._instance.max_history = 10
        return cls._instance
    
    def save(self, path: str, content: str):
        if path not in self._history:
            self._history[path] = []
        self._history[path].append(content)
        if len(self._history[path]) > self.max_history:
            self._history[path] = self._history[path][-self.max_history:]
    
    def get_previous(self, path: str) -> Optional[str]:
        if path in self._history and self._history[path]:
            return self._history[path].pop()
        return None
    
    def clear(self, path: str = None):
        if path:
            self._history.pop(path, None)
        else:
            self._history.clear()


_file_history = FileHistory()


@dataclass
class _FileReadSnapshot:
    content: str
    timestamp: float
    full_read: bool = True


_file_read_state: Dict[str, _FileReadSnapshot] = {}


def _get_file_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except Exception:
        return time.time()


def _record_file_read(path: Path, content: str, *, full_read: bool = True) -> None:
    _file_read_state[str(path)] = _FileReadSnapshot(
        content=content,
        timestamp=_get_file_mtime(path),
        full_read=full_read,
    )


def _record_file_write(path: Path, content: str) -> None:
    _file_read_state[str(path)] = _FileReadSnapshot(
        content=content,
        timestamp=_get_file_mtime(path),
        full_read=True,
    )


def _check_stale_write_guard(path: Path, current_content: str) -> Optional[str]:
    """
    Guard against blind overwrite:
    - Existing file must be read before write
    - If file changed after last read, reject unless full-read content still matches
    """
    if not path.exists():
        return None
    snap = _file_read_state.get(str(path))
    if not snap:
        return (
            f"Refusing to overwrite existing file without prior read: {path}. "
            "Call `read` on this file first, then retry."
        )
    current_mtime = _get_file_mtime(path)
    if current_mtime > snap.timestamp:
        if not snap.full_read or snap.content != current_content:
            return (
                f"File changed since last read: {path}. "
                "Re-read the file and retry to avoid clobbering concurrent edits."
            )
    return None


def _atomic_write_text(path: Path, content: str, *, encoding: str = "utf-8") -> None:
    """Atomic text write via temp file + replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.parent / f".{path.name}.tmp.{os.getpid()}.{int(time.time() * 1000)}"
    try:
        with open(temp_path, "w", encoding=encoding) as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, path)
    finally:
        try:
            if temp_path.exists():
                temp_path.unlink()
        except Exception:
            pass


class _FileLock:
    """Simple lockfile guard for cross-process writes."""

    def __init__(self, path: Path, timeout_seconds: float = 5.0):
        self._lock_path = path.parent / f".{path.name}.lock"
        self._timeout = max(0.1, float(timeout_seconds))
        self._fd: Optional[int] = None

    def __enter__(self):
        start = time.time()
        while True:
            try:
                self._fd = os.open(str(self._lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(self._fd, f"{os.getpid()} {int(time.time())}\n".encode("utf-8"))
                return self
            except FileExistsError:
                if time.time() - start >= self._timeout:
                    raise TimeoutError(f"Timeout acquiring file lock: {self._lock_path}")
                time.sleep(0.05)

    def __exit__(self, exc_type, exc, tb):
        try:
            if self._fd is not None:
                os.close(self._fd)
        except Exception:
            pass
        try:
            if self._lock_path.exists():
                self._lock_path.unlink()
        except Exception:
            pass


def _is_protected_delete_path(workspace: Workspace, file_path: Path) -> bool:
    rel = _workspace_rel(workspace, file_path).replace("\\", "/").lstrip("./")
    protected_prefixes = (".git/", ".cursor/", ".openenv_trash/")
    return rel == ".git" or rel.startswith(protected_prefixes)


def _move_to_trash(workspace: Workspace, file_path: Path) -> Path:
    # Per-agent scratch — trash is isolated to each worktree, never
    # routed to the shared base root.
    trash_root = workspace.code_root / ".openenv_trash"
    trash_root.mkdir(parents=True, exist_ok=True)
    rel = _workspace_rel(workspace, file_path).replace("\\", "/").strip("/") or file_path.name
    safe_rel = rel.replace("/", "__")
    stamp = int(time.time() * 1000)
    trash_path = trash_root / f"{safe_rel}.{stamp}.deleted"
    shutil.move(str(file_path), str(trash_path))
    return trash_path


# ===== Structured JSON Edit Tool =====

class UpdateJsonPathTool(BaseTool):
    """Update a JSON file at a specific object/array path."""

    NAME = "update_json_path"

    DESCRIPTION = """Update a JSON file by structured path, avoiding fragile string replacement.

Path syntax:
- Dot notation for object keys: `a.b.c`
- Bracket index for arrays: `items[0].name`

Actions:
- `set`: set/replace value at path
- `delete`: delete key/index at path

Examples:
    update_json_path(path="design/spec.api.json", json_path="meta.version", action="set", value="1.2.0")
    update_json_path(path="package.json", json_path="scripts.lint", action="set", value="eslint .")
    update_json_path(path="data.json", json_path="items[1]", action="delete")
"""

    def __init__(self, *, workspace: Workspace):
        super().__init__(name=self.NAME, category=ToolCategory.FILE)
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
                    "path": {
                        "type": "string",
                        "description": "JSON file path"
                    },
                    "json_path": {
                        "type": "string",
                        "description": "Path inside JSON (e.g. a.b[0].c)"
                    },
                    "action": {
                        "type": "string",
                        "enum": ["set", "delete"],
                        "description": "Operation type (default: set)"
                    },
                    "value": {
                        "description": "Value for set action (any valid JSON value)"
                    },
                    "create_missing": {
                        "type": "boolean",
                        "description": "Create missing intermediate keys/arrays (default: true)"
                    }
                },
                "required": ["path", "json_path"]
            }
        )

    def _parse_json_path(self, json_path: str) -> Tuple[Optional[List[Union[str, int]]], Optional[str]]:
        if not json_path or not str(json_path).strip():
            return None, "json_path is required"
        tokens: List[Union[str, int]] = []
        # matches either dot-segment token or [index]
        pattern = re.compile(r"([^\.\[\]]+)|\[(\d+)\]")
        for match in pattern.finditer(json_path.strip()):
            key, idx = match.groups()
            if key is not None:
                tokens.append(key)
            elif idx is not None:
                tokens.append(int(idx))
        if not tokens:
            return None, f"Invalid json_path: {json_path}"
        return tokens, None

    def _apply_set(
        self,
        doc: Any,
        tokens: List[Union[str, int]],
        value: Any,
        create_missing: bool,
    ) -> Tuple[bool, Optional[str]]:
        cur = doc
        for i, tok in enumerate(tokens):
            is_last = i == len(tokens) - 1
            nxt = tokens[i + 1] if not is_last else None

            if isinstance(tok, str):
                if not isinstance(cur, dict):
                    return False, f"Path segment '{tok}' expects object parent, got {type(cur).__name__}"
                if is_last:
                    cur[tok] = value
                    return True, None
                if tok not in cur:
                    if not create_missing:
                        return False, f"Missing key '{tok}' and create_missing=false"
                    cur[tok] = [] if isinstance(nxt, int) else {}
                cur = cur[tok]
            else:
                if not isinstance(cur, list):
                    return False, f"Path index [{tok}] expects array parent, got {type(cur).__name__}"
                if tok < 0:
                    return False, "Negative array index is not supported"
                if tok >= len(cur):
                    if not create_missing:
                        return False, f"Index [{tok}] out of range and create_missing=false"
                    while len(cur) <= tok:
                        cur.append(None)
                if is_last:
                    cur[tok] = value
                    return True, None
                if cur[tok] is None or not isinstance(cur[tok], (dict, list)):
                    if not create_missing:
                        return False, f"Index [{tok}] is not container and create_missing=false"
                    cur[tok] = [] if isinstance(nxt, int) else {}
                cur = cur[tok]
        return False, "Invalid path"

    def _apply_delete(self, doc: Any, tokens: List[Union[str, int]]) -> Tuple[bool, Optional[str]]:
        if not tokens:
            return False, "json_path is required"
        cur = doc
        for tok in tokens[:-1]:
            if isinstance(tok, str):
                if not isinstance(cur, dict) or tok not in cur:
                    return False, f"Missing key '{tok}'"
                cur = cur[tok]
            else:
                if not isinstance(cur, list) or tok < 0 or tok >= len(cur):
                    return False, f"Index [{tok}] out of range"
                cur = cur[tok]

        last = tokens[-1]
        if isinstance(last, str):
            if not isinstance(cur, dict) or last not in cur:
                return False, f"Missing key '{last}'"
            del cur[last]
        else:
            if not isinstance(cur, list) or last < 0 or last >= len(cur):
                return False, f"Index [{last}] out of range"
            del cur[last]
        return True, None

    def execute(
        self,
        path: str,
        json_path: str,
        action: str = "set",
        value: Any = None,
        create_missing: bool = True,
    ) -> ToolResult:
        file_path, err = _resolve_workspace_path(
            self.workspace,
            path,
            op_name="update_json_path",
            must_exist=True,
            expect_file=True,
        )
        if err:
            return ToolResult(success=False, error_message=err)
        if file_path.suffix.lower() != ".json":
            return ToolResult(success=False, error_message=f"update_json_path requires .json file: {path}")

        tokens, parse_err = self._parse_json_path(json_path)
        if parse_err:
            return ToolResult(success=False, error_message=parse_err)

        try:
            old_content = file_path.read_text(encoding="utf-8")
            _record_file_read(file_path, old_content, full_read=True)
            doc = json.loads(old_content)
        except Exception as e:
            return ToolResult(success=False, error_message=f"Failed to read/parse JSON: {e}")

        if action not in {"set", "delete"}:
            return ToolResult(success=False, error_message=f"Unsupported action: {action}")
        if action == "set":
            ok, apply_err = self._apply_set(doc, tokens, value, bool(create_missing))
        else:
            ok, apply_err = self._apply_delete(doc, tokens)
        if not ok:
            return ToolResult(success=False, error_message=f"Failed to apply JSON edit: {apply_err}")

        _file_history.save(str(file_path), old_content)
        stale_err = _check_stale_write_guard(file_path, old_content)
        if stale_err:
            return ToolResult(success=False, error_message=stale_err)
        try:
            new_content = json.dumps(doc, ensure_ascii=False, indent=2) + "\n"
            with _FileLock(file_path):
                stale_err = _check_stale_write_guard(file_path, old_content)
                if stale_err:
                    return ToolResult(success=False, error_message=stale_err)
                _atomic_write_text(file_path, new_content, encoding="utf-8")
                lint_ok, lint_errors = run_lint(file_path)
                if not lint_ok:
                    _atomic_write_text(file_path, old_content, encoding="utf-8")
                    return ToolResult(
                        success=False,
                        error_message=f"Edit reverted due to lint failure: {lint_errors}"
                    )
            _record_file_write(file_path, new_content)
            try:
                from tools.canonical_file_tools.shared import sync_hub_write

                sync_hub_write(
                    tool=self,
                    workspace=self.workspace,
                    path=file_path,
                    updated_content=new_content,
                    original_content=old_content,
                    operation="json_path_update",
                    metadata={"json_path": json_path, "action": action},
                )
            except Exception:
                pass
            return ToolResult(
                success=True,
                data={
                    "path": _workspace_rel(self.workspace, file_path),
                    "action": action,
                    "json_path": json_path,
                    "info": f"JSON updated: {json_path} ({action})",
                },
            )
        except Exception as e:
            try:
                _atomic_write_text(file_path, old_content, encoding="utf-8")
            except Exception:
                pass
            return ToolResult(success=False, error_message=f"JSON update failed: {e}")


# ===== Structured YAML Edit Tool =====

class UpdateYamlPathTool(BaseTool):
    """Update a YAML file at a specific object/array path."""

    NAME = "update_yaml_path"

    DESCRIPTION = """Update a YAML file by structured path, avoiding fragile string replacement.

Path syntax:
- Dot notation for object keys: `a.b.c`
- Bracket index for arrays: `items[0].name`

Actions:
- `set`: set/replace value at path
- `delete`: delete key/index at path
"""

    def __init__(self, *, workspace: Workspace):
        super().__init__(name=self.NAME, category=ToolCategory.FILE)
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
                    "path": {"type": "string", "description": "YAML file path"},
                    "yaml_path": {"type": "string", "description": "Path inside YAML (e.g. a.b[0].c)"},
                    "action": {
                        "type": "string",
                        "enum": ["set", "delete"],
                        "description": "Operation type (default: set)"
                    },
                    "value": {"description": "Value for set action (any valid YAML value)"},
                    "create_missing": {
                        "type": "boolean",
                        "description": "Create missing intermediate keys/arrays (default: true)"
                    },
                },
                "required": ["path", "yaml_path"],
            },
        )

    def _parse_yaml_path(self, yaml_path: str) -> Tuple[Optional[List[Union[str, int]]], Optional[str]]:
        if not yaml_path or not str(yaml_path).strip():
            return None, "yaml_path is required"
        tokens: List[Union[str, int]] = []
        pattern = re.compile(r"([^\.\[\]]+)|\[(\d+)\]")
        for match in pattern.finditer(yaml_path.strip()):
            key, idx = match.groups()
            if key is not None:
                tokens.append(key)
            elif idx is not None:
                tokens.append(int(idx))
        if not tokens:
            return None, f"Invalid yaml_path: {yaml_path}"
        return tokens, None

    def _apply_set(self, doc: Any, tokens: List[Union[str, int]], value: Any, create_missing: bool) -> Tuple[bool, Optional[str]]:
        cur = doc
        for i, tok in enumerate(tokens):
            is_last = i == len(tokens) - 1
            nxt = tokens[i + 1] if not is_last else None
            if isinstance(tok, str):
                if not isinstance(cur, dict):
                    return False, f"Path segment '{tok}' expects object parent, got {type(cur).__name__}"
                if is_last:
                    cur[tok] = value
                    return True, None
                if tok not in cur:
                    if not create_missing:
                        return False, f"Missing key '{tok}' and create_missing=false"
                    cur[tok] = [] if isinstance(nxt, int) else {}
                cur = cur[tok]
            else:
                if not isinstance(cur, list):
                    return False, f"Path index [{tok}] expects array parent, got {type(cur).__name__}"
                if tok < 0:
                    return False, "Negative array index is not supported"
                if tok >= len(cur):
                    if not create_missing:
                        return False, f"Index [{tok}] out of range and create_missing=false"
                    while len(cur) <= tok:
                        cur.append(None)
                if is_last:
                    cur[tok] = value
                    return True, None
                if cur[tok] is None or not isinstance(cur[tok], (dict, list)):
                    if not create_missing:
                        return False, f"Index [{tok}] is not container and create_missing=false"
                    cur[tok] = [] if isinstance(nxt, int) else {}
                cur = cur[tok]
        return False, "Invalid path"

    def _apply_delete(self, doc: Any, tokens: List[Union[str, int]]) -> Tuple[bool, Optional[str]]:
        if not tokens:
            return False, "yaml_path is required"
        cur = doc
        for tok in tokens[:-1]:
            if isinstance(tok, str):
                if not isinstance(cur, dict) or tok not in cur:
                    return False, f"Missing key '{tok}'"
                cur = cur[tok]
            else:
                if not isinstance(cur, list) or tok < 0 or tok >= len(cur):
                    return False, f"Index [{tok}] out of range"
                cur = cur[tok]
        last = tokens[-1]
        if isinstance(last, str):
            if not isinstance(cur, dict) or last not in cur:
                return False, f"Missing key '{last}'"
            del cur[last]
        else:
            if not isinstance(cur, list) or last < 0 or last >= len(cur):
                return False, f"Index [{last}] out of range"
            del cur[last]
        return True, None

    def execute(
        self,
        path: str,
        yaml_path: str,
        action: str = "set",
        value: Any = None,
        create_missing: bool = True,
    ) -> ToolResult:
        file_path, err = _resolve_workspace_path(
            self.workspace,
            path,
            op_name="update_yaml_path",
            must_exist=True,
            expect_file=True,
        )
        if err:
            return ToolResult(success=False, error_message=err)
        if file_path.suffix.lower() not in {".yaml", ".yml"}:
            return ToolResult(success=False, error_message=f"update_yaml_path requires .yaml/.yml file: {path}")

        tokens, parse_err = self._parse_yaml_path(yaml_path)
        if parse_err:
            return ToolResult(success=False, error_message=parse_err)

        try:
            import yaml
        except Exception as e:
            return ToolResult(success=False, error_message=f"YAML support unavailable: {e}")

        try:
            old_content = file_path.read_text(encoding="utf-8")
            _record_file_read(file_path, old_content, full_read=True)
            doc = yaml.safe_load(old_content)
            if doc is None:
                doc = {}
        except Exception as e:
            return ToolResult(success=False, error_message=f"Failed to read/parse YAML: {e}")

        if action not in {"set", "delete"}:
            return ToolResult(success=False, error_message=f"Unsupported action: {action}")
        if action == "set":
            ok, apply_err = self._apply_set(doc, tokens, value, bool(create_missing))
        else:
            ok, apply_err = self._apply_delete(doc, tokens)
        if not ok:
            return ToolResult(success=False, error_message=f"Failed to apply YAML edit: {apply_err}")

        _file_history.save(str(file_path), old_content)
        try:
            new_content = yaml.safe_dump(doc, sort_keys=False, allow_unicode=True)
            if not new_content.endswith("\n"):
                new_content += "\n"
            with _FileLock(file_path):
                stale_err = _check_stale_write_guard(file_path, old_content)
                if stale_err:
                    return ToolResult(success=False, error_message=stale_err)
                _atomic_write_text(file_path, new_content, encoding="utf-8")
                lint_ok, lint_errors = run_lint(file_path)
                if not lint_ok:
                    _atomic_write_text(file_path, old_content, encoding="utf-8")
                    return ToolResult(
                        success=False,
                        error_message=f"Edit reverted due to lint failure: {lint_errors}"
                    )
            _record_file_write(file_path, new_content)
            try:
                from tools.canonical_file_tools.shared import sync_hub_write

                sync_hub_write(
                    tool=self,
                    workspace=self.workspace,
                    path=file_path,
                    updated_content=new_content,
                    original_content=old_content,
                    operation="yaml_path_update",
                    metadata={"yaml_path": yaml_path, "action": action},
                )
            except Exception:
                pass
            return ToolResult(
                success=True,
                data={
                    "path": _workspace_rel(self.workspace, file_path),
                    "action": action,
                    "yaml_path": yaml_path,
                    "info": f"YAML updated: {yaml_path} ({action})",
                },
            )
        except Exception as e:
            try:
                _atomic_write_text(file_path, old_content, encoding="utf-8")
            except Exception:
                pass
            return ToolResult(success=False, error_message=f"YAML update failed: {e}")


# ===== View Image Tool =====

import base64

# Mechanism #41: oversized reference images are downscaled+recompressed ONCE
# and cached (keyed by path+mtime+size), so repeated view_image calls neither
# re-read multi-MB files nor push needless pixels at the model. The cache
# lives in /tmp — never inside the generated project.
_IMAGE_CACHE_DIR = Path("/tmp/envgen_image_cache")
_COMPRESS_RAW_BYTES = 1 * 1024 * 1024   # compress when the file exceeds 1MB…
_COMPRESS_MAX_SIDE = 2000               # …or its longest side exceeds this
_TARGET_MAX_SIDE = 1568                 # standard vision-input long side


def _compressed_image_for_llm(image_path: Path) -> Optional[Path]:
    """Return a cached, LLM-sized JPEG/PNG for ``image_path`` (or None when
    the original is already small — caller uses it directly). Best-effort:
    any failure returns None and the caller falls back to the original."""
    try:
        from PIL import Image
    except Exception:
        return None
    try:
        raw_size = image_path.stat().st_size
        with Image.open(image_path) as im:
            w, h = im.size
            if raw_size <= _COMPRESS_RAW_BYTES and max(w, h) <= _COMPRESS_MAX_SIDE:
                return None
            st = image_path.stat()
            key = hashlib.sha1(
                f"{image_path.resolve()}|{st.st_mtime_ns}|{st.st_size}".encode()
            ).hexdigest()[:24]
            has_alpha = im.mode in ("RGBA", "LA", "P")
            ext = ".png" if has_alpha else ".jpg"
            _IMAGE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cached = _IMAGE_CACHE_DIR / f"{key}{ext}"
            if cached.exists():
                return cached
            im.thumbnail((_TARGET_MAX_SIDE, _TARGET_MAX_SIDE))
            if has_alpha:
                im.convert("RGBA").save(cached, format="PNG", optimize=True)
            else:
                im.convert("RGB").save(cached, format="JPEG",
                                       quality=85, optimize=True)
            return cached
    except Exception:
        return None


def _encode_image_to_base64(image_path: Path) -> Optional[str]:
    """Encode image file to base64 string"""
    if not image_path.exists():
        return None
    try:
        with open(image_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")
    except Exception:
        return None

def _get_image_mime_type(image_path: Path) -> str:
    """Get MIME type from file extension"""
    ext = image_path.suffix.lower()
    mime_map = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".svg": "image/svg+xml",
    }
    return mime_map.get(ext, "image/png")


class ViewImageTool(BaseTool):
    """View/load an image file for design reference.
    
    This tool loads images (screenshots, mockups, design references) and makes them
    available for the LLM to analyze. The image is returned as base64 for multimodal
    LLM processing.
    """
    
    NAME = "view_image"
    
    DESCRIPTION = """Load an image file (screenshot, mockup, design reference) for analysis.

Use this tool to:
- Load a reference screenshot to recreate a design
- View a mockup image to understand the expected UI
- Compare with generated screenshots

Supported formats: PNG, JPG, JPEG, GIF, WebP, SVG

Examples:
    view_image "design/mockup.png"              # Load a design mockup
    view_image "screenshots/reference.jpg"      # Load a reference screenshot
    view_image "ui-spec/dashboard.png"          # Load UI specification image

By default, this tool returns ONLY metadata (path, size, mime) to avoid exploding LLM context.
If you truly need the raw base64 payload, pass include_base64=true (WARNING: huge).
"""
    
    def __init__(self, *, workspace: Workspace):
        super().__init__(name=self.NAME, category=ToolCategory.FILE)
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
                    "path": {
                        "type": "string",
                        "description": "Path to the image file (relative to workspace or absolute)"
                    },
                    "description": {
                        "type": "string",
                        "description": "Optional description of what to look for in the image"
                    },
                    "include_base64": {
                        "type": "boolean",
                        "description": "Include base64 payload in tool output (WARNING: very large). Default: false."
                    }
                },
                "required": ["path"]
            }
        )
    
    def _fuzzy_match_file(self, target_dir: Path, filename: str) -> Optional[Path]:
        """Try to find a file with fuzzy matching (handles missing/extra spaces)."""
        if not target_dir.exists():
            return None
        
        # Normalize: remove all spaces for comparison
        normalized_target = filename.replace(" ", "").lower()
        
        for file in target_dir.iterdir():
            if file.is_file():
                normalized_file = file.name.replace(" ", "").lower()
                if normalized_file == normalized_target:
                    return file
        
        return None
    
    def execute(self, path: str = None, description: str = None,
                include_base64: bool = False, **alias_kwargs) -> ToolResult:
        # Param-name tolerance (mechanism #40): real-LLM calls write the
        # argument as image_path/file_path/image — a hard TypeError here cost
        # the frontend its ONLY look at the reference designs (round 32).
        if not path:
            for k in ("image_path", "file_path", "image", "filename"):
                if alias_kwargs.get(k):
                    path = alias_kwargs[k]
                    break
        if not path:
            return ToolResult(success=False, error_message=(
                "view_image requires `path` (the image file path)."))
        image_path, err = _resolve_workspace_path(
            self.workspace,
            path,
            op_name="view_image",
            must_exist=False,
            expect_file=True,
        )
        if err:
            return ToolResult(success=False, error_message=err)
        
        if not image_path.exists():
            # No more multi-candidate guess loop — the workspace's
            # routing table is the authoritative source for where a
            # given prefix lives. If ``view_image('login.png')`` doesn't
            # find anything, the caller meant a path that doesn't exist
            # at that route. Give them the available images so they can
            # pick the right path on the next call.
            suggestions: list = []
            for prefix in ("screenshots", "references", "mockups", "design", "images"):
                prefix_dir = self.workspace.resolve(prefix)
                if prefix_dir.exists() and prefix_dir.is_dir():
                    for f in prefix_dir.iterdir():
                        if f.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}:
                            suggestions.append(f"{prefix}/{f.name}")
            suggestion_text = ""
            if suggestions:
                suggestion_text = f" Available images: {', '.join(suggestions[:5])}"
                if len(suggestions) > 5:
                    suggestion_text += f" ... and {len(suggestions) - 5} more"
            return ToolResult(
                success=False,
                error_message=(
                    f"Image not found: {path}. "
                    f"Use ``list_reference_images()`` first to discover the available "
                    f"paths.{suggestion_text}"
                ),
            )
        
        # Check if it's a supported image format
        supported_exts = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}
        if image_path.suffix.lower() not in supported_exts:
            return ToolResult(
                success=False,
                error_message=f"Unsupported image format: {image_path.suffix}. Supported: {supported_exts}"
            )
        
        # Get file size
        file_size = image_path.stat().st_size
        if file_size > 20 * 1024 * 1024:  # 20MB limit
            return ToolResult(
                success=False,
                error_message=f"Image too large: {file_size / 1024 / 1024:.1f}MB. Maximum: 20MB"
            )
        
        mime_type = _get_image_mime_type(image_path)

        # Mechanism #40: the PIXELS are the point of this tool. Always build
        # the multimodal part (the step runner extracts it from the result
        # dict and injects it as a multimodal message — it never lands in the
        # stringified tool output). ``image_base64`` raw text stays opt-in.
        # Mechanism #41: oversized images are downscaled+cached first.
        payload = {}
        send_path, send_mime = image_path, mime_type
        if image_path.suffix.lower() != ".svg":
            cached = _compressed_image_for_llm(image_path)
            if cached is not None:
                send_path = cached
                send_mime = _get_image_mime_type(cached)
                payload["compressed"] = {
                    "cache_path": str(cached),
                    "original_bytes": file_size,
                    "compressed_bytes": cached.stat().st_size,
                }
            if send_path.stat().st_size <= 6 * 1024 * 1024:
                image_base64 = _encode_image_to_base64(send_path)
                if image_base64:
                    payload["multimodal_content"] = {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{send_mime};base64,{image_base64}",
                            "detail": "high"
                        }
                    }
                    if include_base64:
                        payload["image_base64"] = image_base64
        if "multimodal_content" not in payload:
            payload["note"] = ("image could not be inlined (SVG, or >6MB even "
                               "after compression) — only metadata returned")

        return ToolResult(
            success=True,
            data={
                "path": _workspace_rel(self.workspace, image_path),
                "mime_type": mime_type,
                "size_bytes": file_size,
                "size_display": f"{file_size / 1024:.1f}KB" if file_size < 1024*1024 else f"{file_size / 1024 / 1024:.1f}MB",
                "description": description,
                "message": f"Image loaded: {_workspace_rel(self.workspace, image_path)} ({mime_type}, {file_size / 1024:.1f}KB)",
                **payload
            }
        )


# ===== List Reference Images Tool =====

class ListReferenceImagesTool(BaseTool):
    """List available reference images from the screenshot library."""
    
    NAME = "list_reference_images"
    
    DESCRIPTION = """List available reference images from the screenshot library.

The screenshot library contains design references, UI mockups, and component examples
that can be used as reference for generating web pages.

Examples:
    list_reference_images                        # List runtime workspace screenshots and bundled projects
    list_reference_images "screenshots"          # List images copied into the current workspace
    list_reference_images "atlassian_home"       # List bundled library project images

When the run starts with --reference-dir, images are already copied into
workspace/screenshots. Prefer view_image("screenshots/<name>.png") for those.
Use copy_reference_image only for bundled library images that are not yet in the workspace.
"""
    
    # Default screenshot library path (relative to llm_generator)
    SCREENSHOT_LIB_PATH = Path(__file__).parent.parent / "screenshot"
    
    def __init__(self, *, workspace: Workspace, screenshot_lib: Path = None):
        super().__init__(name=self.NAME, category=ToolCategory.FILE)
        if workspace is None:
            raise ValueError(f"{self.NAME}: workspace is required (no bypass construction)")
        self.workspace = workspace
        self.screenshot_lib = screenshot_lib or self.SCREENSHOT_LIB_PATH
    
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
                    "project": {
                        "type": "string",
                        "description": "Project name to list images for (optional, lists all projects if not provided)"
                    }
                },
                "required": []
            }
        )
    
    def execute(self, project: str = None) -> ToolResult:
        if not self.screenshot_lib.exists():
            return ToolResult(
                success=False,
                error_message=f"Screenshot library not found: {self.screenshot_lib}"
            )
        
        result = {"projects": {}}
        
        if project:
            project_path = self._resolve_reference_project(project)
            if project_path and project_path.exists() and project_path.is_dir():
                images = self._list_images(project_path)
                result["projects"][project] = images
                result["total_images"] = len(images)
                result["source"] = str(project_path)
                return ToolResult(success=True, data=result)

            # Project not found via the contained resolver (workspace +
            # bundled screenshot_lib). Do NOT fall back to a raw
            # ``self.screenshot_lib / project`` join — for absolute or
            # ``..``-bearing inputs that join collapses to an
            # out-of-workspace path and would silently enumerate the
            # host filesystem (the bypass we are closing in fix #4).
            try:
                avail = [d.name for d in self.screenshot_lib.iterdir() if d.is_dir()]
            except Exception:
                avail = []
            return ToolResult(
                success=False,
                error_message=(
                    f"Project not found: {project}. "
                    f"Available library projects: {avail}. "
                    "For runtime reference screenshots, use list_reference_images() with no project and view_image('screenshots/<name>')."
                )
            )
        else:
            # Runtime references copied by --reference-dir live in the current
            # workspace. Surface them first so agents do not confuse page names
            # with bundled screenshot-library project names.
            workspace_screenshots = self.workspace.resolve("screenshots")
            if workspace_screenshots.exists() and workspace_screenshots.is_dir():
                images = self._list_images(workspace_screenshots)
                if images:
                    result["projects"]["screenshots"] = images
                    result["total_images"] = len(images)
                    result["source"] = str(workspace_screenshots)
                    return ToolResult(success=True, data=result)

            # List all bundled library projects and their images
            total = 0
            for proj_dir in sorted(self.screenshot_lib.iterdir()):
                if proj_dir.is_dir() and not proj_dir.name.startswith('.'):
                    images = self._list_images(proj_dir)
                    result["projects"][proj_dir.name] = images
                    total += len(images)
            result["total_images"] = total
        
        return ToolResult(
            success=True,
            data=result
        )

    def _resolve_reference_project(self, project: str) -> Optional[Path]:
        """Resolve ``project`` to a directory, contained to:
          * the workspace (via ``self.workspace.resolve()`` — fix #4),
          * or the bundled, hard-coded ``self.screenshot_lib`` tree.
        Previously enumerated ``root.parent``, ``repo_root``, ``Path.cwd()``,
        etc., letting an agent list arbitrary host directories.
        """
        raw = str(project or "").strip()
        if not raw:
            return None
        try:
            ws_candidate = self.workspace.resolve(raw)
            if ws_candidate.exists() and ws_candidate.is_dir():
                return ws_candidate
        except Exception:
            pass
        try:
            lib_root = self.screenshot_lib.resolve()
            lib_candidate = (self.screenshot_lib / raw).resolve()
            if lib_candidate.is_relative_to(lib_root) and lib_candidate.exists() and lib_candidate.is_dir():
                return lib_candidate
        except Exception:
            pass
        return None
    
    def _list_images(self, path: Path) -> list:
        """List all images in a directory"""
        supported_exts = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}
        images = []
        
        for f in sorted(path.iterdir()):
            if f.is_file() and f.suffix.lower() in supported_exts:
                size = f.stat().st_size
                images.append({
                    "name": f.name,
                    "size": f"{size / 1024:.1f}KB" if size < 1024*1024 else f"{size / 1024 / 1024:.1f}MB",
                    "type": f.suffix.lower()[1:]
                })
        
        return images


# ===== Copy Reference Image Tool =====

class CopyReferenceImageTool(BaseTool):
    """Copy reference images from the screenshot library to workspace."""
    
    NAME = "copy_reference_image"
    
    DESCRIPTION = """Copy a reference image from the screenshot library to your workspace.

This allows you to use existing design references for your project.
Images are copied to workspace/screenshots/ by default.

Examples:
    copy_reference_image "atlassian_home/atlassian_home.png"
    copy_reference_image "atlassian_home/jira_example.png" "design/reference.png"
    copy_reference_image "atlassian_home/user_bar.png" "components/navbar-ref.png"

Use list_reference_images to see available images first. If screenshots already
exist in workspace/screenshots, use view_image("screenshots/<name>.png") instead
of copying them again.
"""
    
    SCREENSHOT_LIB_PATH = Path(__file__).parent.parent / "screenshot"
    
    def __init__(self, *, workspace: Workspace, screenshot_lib: Path = None):
        super().__init__(name=self.NAME, category=ToolCategory.FILE)
        if workspace is None:
            raise ValueError(f"{self.NAME}: workspace is required (no bypass construction)")
        self.workspace = workspace
        self.screenshot_lib = screenshot_lib or self.SCREENSHOT_LIB_PATH
    
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
                    "source": {
                        "type": "string",
                        "description": "Source image path (e.g., 'atlassian_home/mockup.png')"
                    },
                    "destination": {
                        "type": "string",
                        "description": "Destination path in workspace (default: screenshots/<source_name>)"
                    }
                },
                "required": ["source"]
            }
        )
    
    def execute(self, source: str, destination: str = None) -> ToolResult:
        import shutil
        
        # Resolve source path. Runtime references copied into workspace/screenshots
        # are preferred over the bundled screenshot library.
        source_path = self._resolve_source_image(source)
        if not source_path.exists():
            return ToolResult(
                success=False,
                error_message=(
                    f"Source image not found: {source}. "
                    "Use list_reference_images() and prefer view_image('screenshots/<name>') for runtime references."
                )
            )
        
        # Determine destination
        if destination:
            dest_path, err = _resolve_workspace_path(
                self.workspace,
                destination,
                op_name="copy_reference_image",
                must_exist=False,
                expect_file=True,
            )
            if err:
                return ToolResult(success=False, error_message=err)
        else:
            # Default to screenshots directory
            dest_path = self.workspace.resolve("screenshots") / source_path.name
        
        # Create parent directory if needed
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            shutil.copy2(source_path, dest_path)
            
            return ToolResult(
                success=True,
                data={
                    "source": source,
                    "destination": str(dest_path.relative_to(self.workspace.root)),
                    "size": f"{dest_path.stat().st_size / 1024:.1f}KB",
                    "message": f"Copied {source} to {dest_path.relative_to(self.workspace.root)}"
                }
            )
        except Exception as e:
            return ToolResult(success=False, error_message=f"Copy failed: {e}")

    def _resolve_source_image(self, source: str) -> Path:
        """Resolve ``source`` to a file, contained to:
          * the workspace (via ``self.workspace.resolve()`` — fix #4),
          * or the bundled, hard-coded ``self.screenshot_lib`` tree.

        Previously this enumerated ``root.parent``, ``repo_root``, ``cwd``,
        etc. and silently returned ``screenshot_lib / raw`` (which, for an
        absolute ``raw`` like ``/etc/passwd``, collapses to ``/etc/passwd``)
        — so an agent could ask ``copy_reference_image('/etc/passwd', ...)``
        and exfiltrate host secrets INTO the workspace. No more.

        Returns a path; the caller checks ``.exists()`` for not-found.
        """
        raw = str(source or "").strip()

        # Candidate 1: inside the workspace at the user-given path.
        try:
            ws_candidate = self.workspace.resolve(raw)
            if ws_candidate.exists() and ws_candidate.is_file():
                return ws_candidate
        except Exception:
            pass

        # Candidate 2: inside the workspace at ``screenshots/<raw>``.
        try:
            ws_screens = self.workspace.resolve("screenshots") / raw
            ws_screens_resolved = ws_screens.resolve()
            ws_screens_root = self.workspace.resolve("screenshots").resolve()
            if (
                ws_screens_resolved.is_relative_to(ws_screens_root)
                and ws_screens_resolved.exists()
                and ws_screens_resolved.is_file()
            ):
                return ws_screens_resolved
        except Exception:
            pass

        # Candidate 3: bundled screenshot library (hard-coded, read-only).
        # Containment: joined path MUST stay under ``screenshot_lib`` after
        # ``.resolve()`` — blocks both ``..`` traversal and absolute paths.
        try:
            lib_root = self.screenshot_lib.resolve()
            lib_candidate = (self.screenshot_lib / raw).resolve()
            if lib_candidate.is_relative_to(lib_root) and lib_candidate.exists() and lib_candidate.is_file():
                return lib_candidate
        except Exception:
            pass

        # Not found in any contained location. Return a sentinel path
        # under the screenshot_lib so the caller's ``exists()`` check
        # produces a clean "Source image not found" error — but only
        # for SAFE ``raw`` inputs. For escape attempts, return a known
        # non-existent path inside the workspace to avoid leaking host
        # filesystem structure.
        try:
            safe_candidate = (self.screenshot_lib / raw).resolve()
            if safe_candidate.is_relative_to(self.screenshot_lib.resolve()):
                return safe_candidate
        except Exception:
            pass
        return self.screenshot_lib / "__not_found__"


# ===== Glob Tool =====

class GlobTool(BaseTool):
    """Find files by glob pattern."""
    
    NAME = "glob"
    
    DESCRIPTION = """Find files matching a glob pattern.

Examples:
    glob "*.py"                 # Python files in current dir
    glob "**/*.ts" /src         # TypeScript files recursively
    glob "test_*.py" /tests     # Test files in tests dir
"""
    
    def __init__(self, *, workspace: Workspace):
        super().__init__(name=self.NAME, category=ToolCategory.FILE)
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
                    "pattern": {"type": "string", "description": "Glob pattern"},
                    "path": {"type": "string", "description": "Directory to search (default: current)"}
                },
                "required": ["pattern"]
            }
        )
    
    def execute(self, pattern: str, path: str = None) -> ToolResult:
        # An empty/absent path searches the workspace ROOT (".") — matching this
        # tool's own docstring (`glob "*.py"  # ... in current dir`). Previously
        # `path or ""` failed the resolver's "path is required" guard, so an
        # agent following the docs got an error and fell back to guessing paths.
        # An EXPLICIT non-existent path still errors (with the not-found hint).
        search_path, err = _resolve_workspace_path(
            self.workspace,
            path or ".",
            op_name="glob",
            must_exist=True,
            expect_file=False,
        )
        if err:
            return ToolResult(success=False, error_message=err)
        
        try:
            matches = list(search_path.glob(pattern))
            
            # Sort and filter
            matches = sorted(m for m in matches if not any(
                p.startswith('.') for p in m.parts
            ))[:100]  # Limit results
            
            if not matches:
                return ToolResult(
                    success=True,
                    data={"matches": [], "info": f"No files matching '{pattern}' in {path or '.'}"}
                )
            
            rel_matches = []
            for m in matches:
                try:
                    rel_matches.append(str(m.relative_to(search_path)))
                except ValueError:
                    rel_matches.append(str(m))
            
            output = [f"Found {len(matches)} files:"] + rel_matches
            
            return ToolResult(
                success=True,
                data={"matches": rel_matches, "output": "\n".join(output)}
            )
        except Exception as e:
            return ToolResult(success=False, error_message=f"Glob failed: {e}")


# ===== Exports =====

__all__ = [
    "UpdateJsonPathTool",
    "UpdateYamlPathTool",
    "ViewImageTool",
    "ListReferenceImagesTool",
    "CopyReferenceImageTool",
    "GlobTool",
    "FileHistory",
]
