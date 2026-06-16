"""Edit tool for canonical file/search surface."""

from pathlib import Path
from typing import Optional

from .shared import (
    BaseTool, ToolCategory, ToolResult, Workspace, create_tool_param,
    _check_stale_write_guard, _file_history, _resolve_workspace_path,
    _workspace_rel, _write_with_lint_guard, write_workspace_file,
    _check_file_region_claim,
)

class EditTool(BaseTool):
    """Canonical exact-string edit tool."""

    NAME = "edit"
    DESCRIPTION = """Modify a file in place using an exact string replacement.

Parameters:
- file_path: Path to the file
- old_string: Exact text to replace
- new_string: Replacement text
- replace_all: Replace all occurrences instead of requiring a unique match

If `old_string` is empty and the file does not exist, a new file is created.
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
                    "file_path": {"type": "string", "description": "Path to the file to modify"},
                    "old_string": {"type": "string", "description": "Exact text to replace"},
                    "new_string": {"type": "string", "description": "Replacement text"},
                    "replace_all": {"type": "boolean", "description": "Replace all occurrences (default false)"},
                },
                "required": ["file_path", "old_string", "new_string"],
            },
        )

    def get_tool_param(self):
        return self.tool_definition

    def execute(
        self,
        file_path: Optional[str] = None,
        old_string: Optional[str] = None,
        new_string: Optional[str] = None,
        replace_all: bool = False,
    ) -> ToolResult:
        fp = str(file_path).strip() if file_path is not None else ""
        if not fp:
            return ToolResult(success=False, error_message="edit: missing file_path")
        if old_string is None or new_string is None:
            return ToolResult(success=False, error_message="edit: old_string and new_string are required")
        resolved, err = _resolve_workspace_path(
            self.workspace,
            fp,
            op_name="edit",
            must_exist=False,
            expect_file=True,
        )
        if err:
            return ToolResult(success=False, error_message=err)

        claim_err = _check_file_region_claim(self, fp)
        if claim_err:
            return claim_err

        if old_string == new_string:
            return ToolResult(success=False, error_message="edit: old_string and new_string are identical")

        if not resolved.exists():
            if old_string != "":
                return ToolResult(success=False, error_message=f"edit: file not found: {fp}")
            return write_workspace_file(self.workspace, fp, new_string, tool=self)

        try:
            current_content = resolved.read_text(encoding="utf-8")
        except Exception as e:
            return ToolResult(success=False, error_message=f"edit: read failed: {e}")

        stale_err = _check_stale_write_guard(resolved, current_content)
        if stale_err:
            return ToolResult(success=False, error_message=stale_err)

        if old_string == "":
            if current_content:
                return ToolResult(
                    success=False,
                    error_message="edit: old_string can be empty only when creating a new file or editing an empty file",
                )
            updated_content = new_string
            replacements = 1 if new_string else 0
        else:
            matches = current_content.count(old_string)
            if matches == 0:
                return ToolResult(success=False, error_message="edit: old_string not found in file")
            if matches > 1 and not replace_all:
                return ToolResult(
                    success=False,
                    error_message=(
                        f"edit: found {matches} matches of old_string; set replace_all=true or provide a more specific old_string"
                    ),
                )
            replacements = matches if replace_all else 1
            updated_content = (
                current_content.replace(old_string, new_string)
                if replace_all
                else current_content.replace(old_string, new_string, 1)
            )

        _file_history.save(str(resolved), current_content)
        return _write_with_lint_guard(
            workspace=self.workspace,
            path=resolved,
            original_content=current_content,
            updated_content=updated_content,
            tool=self,
            operation="edit",
            success_payload={
                "file_path": _workspace_rel(self.workspace, resolved),
                "replacements": replacements,
                "message": f"Edited {fp}",
            },
        )

