"""Apply patch tool for canonical file/search surface."""

from pathlib import Path

from .shared import (
    BaseTool, ToolCategory, ToolResult, Workspace, create_tool_param,
    _PatchOperation, _check_stale_write_guard, _file_history, _parse_patch,
    _resolve_workspace_path, _workspace_rel, _write_with_lint_guard,
    write_workspace_file, _find_subsequence, _check_file_region_claim,
    _FileLock, _file_read_state, _is_protected_delete_path, _move_to_trash,
)

class ApplyPatchTool(BaseTool):
    """Canonical patch application tool."""

    NAME = "apply_patch"
    DESCRIPTION = """Apply a structured patch to one or more files.

Expected format:
*** Begin Patch
*** Add File: path/to/file
+new line
*** Update File: path/to/file
@@
 old context
-old line
+new line
*** Delete File: path/to/file
*** End Patch
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
                    "patch": {"type": "string", "description": "Patch text in *** Begin Patch format"},
                },
                "required": ["patch"],
            },
        )

    def get_tool_param(self):
        return self.tool_definition

    def execute(self, patch: str) -> ToolResult:
        try:
            operations = _parse_patch(patch)
        except ValueError as e:
            return ToolResult(success=False, error_message=f"apply_patch: {e}")

        results = []
        for operation in operations:
            if operation.op_type == "add":
                result = self._apply_add(operation)
            elif operation.op_type == "delete":
                result = self._apply_delete(operation)
            else:
                result = self._apply_update(operation)

            if not result.success:
                return result
            results.append(result.data)

        return ToolResult(
            success=True,
            data={
                "files": results,
                "message": f"Applied patch to {len(results)} file(s)",
            },
        )

    def _apply_add(self, operation: _PatchOperation) -> ToolResult:
        resolved, err = _resolve_workspace_path(
            self.workspace,
            operation.path,
            op_name="apply_patch",
            must_exist=False,
            expect_file=True,
        )
        if err:
            return ToolResult(success=False, error_message=err)
        claim_err = _check_file_region_claim(self, operation.path)
        if claim_err:
            return claim_err
        if resolved.exists():
            return ToolResult(success=False, error_message=f"apply_patch: file already exists: {operation.path}")

        content = "\n".join(operation.add_lines)
        return write_workspace_file(self.workspace, operation.path, content, tool=self)

    def _apply_delete(self, operation: _PatchOperation) -> ToolResult:
        """#1021 — `*** Delete File:`, applying the delete_file tool's policy verbatim.

        Deliberately NOT a new capability: `delete_file` is already registered for every lane,
        so the authority granted here is identical to a tool call the agent could already make.
        The guards are therefore copied rather than re-decided — protected paths refused, the
        file moved to `.openenv_trash` instead of unlinked, so a wrong delete stays recoverable.
        """
        resolved, err = _resolve_workspace_path(
            self.workspace,
            operation.path,
            op_name="apply_patch",
            must_exist=True,
            expect_file=True,          # already rejects a directory; no second is_dir() check
        )
        if err:
            return ToolResult(success=False, error_message=err)
        claim_err = _check_file_region_claim(self, operation.path)
        if claim_err:
            return claim_err
        if _is_protected_delete_path(self.workspace, resolved):
            return ToolResult(
                success=False,
                error_message=(
                    "apply_patch: refusing to delete protected path: "
                    f"{_workspace_rel(self.workspace, resolved)}"
                ),
            )

        try:
            original_content = resolved.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            original_content = ""      # unreadable (binary/permissions) is not a reason to keep it

        try:
            with _FileLock(resolved):
                trash_path = _move_to_trash(self.workspace, resolved)
        except PermissionError:
            return ToolResult(
                success=False,
                error_message=f"apply_patch: permission denied: {_workspace_rel(self.workspace, resolved)}",
            )
        except Exception as e:
            return ToolResult(success=False, error_message=f"apply_patch: delete failed: {e}")

        _file_read_state.pop(str(resolved), None)
        _file_history.save(str(resolved), original_content)
        rel = _workspace_rel(self.workspace, resolved)
        return ToolResult(
            success=True,
            data={
                "file_path": rel,
                "deleted": rel,
                "purged": False,
                "trash_path": _workspace_rel(self.workspace, trash_path),
                "message": f"Deleted {operation.path} (moved to trash)",
            },
        )

    def _apply_update(self, operation: _PatchOperation) -> ToolResult:
        resolved, err = _resolve_workspace_path(
            self.workspace,
            operation.path,
            op_name="apply_patch",
            must_exist=True,
            expect_file=True,
        )
        if err:
            return ToolResult(success=False, error_message=err)
        claim_err = _check_file_region_claim(self, operation.path)
        if claim_err:
            return claim_err

        try:
            original_content = resolved.read_text(encoding="utf-8")
        except Exception as e:
            return ToolResult(success=False, error_message=f"apply_patch: read failed: {e}")

        stale_err = _check_stale_write_guard(resolved, original_content, self.workspace)
        if stale_err:
            return ToolResult(success=False, error_message=stale_err)

        original_lines = original_content.splitlines()
        updated_lines = list(original_lines)
        search_start = 0

        for hunk in operation.hunks:
            old_block = [text for prefix, text in hunk.lines if prefix in {" ", "-"}]
            new_block = [text for prefix, text in hunk.lines if prefix in {" ", "+"}]

            match_index = _find_subsequence(updated_lines, old_block, search_start)
            if match_index < 0:
                rel_path = _workspace_rel(self.workspace, resolved)
                context = hunk.header or "<no hunk header>"
                return ToolResult(
                    success=False,
                    error_message=(
                        f"apply_patch: failed to match patch hunk in {rel_path} "
                        f"(header: {context})"
                    ),
                )

            updated_lines = (
                updated_lines[:match_index]
                + new_block
                + updated_lines[match_index + len(old_block):]
            )
            search_start = match_index + len(new_block)

        updated_content = "\n".join(updated_lines)
        if original_content.endswith("\n"):
            updated_content += "\n"

        _file_history.save(str(resolved), original_content)
        return _write_with_lint_guard(
            workspace=self.workspace,
            path=resolved,
            original_content=original_content,
            updated_content=updated_content,
            tool=self,
            operation="patch",
            success_payload={
                "file_path": _workspace_rel(self.workspace, resolved),
                "message": f"Patched {operation.path}",
            },
        )

