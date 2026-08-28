"""#1143: `read` hands out line numbers and `edit` had no way to use them.

`read` returns numbered lines (`f"{idx}:{line}"`), so a caller already holds exact
coordinates — and could only spend them by retyping the text as an anchor. Anchor matching is
where the failures are. Over the eight netflix runs, 102 edit failures split:

    46  "no part of the anchor is present"      (stale read / wrong file)
    41  "FIRST line is at line N, block diverges after"
    13  "found N matches of old_string"
     2  whitespace-only difference

100 of those are MATCHING failures, not editing failures, and each costs a fail-read-retry
cycle re-sending 54-65K tokens of context. Line mode cannot mismatch. What it can do is act on
stale coordinates — which is exactly what `_check_stale_write_guard` already refuses, so the
safety property is one the tool already enforces rather than a new one to get right.
"""
from __future__ import annotations

import pytest

from env_generator.llm_generator.tools.canonical_file_tools.edit import EditTool
from env_generator.llm_generator.workspace import Workspace
from env_generator.llm_generator.tools.canonical_file_tools.read import ReadTool

SRC = "alpha\nbravo\ncharlie\ndelta\n"


def _tools(tmp_path):
    ws = Workspace(str(tmp_path))
    return ws, EditTool(workspace=ws), ReadTool(workspace=ws)


def _seed(tmp_path, rel="f.txt", body=SRC):
    p = tmp_path / rel
    p.write_text(body, encoding="utf-8")
    return p


def _read_first(read_tool, rel="f.txt"):
    """A prior read is required before any write — mirror what an agent does."""
    return read_tool.execute(file_path=rel)


class TestEditsByCoordinate:

    def test_a_single_line_is_replaced(self, tmp_path):
        p = _seed(tmp_path)
        ws, edit, read = _tools(tmp_path)
        _read_first(read)
        res = edit.execute(file_path="f.txt", start_line=2, end_line=2, new_string="BRAVO\n")
        assert res.success, res.error_message
        assert p.read_text() == "alpha\nBRAVO\ncharlie\ndelta\n"

    def test_a_range_is_replaced(self, tmp_path):
        p = _seed(tmp_path)
        ws, edit, read = _tools(tmp_path)
        _read_first(read)
        res = edit.execute(file_path="f.txt", start_line=2, end_line=3, new_string="X\n")
        assert res.success, res.error_message
        assert p.read_text() == "alpha\nX\ndelta\n"

    def test_end_line_defaults_to_start_line(self, tmp_path):
        p = _seed(tmp_path)
        ws, edit, read = _tools(tmp_path)
        _read_first(read)
        res = edit.execute(file_path="f.txt", start_line=1, new_string="ALPHA\n")
        assert res.success, res.error_message
        assert p.read_text().startswith("ALPHA\nbravo\n")

    def test_a_replacement_without_a_newline_does_not_glue_lines(self, tmp_path):
        p = _seed(tmp_path)
        ws, edit, read = _tools(tmp_path)
        _read_first(read)
        res = edit.execute(file_path="f.txt", start_line=2, end_line=2, new_string="BRAVO")
        assert res.success, res.error_message
        assert p.read_text() == "alpha\nBRAVO\ncharlie\ndelta\n"


class TestRefusesWhatItCannotDoSafely:

    def test_both_modes_at_once_is_refused(self, tmp_path):
        _seed(tmp_path)
        ws, edit, read = _tools(tmp_path)
        _read_first(read)
        res = edit.execute(file_path="f.txt", old_string="alpha", new_string="A", start_line=1)
        assert not res.success
        assert "EITHER" in (res.error_message or "")

    def test_a_range_past_the_end_says_to_re_read(self, tmp_path):
        _seed(tmp_path)
        ws, edit, read = _tools(tmp_path)
        _read_first(read)
        res = edit.execute(file_path="f.txt", start_line=99, new_string="X\n")
        assert not res.success
        assert "past the end" in (res.error_message or "")

    def test_a_backwards_range_is_refused(self, tmp_path):
        _seed(tmp_path)
        ws, edit, read = _tools(tmp_path)
        _read_first(read)
        res = edit.execute(file_path="f.txt", start_line=3, end_line=1, new_string="X\n")
        assert not res.success
        assert "line range" in (res.error_message or "")

    def test_non_integer_coordinates_are_refused(self, tmp_path):
        _seed(tmp_path)
        ws, edit, read = _tools(tmp_path)
        _read_first(read)
        res = edit.execute(file_path="f.txt", start_line="two", new_string="X\n")
        assert not res.success
        assert "integer" in (res.error_message or "")


class TestAnchorModeIsUntouched:

    def test_text_anchor_still_works(self, tmp_path):
        p = _seed(tmp_path)
        ws, edit, read = _tools(tmp_path)
        _read_first(read)
        res = edit.execute(file_path="f.txt", old_string="bravo", new_string="BRAVO")
        assert res.success, res.error_message
        assert "BRAVO" in p.read_text()

    def test_a_missing_anchor_still_explains_itself(self, tmp_path):
        _seed(tmp_path)
        ws, edit, read = _tools(tmp_path)
        _read_first(read)
        res = edit.execute(file_path="f.txt", old_string="zzz", new_string="X")
        assert not res.success
        assert "old_string not found" in (res.error_message or "")


class TestSchemaAdvertisesIt:

    def test_the_tool_definition_exposes_the_coordinates(self, tmp_path):
        ws, edit, _ = _tools(tmp_path)
        blob = str(edit.get_tool_param())
        assert "start_line" in blob and "end_line" in blob

    def test_old_string_is_no_longer_unconditionally_required(self, tmp_path):
        ws, edit, _ = _tools(tmp_path)
        blob = str(edit.get_tool_param())
        assert "'required': ['file_path', 'new_string']" in blob or \
               '"required": ["file_path", "new_string"]' in blob
