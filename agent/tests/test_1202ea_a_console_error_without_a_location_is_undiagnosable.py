r"""#1202ea: the test-user walk drops the one field that localises a crash.

tiktok-web-r96 came back with every one of its twelve pages blank and a single console error:

    [/] BLANK (renders no real content) · console errors: TypeError: (void 0) is not a function

No file, no line. An app-wide render crash reported as an unlocalised sentence — there is
nothing a lane can act on, and nothing an operator can grep for.

Playwright's console message carries `location = {url, lineNumber, columnNumber}`, and this
repo already records it: `browser/_manager.py::_on_console` stores `"location": str(msg.location)`
beside the text. The test-user walk registers its OWN handler and keeps only the text:

    page.on("console", lambda m: cerr.append(m.text) if m.type == "error" else None)

so the field that turns "something is undefined somewhere" into "bundle.js:1421" is discarded
at the source, before any cap or filter can preserve it.

The report then truncates what is left to 120 characters ACROSS THE JOINED LIST:

    flags.append("console errors: " + "; ".join(p["console_errors"])[:120])

Five errors are collected (`list(cerr)[:5]`), so a page with several shows the first and half
of the second. Same shape as #973/#978/#1202df: the framework holds the actionable detail and
then reports the failure without the instance.
"""
import sys
from pathlib import Path

import pytest

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

from multi_agent.runtime.test_user_runner import (  # noqa: E402
    _console_entry_1202ea,
    _console_flag_1202ea,
)


class _Msg:
    def __init__(self, text, location=None, type="error"):
        self.text = text
        self.location = location
        self.type = type


def test_the_location_travels_with_the_text():
    """tiktok's crash, with the field Playwright already hands us."""
    m = _Msg("TypeError: (void 0) is not a function",
             {"url": "http://localhost:8005/assets/index-a1b2.js",
              "lineNumber": 1421, "columnNumber": 17})
    got = _console_entry_1202ea(m)
    assert "TypeError: (void 0) is not a function" in got
    assert "index-a1b2.js" in got
    assert "1421" in got


def test_a_message_without_a_location_is_still_reported():
    assert _console_entry_1202ea(_Msg("boom", None)) == "boom"
    assert _console_entry_1202ea(_Msg("boom", {})) == "boom"


def test_a_partial_location_does_not_raise():
    got = _console_entry_1202ea(_Msg("boom", {"url": "http://x/a.js"}))
    assert "boom" in got and "a.js" in got


def test_each_error_keeps_its_own_room():
    """`"; ".join(...)[:120]` showed the first error and half of the second."""
    errs = [f"TypeError: thing{i} is not a function (http://localhost:8005/assets/index.js:{i}:1)"
            for i in range(5)]
    flag = _console_flag_1202ea(errs)
    for i in range(5):
        assert f"thing{i}" in flag, "error %d was truncated away" % i


def test_a_single_enormous_error_is_still_bounded():
    """Bounded per entry, so one pathological message cannot flood the report."""
    flag = _console_flag_1202ea(["x" * 5000])
    assert len(flag) < 600


def test_the_cap_keeps_a_p90_error_whole():
    """Measured: p50 330 / p90 450 / p99 630 over 135 console errors in 33 run logs.
    The old 120 cut the MEDIAN in half."""
    from multi_agent.runtime.test_user_runner import _CONSOLE_ENTRY_CAP_1202EA as CAP
    assert CAP >= 450, "a p90 console error no longer survives the cap"


def test_no_errors_yields_nothing():
    assert _console_flag_1202ea([]) == ""
