r"""#1202ba: a refused screenshot is a dead stack, not a page the lane can fix.

netflix-r30 received the raw Playwright text eight times over 100 minutes:

    Screenshot failed: Page.goto: net::ERR_CONNECTION_REFUSED at http://localhost:8042/

Nothing in that says the app is not running, or that no edit to the frontend can make
the capture succeed. The gate it feeds — validation_ui_evidence_failed — was one of the
two still failing when r30 aborted at 148 minutes having delivered nothing.

Bounded by LANDMARKS, not a byte count (#943): the region under test runs from the fix
marker to the `return ToolResult` that ends the handler, so it stays correct as the
surrounding code moves.
"""
import sys
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))


def _handler():
    """The refusal branch, from its marker to the return that ends the handler."""
    from tools import image_search_tools
    src = Path(image_search_tools.__file__).read_text(encoding="utf-8")
    i = src.index("#1202ba")
    j = src.index("return ToolResult(success=False", i)
    return src[i:j]


class RefusedCaptureTests(unittest.TestCase):
    def test_it_names_the_cause(self):
        self.assertIn("NOTHING IS LISTENING", _handler())

    def test_it_names_the_one_action_that_helps(self):
        self.assertIn("compose up", _handler(),
                      "the message names the problem but not what to do about it")

    def test_it_says_editing_the_page_cannot_help(self):
        """The point is to stop a lane rewriting a page against a dead port."""
        self.assertIn("not a page you can fix by editing it", _handler())

    def test_the_advice_is_conditional_on_a_refusal(self):
        """A timeout or a bad selector is a different thing and must not be relabelled."""
        self.assertIn('if "ERR_CONNECTION_REFUSED" in str(e) or "ECONNREFUSED" in str(e):',
                      _handler())

    def test_the_original_error_survives(self):
        """Whatever Playwright said must still reach the caller, refusal or not."""
        h = _handler()
        self.assertIn('_msg = f"Screenshot failed: {e}"', h)
        self.assertIn("_msg +=", h, "the advice replaces the original text instead of adding to it")


if __name__ == "__main__":
    unittest.main()
