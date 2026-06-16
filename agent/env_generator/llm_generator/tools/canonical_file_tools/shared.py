"""Shared helpers for canonical file/search tools."""

from dataclasses import dataclass
import hashlib
import hashlib
import logging
from pathlib import Path
from typing import List, Optional, Tuple

from utils.tool import BaseTool, ToolCategory, ToolResult, create_tool_param
from workspace import Workspace

_logger = logging.getLogger(__name__)

# Per-process set of (op, exception_type_name) keys we have already logged a
# warning for. Hub probe-recording is best-effort by design but a hub-contract
# drift that silently zeroes file-IO observability would be invisible without
# at least one warning per (op, error-class) per process. See
# ``_log_hub_swallow_once`` below.
_HUB_SWALLOW_LOGGED: set = set()


def _log_hub_swallow_once(op: str, exc: BaseException) -> None:
    """Log a single warning per (hub-op, exception type) per process so a
    hub-API drift that always errors is observable in the pilot log-tail
    without drowning out every other diagnostic. The caller still degrades
    gracefully — this only adds an observability signal, not a behavioural
    change."""
    key = (op, type(exc).__name__)
    if key in _HUB_SWALLOW_LOGGED:
        return
    _HUB_SWALLOW_LOGGED.add(key)
    _logger.warning(
        "swallowed (once-per-process): hub op %s raised %r — "
        "observability degraded",
        op,
        exc,
    )

from ..file_tools import (
    _FileLock,
    _atomic_write_text,
    _check_stale_write_guard,
    _file_history,
    _file_read_state,
    _is_protected_delete_path,
    _move_to_trash,
    _record_file_read,
    _record_file_write,
    _resolve_workspace_path,
    _workspace_rel,
    format_lint_error,
    run_lint,
)
# Dockerfile-lint import. Two invocation patterns the test+production paths use:
#   - Production: agent/ on sys.path; full package = env_generator.llm_generator.tools.canonical_file_tools.shared
#     → 3-dot relative resolves to env_generator.llm_generator.multi_agent.dockerfile_lint ✓
#   - Tests: env_generator/llm_generator/ on sys.path; truncated package = tools.canonical_file_tools.shared
#     → 3-dot relative tries to go above `tools` top-level → ValueError; fall back to absolute
#       `multi_agent.dockerfile_lint` which resolves because multi_agent is a sibling top-level pkg
# Cascading try handles both. Bug-history: commit 006261ff originally used 3 dots only;
# this fired ValueError under the test sys.path pattern, silently breaking 196 tests' collection
# until R1+adversarial caught it during Phase 0.3.
try:
    from ...multi_agent.dockerfile_lint import enforce_dockerfile_classic_compat
except (ImportError, ValueError):
    from multi_agent.dockerfile_lint import enforce_dockerfile_classic_compat  # type: ignore

MAX_READ_LINES = 2000

HIGH_CONTENTION_PREFIXES = (
    "design/",
    "app/frontend/src/",
    "app/backend/src/routes/",
    "app/frontend/src/services/",
)

def _tool_agent_id(tool: Optional[BaseTool]) -> str:
    return str(getattr(tool, "_agent_id", "") or "")

def sync_hub_read(
    *,
    tool: Optional[BaseTool],
    workspace: Workspace,
    path: Path,
    content: str,
    full_read: bool,
    line_range: Optional[dict] = None,
) -> None:
    hubs = getattr(tool, "_hubs", None) if tool is not None else None
    if not hubs or not hasattr(hubs, "record_file_read"):
        return
    try:
        hubs.record_file_read(
            _workspace_rel(workspace, path),
            agent=_tool_agent_id(tool),
            read_mode="full" if full_read else "partial",
            content_hash="sha256:" + hashlib.sha256((content or "").encode("utf-8")).hexdigest(),
            line_range=line_range or {},
        )
    except Exception as e:
        _log_hub_swallow_once("record_file_read", e)
        return

def sync_hub_write(
    *,
    tool: Optional[BaseTool],
    workspace: Workspace,
    path: Path,
    updated_content: str,
    original_content: str = "",
    operation: str = "write",
    metadata: Optional[dict] = None,
) -> None:
    hubs = getattr(tool, "_hubs", None) if tool is not None else None
    if not hubs or not hasattr(hubs, "sync_file_change"):
        return
    try:
        hubs.sync_file_change(
            _workspace_rel(workspace, path),
            updated_content,
            agent=_tool_agent_id(tool),
            operation=operation,
            old_content=original_content,
            metadata=metadata or {},
        )
        if hasattr(hubs, "sync_text_document_snapshot") and _is_high_contention_path(_workspace_rel(workspace, path)):
            hubs.sync_text_document_snapshot(
                _workspace_rel(workspace, path),
                updated_content,
                agent=_tool_agent_id(tool),
                metadata={"source": "materialized_file_write", "operation": operation},
            )
    except Exception as e:
        _log_hub_swallow_once("sync_file_change", e)
        return

def _normalize_hub_path(path: str) -> str:
    """Normalize hub file paths for guard comparisons."""
    normalized = str(path or "").replace("\\", "/").strip()
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized.strip("/")

def _is_high_contention_path(file_path: str) -> bool:
    normalized = _normalize_hub_path(file_path)
    return normalized in {"app/frontend/src/App.jsx"} or any(
        normalized.startswith(prefix) for prefix in HIGH_CONTENTION_PREFIXES
    )

def _check_file_region_claim(tool: BaseTool, file_path: str) -> Optional[ToolResult]:
    """Require a matching hub file-region claim when regions exist for a path."""
    hubs = getattr(tool, "_hubs", None)
    agent_id = str(getattr(tool, "_agent_id", "") or "").strip()
    if not hubs or not agent_id or not hasattr(hubs, "get_file_regions"):
        return None
    target_path = _normalize_hub_path(file_path)
    try:
        regions = hubs.get_file_regions(file_path=file_path)
        if not regions:
            regions = [
                region for region in hubs.get_file_regions()
                if isinstance(region, dict)
                and _normalize_hub_path(region.get("file_path")) == target_path
            ]
    except Exception as e:
        _log_hub_swallow_once("get_file_regions", e)
        return None
    active_regions = [
        region for region in regions
        if isinstance(region, dict) and region.get("status") in {"pending", "in_progress"}
    ]
    if not active_regions and _is_high_contention_path(file_path):
        try:
            hubs.publish_file_region(
                region_id=f"auto:{target_path}",
                file_path=target_path,
                title=f"Exclusive edits for {target_path}",
                description="Automatically created high-contention file region.",
                owner_domain="any",
                region_type="file",
                anchor={"path": target_path},
                metadata={"auto_created": True},
                agent="system",
            )
            active_regions = [
                region for region in hubs.get_file_regions(file_path=target_path)
                if isinstance(region, dict) and region.get("status") in {"pending", "in_progress"}
            ]
        except Exception as e:
            _log_hub_swallow_once("publish_file_region", e)
            active_regions = []
    if not active_regions:
        return None
    claimed = [
        region for region in active_regions
        if region.get("claimed_by") == agent_id and region.get("status") == "in_progress"
    ]
    if claimed:
        return None
    region_preview = [
        {
            "id": region.get("id"),
            "status": region.get("status"),
            "claimed_by": region.get("claimed_by"),
            "title": region.get("title"),
        }
        for region in active_regions[:8]
    ]
    return ToolResult(
        success=False,
        error_message=(
            f"hub file-region claim required before editing {file_path}. "
            "Call get_file_regions(file_path=...), then claim_file_region(region_id=...) "
            "for the matching pending region before write/edit/apply_patch. "
            f"Active regions: {region_preview}"
        ),
        data={"file_path": file_path, "active_regions": region_preview},
    )

def write_workspace_file(workspace: Workspace, file_path: str, content: str, tool: BaseTool = None) -> ToolResult:
    """Create or overwrite a file under the workspace."""
    if tool is not None:
        claim_err = _check_file_region_claim(tool, file_path)
        if claim_err:
            return claim_err

    file_path_resolved, err = _resolve_workspace_path(
        workspace,
        file_path,
        op_name="write",
        must_exist=False,
        expect_file=True,
    )
    if err:
        return ToolResult(success=False, error_message=err)

    if content and "\\n" in content and content.count("\\n") > content.count("\n"):
        content = content.replace("\\n", "\n")
        content = content.replace("\\t", "\t")
        content = content.replace("\\r", "\r")

    if not content or len(content.strip()) < 2:
        return ToolResult(
            success=False,
            error_message=f"Content is empty or too short (len={len(content)}). Refusing to write potentially corrupted file.",
        )

    if file_path_resolved.suffix == ".json":
        import json

        try:
            json.loads(content)
        except json.JSONDecodeError as e:
            return ToolResult(
                success=False,
                error_message=f"Invalid JSON content at line {e.lineno}: {e.msg}. Content preview: {content[:200]}...",
            )

    if file_path_resolved.suffix in {".yaml", ".yml"}:
        try:
            import yaml

            yaml.safe_load(content)
        except Exception as e:
            return ToolResult(
                success=False,
                error_message=(
                    f"Invalid YAML content: {e}. "
                    "Tip: quote values containing ':' (example: name: \"API smoke: health\"). "
                    f"Content preview: {content[:220]}..."
                ),
            )

    # R2 round-11 structural pin (durable companion to Fix A):
    # every Dockerfile emitted by the pipeline must be classic-builder
    # compatible so DOCKER_BUILDKIT=0 stays viable per-app. Strip lone
    # `# syntax=docker/dockerfile:...` directives + hard-reject BuildKit-only
    # RUN/COPY --mount= and heredoc patterns. Single chokepoint: every
    # gated write tool (write, edit, apply_patch, ...) flows through here.
    if file_path_resolved.name == "Dockerfile" or file_path_resolved.suffix == ".dockerfile":
        try:
            content = enforce_dockerfile_classic_compat(content, str(file_path_resolved))
        except ValueError as e:
            return ToolResult(
                success=False,
                error_message=str(e),
            )

    try:
        is_new = not file_path_resolved.exists()
        old_content = ""
        if not is_new:
            old_content = file_path_resolved.read_text(encoding="utf-8")
            _file_history.save(str(file_path_resolved), old_content)
            stale_err = _check_stale_write_guard(file_path_resolved, old_content)
            if stale_err:
                return ToolResult(success=False, error_message=stale_err)

        file_path_resolved.parent.mkdir(parents=True, exist_ok=True)
        with _FileLock(file_path_resolved):
            _atomic_write_text(file_path_resolved, content, encoding="utf-8")

            lint_ok, lint_errors = run_lint(file_path_resolved)

            if not lint_ok:
                if is_new:
                    try:
                        file_path_resolved.unlink()
                    except Exception:
                        pass
                else:
                    _atomic_write_text(file_path_resolved, old_content, encoding="utf-8")
                error_msg = format_lint_error(str(file_path_resolved), lint_errors, content, old_content)
                return ToolResult(success=False, error_message=error_msg)
        _record_file_write(file_path_resolved, content)
        sync_hub_write(
            tool=tool,
            workspace=workspace,
            path=file_path_resolved,
            updated_content=content,
            original_content=old_content,
            operation="create" if is_new else "write",
        )

        lines = content.count("\n") + 1
        action = "Created" if is_new else "Overwrote"
        return ToolResult(
            success=True,
            data={
                "path": file_path,
                "lines": lines,
                "is_new": is_new,
                "message": f"File {action.lower()}: {file_path} ({lines} lines). Review the content and edit if necessary.",
            },
        )
    except Exception as e:
        return ToolResult(success=False, error_message=f"Write failed: {e}")



@dataclass
class _PatchHunk:
    header: str
    lines: List[Tuple[str, str]]


@dataclass
class _PatchOperation:
    op_type: str
    path: str
    hunks: List[_PatchHunk]
    add_lines: List[str]



def _write_with_lint_guard(
    *,
    workspace: Workspace,
    path: Path,
    original_content: str,
    updated_content: str,
    success_payload: dict,
    tool: Optional[BaseTool] = None,
    operation: str = "edit",
) -> ToolResult:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with _FileLock(path):
            _atomic_write_text(path, updated_content, encoding="utf-8")
            lint_ok, lint_errors = run_lint(path)
            if not lint_ok:
                _atomic_write_text(path, original_content, encoding="utf-8")
                return ToolResult(
                    success=False,
                    error_message=format_lint_error(
                        str(path),
                        lint_errors,
                        updated_content,
                        original_content,
                    ),
                )
        _record_file_write(path, updated_content)
        sync_hub_write(
            tool=tool,
            workspace=workspace,
            path=path,
            updated_content=updated_content,
            original_content=original_content,
            operation=operation,
        )
        return ToolResult(success=True, data=success_payload)
    except Exception as e:
        return ToolResult(success=False, error_message=f"write failed: {e}")


def _parse_patch(patch: str) -> List[_PatchOperation]:
    lines = patch.splitlines()
    if not lines or lines[0] != "*** Begin Patch":
        raise ValueError("patch must start with '*** Begin Patch'")

    operations: List[_PatchOperation] = []
    idx = 1
    while idx < len(lines):
        line = lines[idx]
        if line == "*** End Patch":
            return operations

        if line.startswith("*** Add File: "):
            path = line[len("*** Add File: "):].strip()
            idx += 1
            add_lines: List[str] = []
            while idx < len(lines) and not lines[idx].startswith("*** "):
                if not lines[idx].startswith("+"):
                    raise ValueError(f"add file lines must start with '+': {lines[idx]}")
                add_lines.append(lines[idx][1:])
                idx += 1
            operations.append(_PatchOperation(op_type="add", path=path, hunks=[], add_lines=add_lines))
            continue

        if line.startswith("*** Update File: "):
            path = line[len("*** Update File: "):].strip()
            idx += 1
            hunks: List[_PatchHunk] = []
            current: Optional[_PatchHunk] = None
            while idx < len(lines):
                current_line = lines[idx]
                if current_line == "*** End Patch" or current_line.startswith("*** Add File: ") or current_line.startswith("*** Update File: "):
                    break
                if current_line.startswith("@@"):
                    if current and current.lines:
                        hunks.append(current)
                    current = _PatchHunk(header=current_line[2:].strip(), lines=[])
                    idx += 1
                    continue
                if current_line == "*** End of File":
                    idx += 1
                    continue
                if not current:
                    current = _PatchHunk(header="", lines=[])
                if not current_line or current_line[0] not in {" ", "-", "+"}:
                    raise ValueError(f"invalid patch line: {current_line}")
                current.lines.append((current_line[0], current_line[1:]))
                idx += 1
            if current and current.lines:
                hunks.append(current)
            operations.append(_PatchOperation(op_type="update", path=path, hunks=hunks, add_lines=[]))
            continue

        raise ValueError(f"unknown patch section: {line}")

    raise ValueError("patch is missing '*** End Patch'")

def _find_subsequence(haystack: List[str], needle: List[str], start_index: int = 0) -> int:
    if not needle:
        return start_index
    max_start = len(haystack) - len(needle)
    for idx in range(max(0, start_index), max_start + 1):
        if haystack[idx:idx + len(needle)] == needle:
            return idx
