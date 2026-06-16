"""Write tool for canonical file/search surface."""

from pathlib import Path
from typing import Optional

from .shared import (
    BaseTool, ToolCategory, ToolResult, Workspace, create_tool_param,
    write_workspace_file,
)

class WriteTool(BaseTool):
    """Canonical full-file write tool."""

    NAME = "write"
    DESCRIPTION = """Create or overwrite a file on the local filesystem.

Use this for new files or complete rewrites.
For targeted edits, prefer `edit` or `apply_patch`.

Parameters: `file_path` and `content`.
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
                    "file_path": {"type": "string", "description": "Path to the file to write"},
                    "content": {"type": "string", "description": "Full file content"},
                },
                "required": ["file_path", "content"],
            },
        )

    def get_tool_param(self):
        return self.tool_definition

    def execute(
        self,
        file_path: Optional[str] = None,
        content: Optional[str] = None,
    ) -> ToolResult:
        fp = str(file_path).strip() if file_path is not None else ""
        if not fp:
            return ToolResult(success=False, error_message="write: missing file_path")
        if content is None:
            return ToolResult(success=False, error_message="write: missing content")
        return write_workspace_file(self.workspace, fp, content, tool=self)

