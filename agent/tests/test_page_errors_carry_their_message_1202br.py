r"""#1202br: a page error recorded as a minified location tells the lane nothing.

netflix-r33's two blocking UI flows recorded this as their entire evidence:

    Error at http://localhost:8053/assets/index--TCHSJCV.js:49:360
    page-level Error

Both were "blocked by frontend runtime JavaScript Error on page navigation", and
`validation_ui_evidence_failed` is the corpus's most common delivery blocker — 46 times
across 40 run logs. A lane handed a production bundle and a column number cannot act on
it; the message is the part it can search its own source for.

Playwright's Error carries .message, .name and .stack. The handler kept none of them.
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

from tools.browser._manager import BrowserManager  # noqa: E402


class _PwError:
    """Shaped like Playwright's Error: str() gives the location, attributes give more."""
    def __init__(self, message, name="TypeError", stack=""):
        self.message = message
        self.name = name
        self.stack = stack

    def __str__(self):
        return "Error at http://localhost:8053/assets/index--TCHSJCV.js:49:360"


class PageErrorsCarryTheirMessageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.m = BrowserManager(Path("/tmp"))

    def test_the_message_reaches_the_record(self):
        self.m._on_page_error(_PwError("Cannot read properties of undefined (reading 'map')"))
        rec = self.m.state.console_logs[-1]
        self.assertIn("Cannot read properties of undefined", rec["text"])
        self.assertEqual(rec["message"], "Cannot read properties of undefined (reading 'map')")

    def test_the_location_is_kept_too(self):
        """The bundle position is not useless — it is just not sufficient on its own."""
        self.m._on_page_error(_PwError("boom"))
        self.assertIn("index--TCHSJCV.js:49:360", self.m.state.console_logs[-1]["text"])

    def test_the_stack_is_bounded(self):
        """A bundled stack is long and repetitive; the useful frames are at the top."""
        self.m._on_page_error(_PwError("boom", stack="\n".join(f"at f{i}" for i in range(40))))
        self.assertEqual(len(self.m.state.console_logs[-1]["stack"].splitlines()), 6)

    def test_an_error_with_no_message_still_records(self):
        """Degrading to the old behaviour beats losing the error."""
        class _Bare:
            def __str__(self):
                return "page-level Error"
        self.m._on_page_error(_Bare())
        self.assertEqual(self.m.state.console_logs[-1]["text"], "page-level Error")

    def test_a_hostile_error_object_cannot_lose_the_record(self):
        """A raising attribute must not take the whole error down with it."""
        class _Hostile:
            @property
            def message(self):
                raise RuntimeError("nope")

            def __str__(self):
                return "page-level Error"
        self.m._on_page_error(_Hostile())
        self.assertEqual(len(self.m.state.console_logs), 1)


if __name__ == "__main__":
    unittest.main()
