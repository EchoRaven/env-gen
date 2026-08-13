r"""#676: "edit: old_string not found in file" was the whole message.

Nine words, naming neither the file, nor the anchor, nor which of three quite different things
went wrong. Continuing the wasted-STEPS ranking that produced #674 and #675 — per #257 each
retry is a whole step re-sending the prompt:

    edit fails 1694 times across the 249 run logs, median 12 per run
      482  Write denied: FRAMEWORK-OWNED files      (that message is already good)
      418  edit: old_string not found in file       <- this one
      212  introduced syntax error(s)                (#666 now points at the real line)
       84  found N matches; set replace_all

Three causes hide behind the one line, and the remedy differs for each:

    whitespace drift  the block IS there, indentation differs -> re-read and copy exactly
    partial match     the first line exists, the block diverges -> here is the line number
    nothing present   stale read or wrong file -> read it again

Everything needed to tell them apart is already in hand: the tool holds both the file content
and the anchor. It just never looked.
"""
from pathlib import Path

import pytest

from env_generator.llm_generator.tools.canonical_file_tools.edit import (
    _anchor_miss_reason_676 as why,
)

_SRC = "def f():\n    return 1\n\nclass A:\n    pass\n"


# --- the three diagnoses ------------------------------------------------------------------------

def test_whitespace_drift_is_named_as_such():
    msg = why(_SRC, "def f():\n        return 1", Path("a.py"))
    assert "SAME text IS present with different whitespace" in msg


def test_whitespace_drift_tells_it_to_copy_not_retype():
    msg = why(_SRC, "def f():\n        return 1", Path("a.py"))
    assert "copy the block exactly" in msg
    assert "rather than retyping" in msg


def test_a_partial_match_gives_the_line_number():
    msg = why(_SRC, "class A:\n    other()", Path("a.py"))
    assert "FIRST line is at line 4" in msg
    assert "diverges after that" in msg


def test_an_absent_anchor_says_stale_read_or_wrong_file():
    msg = why(_SRC, "zzz nothing", Path("a.py"))
    assert "no part of the anchor is present" in msg
    assert "changed since you read it" in msg


def test_the_three_messages_are_distinguishable():
    a = why(_SRC, "def f():\n        return 1", Path("a.py"))
    b = why(_SRC, "class A:\n    other()", Path("a.py"))
    c = why(_SRC, "zzz", Path("a.py"))
    assert len({a, b, c}) == 3


# --- every message keeps the basics ---------------------------------------------------------------

@pytest.mark.parametrize("anchor", ["def f():\n        return 1", "class A:\n    other()", "zzz"])
def test_the_original_wording_still_leads(anchor):
    assert why(_SRC, anchor, Path("a.py")).startswith("edit: old_string not found in file")


@pytest.mark.parametrize("anchor", ["def f():\n        return 1", "class A:\n    other()", "zzz"])
def test_the_file_is_named(anchor):
    assert "a.py" in why(_SRC, anchor, Path("a.py"))


def test_the_anchor_size_is_reported():
    assert "2 line(s)" in why(_SRC, "class A:\n    other()", Path("a.py"))
    assert "1 line(s)" in why(_SRC, "zzz", Path("a.py"))


# --- it must never make the message worse ----------------------------------------------------------

@pytest.mark.parametrize("content,anchor,path", [
    (None, None, None),
    (_SRC, None, Path("a.py")),
    (None, "x", Path("a.py")),
    (_SRC, "", Path("a.py")),
])
def test_junk_falls_back_to_the_original_line(content, anchor, path):
    out = why(content, anchor, path)
    assert out.startswith("edit: old_string not found in file")


def test_a_plain_string_path_works():
    assert "b.py" in why(_SRC, "zzz", "b.py")


def test_an_empty_file_is_handled():
    assert why("", "anything", Path("a.py")).startswith("edit: old_string not found in file")


def test_it_is_deterministic():
    assert why(_SRC, "zzz", Path("a.py")) == why(_SRC, "zzz", Path("a.py"))


# --- wiring -------------------------------------------------------------------------------

def test_the_edit_tool_calls_it():
    import inspect
    from env_generator.llm_generator.tools.canonical_file_tools import edit as e
    src = inspect.getsource(e)
    assert "_anchor_miss_reason_676(" in src
    assert 'error_message="edit: old_string not found in file"' not in src


def test_the_multiple_match_message_is_untouched():
    """That one already names the count and the remedy."""
    import inspect
    from env_generator.llm_generator.tools.canonical_file_tools import edit as e
    assert "set replace_all=true or provide a more specific old_string" in inspect.getsource(e)


# --- provenance -------------------------------------------------------------------------------

def test_the_measurement_is_recorded():
    import inspect
    from env_generator.llm_generator.tools.canonical_file_tools import edit as e
    flat = " ".join(inspect.getsource(e._anchor_miss_reason_676).replace("#", " ").split())
    assert "1694 times" in flat and "418 of those" in flat


def test_the_three_causes_are_documented():
    import inspect
    from env_generator.llm_generator.tools.canonical_file_tools import edit as e
    flat = " ".join(inspect.getsource(e._anchor_miss_reason_676).split())
    for cause in ("whitespace drift", "partial match", "nothing present"):
        assert cause in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
