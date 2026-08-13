"""Edit tool for canonical file/search surface."""

from pathlib import Path
from typing import Optional

from .shared import (
    BaseTool, ToolCategory, ToolResult, Workspace, create_tool_param,
    _check_stale_write_guard, _file_history, _resolve_workspace_path,
    _workspace_rel, _write_with_lint_guard, write_workspace_file,
    _check_file_region_claim,
)

def _anchor_miss_reason_676(content: str, anchor: str, path) -> str:
    """#676: WHY the anchor did not match, from what the tool already holds.

    `edit: old_string not found in file` was the entire message — nine words, naming neither the
    file, nor the anchor, nor which of three quite different things went wrong. Continuing the
    wasted-STEPS ranking (#674, #675): `edit` fails 1694 times across the 249 run logs at a
    median of 12 per run, and 418 of those are this line. Per #257 each retry is a whole step.

    Three causes, and the remedy differs for each:

      * whitespace drift — the block IS there but the indentation or spacing differs. The agent
        should re-read and copy the exact text, not rewrite the anchor.
      * partial match — the anchor's first line exists but the block diverges after it. The
        agent is close and needs the real continuation, so the line number is the answer.
      * nothing present — the anchor is from a stale read or the wrong file entirely.

    Everything needed is in hand. Best-effort: any fault falls back to the original wording, so
    the message is never worse than before.
    """
    base = "edit: old_string not found in file"
    try:
        name = getattr(path, "name", None) or str(path)
        lines = anchor.splitlines() or [anchor]
        where = f" ({name}; the anchor is {len(lines)} line(s))"

        def _flat(t):
            return "\n".join(" ".join(l.split()) for l in t.splitlines())

        if _flat(anchor) and _flat(anchor) in _flat(content):
            return (base + where + " — but the SAME text IS present with different whitespace. "
                    "Re-read the file and copy the block exactly as it appears (indentation "
                    "included) rather than retyping it.")

        first = next((l for l in lines if l.strip()), "")
        if first and first in content:
            n = content[:content.index(first)].count("\n") + 1
            return (base + where + f" — its FIRST line is at line {n}, but the block diverges "
                    "after that. Re-read from there and anchor on the text that is actually "
                    "in the file.")
        if first.strip() and first.strip() in content:
            return (base + where + " — its first line appears only with different surrounding "
                    "whitespace. Re-read and copy the exact text.")
        return (base + where + " — no part of the anchor is present. The file has changed since "
                "you read it, or this is not the file you meant; read it again before editing.")
    except Exception:
        return base


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

        stale_err = _check_stale_write_guard(resolved, current_content, self.workspace)
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
                return ToolResult(success=False, error_message=_anchor_miss_reason_676(
                    current_content, old_string, file_path))
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

