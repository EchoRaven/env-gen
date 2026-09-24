"""#364: browser_eval loses a call to the wrapper, not to the code.

The snippet goes straight to `page.evaluate(script)`, which treats it as an
expression or a function body. 15 browser_eval failures across r91/r92/r93, and
10 of them are purely that framing:

    6x  SyntaxError: Illegal return statement
    4x  SyntaxError: await is only valid in async functions

The model's JavaScript is fine; it just wrote a top-level `return` or `await`.
The other 5 failures are genuine runtime errors (Failed to fetch, reading a
property of null) and must stay exactly as they are.

Wrapping unconditionally would be wrong: `document.title` evaluated as an
expression returns the title, but `(async () => { document.title })()` returns
undefined. Sniffing for a top-level `return`/`await` with a regex would
misfire on a nested function or a string literal.

So the retry is driven by the error itself: run the script as written, and ONLY
when the engine reports one of those two framing errors, run it again inside an
async IIFE. A script that works today is never touched, and if the wrapped
retry also fails the ORIGINAL error is what surfaces.
"""
from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _needs_wrap(msg):
    from tools.browser.inspection import is_async_framing_error
    return is_async_framing_error(msg)


def _wrap(script):
    from tools.browser.inspection import wrap_in_async_iife
    return wrap_in_async_iife(script)


class TheTwoFramingErrorsAreRecognised(unittest.TestCase):

    def test_illegal_return(self):
        self.assertTrue(_needs_wrap(
            "Page.evaluate: SyntaxError: Illegal return statement"))

    def test_top_level_await(self):
        self.assertTrue(_needs_wrap(
            "Page.evaluate: SyntaxError: await is only valid in async functions"))

    def test_case_insensitive(self):
        self.assertTrue(_needs_wrap("SyntaxError: ILLEGAL RETURN STATEMENT"))


class GenuineErrorsAreNotRetried(unittest.TestCase):
    """The other 5 observed failures are real and must surface untouched."""

    def test_failed_to_fetch(self):
        self.assertFalse(_needs_wrap("TypeError: Failed to fetch"))

    def test_null_property(self):
        self.assertFalse(_needs_wrap(
            "TypeError: Cannot read properties of null (reading 'value')"))

    def test_an_unrelated_syntax_error(self):
        self.assertFalse(_needs_wrap("SyntaxError: Unexpected identifier 'doLogin'"))

    def test_empty(self):
        self.assertFalse(_needs_wrap(""))
        self.assertFalse(_needs_wrap(None))


class TheWrapperPreservesTheBody(unittest.TestCase):

    def test_it_is_an_async_iife(self):
        out = _wrap("return document.title")
        self.assertIn("async", out)
        self.assertIn("return document.title", out)
        self.assertTrue(out.strip().endswith(")()"))


class TheToolRetriesOnlyOnFraming(unittest.TestCase):

    def _run(self, fail_first_with, wrapped_ok=True):
        calls = []

        class _Page:
            async def evaluate(self, script):
                calls.append(script)
                if len(calls) == 1 and fail_first_with:
                    raise RuntimeError(fail_first_with)
                if len(calls) == 2 and not wrapped_ok:
                    raise RuntimeError("still broken")
                return "OK"

        class _State:
            page = _Page()

        class _Browser:
            state = _State()

        from tools.browser.inspection import BrowserEvaluateTool
        tool = BrowserEvaluateTool.__new__(BrowserEvaluateTool)
        tool.browser = _Browser()
        res = asyncio.run(tool.execute(script="return document.title"))
        return res, calls

    def test_a_framing_error_triggers_one_wrapped_retry(self):
        res, calls = self._run("SyntaxError: Illegal return statement")
        self.assertTrue(getattr(res, "success", False))
        self.assertEqual(len(calls), 2)
        self.assertIn("async", calls[1])

    def test_a_working_script_is_never_wrapped(self):
        res, calls = self._run(None)
        self.assertTrue(getattr(res, "success", False))
        self.assertEqual(len(calls), 1)
        self.assertNotIn("async", calls[0])

    def test_a_genuine_error_is_not_retried(self):
        res, calls = self._run("TypeError: Failed to fetch")
        self.assertFalse(getattr(res, "success", True))
        self.assertEqual(len(calls), 1)

    def test_when_the_retry_also_fails_the_original_error_surfaces(self):
        res, calls = self._run("SyntaxError: Illegal return statement",
                               wrapped_ok=False)
        self.assertFalse(getattr(res, "success", True))
        self.assertEqual(len(calls), 2)
        self.assertIn("Illegal return statement", str(res.error_message))


if __name__ == "__main__":
    unittest.main()
