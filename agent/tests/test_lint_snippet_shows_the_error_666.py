r"""#666: the write refusal showed the middle of the file, not the syntax error.

`format_lint_error` builds the message an agent gets when its edit would break the file. Under
the heading *"This is how your edit would have looked"* it printed:

    snippet_start = max(0, len(lines) // 2 - 5)
    snippet_end   = min(len(lines), len(lines) // 2 + 5)

— a slice of the file's MIDPOINT, chosen without ever looking at where the error is. Every
checker in `check_syntax` already reports the line ("JSON syntax error at line 5837", node's
"main.js:12", tsc's "app.ts:12:5", the #635 "L12:5"), so the number was in hand and discarded.

Measured over the 249 run logs:

    1520 of these refusals across 122 runs, median 12 per run
    of the 56 whose line number is visible in the log, the median error sits at line 6342
    and 96% are past line 200 — a mid-file window essentially never contains the error

Checked the era before concluding, because twice this round I nearly reported an already-fixed
defect: these runs go up to r144 and `format_lint_error` has not changed, so this one is live.
(#634 and #635 both landed 2026-08-12, after every run in the corpus — their log counts are
pre-fix and were retracted.)
"""
import pytest

from env_generator.llm_generator.tools.file_tools import (
    _first_error_line_666 as first_line,
    format_lint_error,
)

_CONTENT = "\n".join(f"line{i}" for i in range(1, 201))


def _numbers(msg):
    return [int(l.split("|")[0].strip()) for l in msg.splitlines() if "|" in l]


# --- every checker's dialect ------------------------------------------------------------------

@pytest.mark.parametrize("errors,want", [
    ("JSON syntax error at line 5837: Expecting ',' delimiter", 5837),   # json
    ("YAML syntax error: while parsing a block, line 40", 40),           # yaml
    ("SyntaxError at L12:5: invalid syntax", 12),                        # #635
    ("app.ts:12:5 - error TS1005: ',' expected.", 12),                   # tsc
    ("main.js:88\nSyntaxError: Unexpected token", 88),                   # node --check
])
def test_it_reads_the_line_out_of_each_checkers_dialect(errors, want):
    assert first_line(errors) == want


@pytest.mark.parametrize("errors", ["no number here", "", None, "error: unexpected token"])
def test_it_returns_None_when_no_line_is_reported(errors):
    assert first_line(errors) is None


def test_it_takes_the_FIRST_error_when_several_are_reported():
    """With a cascade the earliest is the cause; the rest are consequences."""
    assert first_line("main.js:12\nmain.js:40\nmain.js:99") == 12


def test_it_never_raises_on_junk():
    for junk in (object(), 12, ["a"], b"x"):
        first_line(junk)


# --- the snippet follows the error ----------------------------------------------------------------

def test_the_window_is_centred_on_the_reported_line():
    nums = _numbers(format_lint_error("f.json", "JSON syntax error at line 190: x", _CONTENT, ""))
    assert 190 in nums
    assert min(nums) == 185 and max(nums) == 195


def test_an_error_near_the_top_is_not_shown_from_the_middle():
    """The defect: line 8 in a 200-line file used to display lines 95-105."""
    nums = _numbers(format_lint_error("f.json", "JSON syntax error at line 8: x", _CONTENT, ""))
    assert 8 in nums
    assert max(nums) < 100


def test_an_error_at_the_very_start_clamps():
    nums = _numbers(format_lint_error("f.json", "JSON syntax error at line 1: x", _CONTENT, ""))
    assert min(nums) == 1 and 1 in nums


def test_an_error_at_the_very_end_clamps():
    nums = _numbers(format_lint_error("f.json", "JSON syntax error at line 200: x", _CONTENT, ""))
    assert 200 in nums and max(nums) == 200


def test_a_line_beyond_the_file_falls_back_instead_of_showing_nothing():
    """A checker can report a line past EOF (truncated content); never emit an empty window."""
    nums = _numbers(format_lint_error("f.json", "JSON syntax error at line 9999: x", _CONTENT, ""))
    assert nums, "the snippet must not be empty"
    # the midpoint fallback is the PRE-#666 window verbatim: len(lines)//2 - 5 .. +5
    assert nums == _numbers(format_lint_error("f.py", "no line here", _CONTENT, ""))


def test_no_reported_line_keeps_the_old_midpoint_behaviour():
    nums = _numbers(format_lint_error("f.py", "something went wrong", _CONTENT, ""))
    assert 100 in nums


def test_a_short_file_still_works():
    nums = _numbers(format_lint_error("f.json", "at line 2: x", "a\nb\nc", ""))
    assert nums == [1, 2, 3]


def test_an_empty_file_does_not_crash():
    format_lint_error("f.json", "at line 1: x", "", "")


# --- the rest of the message is unchanged ---------------------------------------------------------

def test_the_errors_block_is_still_quoted_verbatim():
    msg = format_lint_error("f.json", "JSON syntax error at line 190: Expecting ','", _CONTENT, "")
    assert "ERRORS:" in msg
    assert "Expecting ','" in msg


def test_it_still_says_the_change_was_not_applied():
    msg = format_lint_error("f.json", "at line 5: x", _CONTENT, "")
    assert "have NOT been applied" in msg
    assert "DO NOT re-run the same failed edit command" in msg


# --- provenance -------------------------------------------------------------------------------

def test_the_measurement_is_recorded():
    import inspect
    from env_generator.llm_generator.tools import file_tools as ft
    flat = " ".join(inspect.getsource(ft.format_lint_error).replace("#", " ").split())
    assert "1520 of these refusals across 122 runs" in flat
    assert "line **6342**" in flat or "line 6342" in flat


def test_the_fallback_is_documented():
    import inspect
    from env_generator.llm_generator.tools import file_tools as ft
    flat = " ".join(inspect.getsource(ft.format_lint_error).split())
    assert "never worse than before" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
