"""Read tool for canonical file/search surface."""

from typing import Optional

from .shared import (
    BaseTool, ToolCategory, ToolResult, Workspace, create_tool_param,
    MAX_READ_LINES, cap_read_content, _record_file_read, _resolve_workspace_path, _workspace_rel,
    sync_hub_read,
)

# #613: deliver whole-file content in full the first TWO times; from the third identical
# delivery on, send a marker carrying an explicit force= escape instead.
_IDENTICAL_READ_ELIDE_AT = 3


class ReadTool(BaseTool):
    """Canonical file read tool."""

    NAME = "read"
    DESCRIPTION = """Read a file from the local filesystem.

Use this for code inspection before editing.

Parameters:
- file_path: Path to the file
- offset: Optional 1-based line offset (negative values count from end)
- limit: Optional maximum number of lines to return
"""

    def __init__(self, *, workspace: Workspace):
        super().__init__(name=self.NAME, category=ToolCategory.FILE)
        if workspace is None:
            raise ValueError(f"{self.NAME}: workspace is required (no bypass construction)")
        self.workspace = workspace
        # #613: per-INSTANCE (hence per-agent) fingerprint of the last whole-file delivery
        self._read_fingerprints: dict = {}

    @property
    def tool_definition(self):
        return create_tool_param(
            name=self.NAME,
            description=self.DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Path to the file to read"},
                    "offset": {"type": "integer", "description": "Optional 1-based line offset. Negative values count from the end."},
                    "limit": {"type": "integer", "description": f"Optional maximum number of lines to return (default {MAX_READ_LINES})."},
                    "force": {"type": "boolean", "description": "Re-deliver the full text even if you have already been given this exact content twice (see #613)."},
                },
                "required": ["file_path"],
            },
        )

    def get_tool_param(self):
        return self.tool_definition

    def execute(
        self,
        file_path: Optional[str] = None,
        offset: Optional[int] = None,
        limit: Optional[int] = None,
        force: bool = False,
    ) -> ToolResult:
        fp = str(file_path).strip() if file_path is not None else ""
        if not fp:
            return ToolResult(success=False, error_message="read: missing file_path")
        resolved, err = _resolve_workspace_path(
            self.workspace,
            fp,
            op_name="read",
            must_exist=True,
            expect_file=True,
        )
        if err:
            if "expected file, got directory" in err:
                return ToolResult(
                    success=True,
                    data={
                        "file_path": fp,
                        "content": "",
                        "info": "Path is a directory. Use glob(pattern='...') to inspect directory contents.",
                    },
                )
            return ToolResult(success=False, error_message=err)

        try:
            content = resolved.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return ToolResult(success=False, error_message=f"read: cannot read file: {e}")

        lines = content.splitlines()
        total_lines = len(lines)

        start_line = 1
        if offset is not None:
            if offset < 0:
                start_line = max(1, total_lines + offset + 1)
            else:
                start_line = max(1, offset)

        effective_limit = max(1, min(int(limit or MAX_READ_LINES), MAX_READ_LINES))
        end_line = min(total_lines, start_line + effective_limit - 1) if total_lines else 0

        selected = lines[start_line - 1:end_line] if total_lines else []
        numbered = "\n".join(f"{idx}:{line}" for idx, line in enumerate(selected, start=start_line))
        full_read = start_line == 1 and end_line >= total_lines
        _record_file_read(resolved, content, full_read=full_read)
        sync_hub_read(
            tool=self,
            workspace=self.workspace,
            path=resolved,
            content=content,
            full_read=full_read,
            line_range={"start": start_line, "end": end_line},
        )

        body = cap_read_content(numbered)[0] or "File is empty."
        # #613 — THE THIRD IDENTICAL DELIVERY. Measured over the arc's logs: 12469 `read`
        # calls, of which 28% are a first read (or a read after a change), 28% are a second
        # delivery of unchanged content, and **45% (5561) are the THIRD or later**. r134's
        # backend read `custom_routes.py` 135 times with nothing changing in between, at
        # ~8.2k tokens a time.
        #
        # #609 fixed only the provably-safe subset (duplicates inside ONE tool batch) and
        # deliberately left this alone, because a cross-turn cache cannot know whether the
        # agent still HOLDS the earlier content after a context trim. Two things make the
        # third-and-later delivery safe where the second was not: the agent has by then
        # received the identical bytes TWICE, and the marker carries its own escape hatch, so
        # the worst case is one extra round-trip rather than a starved lane.
        #
        # State lives on the INSTANCE: tool objects are built per agent
        # (`agent._tool_instances`), so one lane's reads can never suppress another's. Only
        # WHOLE-file reads are counted or elided — a ranged read is always delivered.
        if full_read and not force:
            key = str(resolved)
            fp = (len(body), hash(body))
            prev_fp, seen = self._read_fingerprints.get(key, (None, 0))
            seen = seen + 1 if prev_fp == fp else 1
            self._read_fingerprints[key] = (fp, seen)
            if seen >= _IDENTICAL_READ_ELIDE_AT:
                body = (f"[unchanged since your last read — identical content already "
                        f"delivered to you {seen - 1}x ({len(body)} chars, {total_lines} "
                        f"lines). Nothing has written to this file since. If you no longer "
                        f"have it, call read(file_path=..., force=true).]")
        return ToolResult(
            success=True,
            data={
                "file_path": _workspace_rel(self.workspace, resolved),
                "total_lines": total_lines,
                "offset": start_line,
                "limit": effective_limit,
                "content": body,
            },
        )

