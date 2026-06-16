"""Delete file tool for canonical file/search surface."""

from .shared import (
    BaseTool, ToolCategory, ToolResult, Workspace, create_tool_param,
    _FileLock, _file_read_state, _is_protected_delete_path, _move_to_trash,
    _resolve_workspace_path, _workspace_rel,
)

class DeleteFileTool(BaseTool):
    """Delete a file within the workspace (trash by default)."""

    NAME = "delete_file"

    DESCRIPTION = """Delete a file from the workspace.

By default moves files to `.openenv_trash` for recovery.
Set `purge=true` to permanently delete.
This only deletes files, not directories.
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
                    "file_path": {
                        "type": "string",
                        "description": "Path to the file to delete (relative to workspace)",
                    },
                    "purge": {
                        "type": "boolean",
                        "description": "Permanently delete file when true (default: false)",
                    },
                },
                "required": ["file_path"],
            },
        )

    def execute(self, file_path: str, purge: bool = False) -> ToolResult:
        file_path, err = _resolve_workspace_path(
            self.workspace,
            file_path,
            op_name="delete_file",
            must_exist=True,
        )
        if err:
            return ToolResult(success=False, error_message=err)

        if file_path.is_dir():
            return ToolResult(
                success=False,
                error_message=(
                    f"Cannot delete directory: {file_path}. "
                    "Use execute_bash with 'rm -r' for directories."
                ),
            )
        if _is_protected_delete_path(self.workspace, file_path):
            return ToolResult(
                success=False,
                error_message=f"Refusing to delete protected path: {_workspace_rel(self.workspace, file_path)}",
            )

        try:
            with _FileLock(file_path):
                if purge:
                    file_path.unlink()
                    trash_path = None
                else:
                    trash_path = _move_to_trash(self.workspace, file_path)
            _file_read_state.pop(str(file_path), None)
            if purge:
                return ToolResult(
                    success=True,
                    data={
                        "deleted": _workspace_rel(self.workspace, file_path),
                        "purged": True,
                        "message": f"Permanently deleted: {_workspace_rel(self.workspace, file_path)}",
                    },
                )
            return ToolResult(
                success=True,
                data={
                    "deleted": _workspace_rel(self.workspace, file_path),
                    "purged": False,
                    "message": f"Moved to trash: {_workspace_rel(self.workspace, file_path)}",
                    "trash_path": _workspace_rel(self.workspace, trash_path),
                },
            )
        except PermissionError:
            return ToolResult(
                success=False,
                error_message=f"Permission denied: {_workspace_rel(self.workspace, file_path)}",
            )
        except Exception as e:
            return ToolResult(success=False, error_message=f"Delete failed: {e}")

