"""#1065 — one transient `Page.screenshot` error priced a good page at 0.00.

The capture loop called `await page.screenshot(...)` once. #769's handler spells
out what a failure costs, in its own words:

    "#769 capture FAILED for screen '%s' (%s): %s: %s. No screenshot, so this
     screen scores 0.00 downstream — that zero is about the capture, not the page."

So a transient CDP/protocol error — the kind that shows up under repeated browser
start/stop — makes the visual gate score a page that may be perfect at zero. It is
also what made test_verdict_cache_by_pixels flaky: the file's four browser tests
share a process, and roughly one run in four lost a screenshot that way, taking
the screen out of the report entirely.

One retry after a short settle. If the second attempt also fails, the ORIGINAL
exception propagates, so #769 still records the deviation and a genuinely broken
page is priced exactly as before.
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

from multi_agent.runtime.visual_fidelity import (  # noqa: E402
    _screenshot_with_retry_1065 as _shot,
)


class _Page:
    """Fails its first `fail_times` screenshot calls, then succeeds."""

    def __init__(self, fail_times=0, exc=None):
        self.fail_times = fail_times
        self.calls = 0
        self.waits = 0
        self.exc = exc or RuntimeError("Page.screenshot: Protocol error")

    async def screenshot(self, path=None):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        Path(path).write_bytes(b"png")

    async def wait_for_timeout(self, ms):
        self.waits += 1


class ATransientFailureIsRescued(unittest.TestCase):

    def setUp(self):
        import tempfile
        self.dest = Path(tempfile.mkdtemp()) / "home.png"

    def test_a_clean_shot_is_taken_once(self):
        p = _Page(fail_times=0)
        asyncio.run(_shot(p, self.dest))
        self.assertEqual(p.calls, 1, "no retry when the first attempt works")
        self.assertEqual(p.waits, 0)
        self.assertTrue(self.dest.exists())

    def test_one_failure_is_retried_and_succeeds(self):
        p = _Page(fail_times=1)
        asyncio.run(_shot(p, self.dest))
        self.assertEqual(p.calls, 2)
        self.assertEqual(p.waits, 1, "it settles before retrying")
        self.assertTrue(self.dest.exists(), "the screen is captured, not scored 0.00")


class APersistentFailureIsUnchanged(unittest.TestCase):

    def setUp(self):
        import tempfile
        self.dest = Path(tempfile.mkdtemp()) / "home.png"

    def test_two_failures_raise_the_original(self):
        boom = RuntimeError("Page.screenshot: Protocol error: the FIRST one")
        p = _Page(fail_times=2, exc=boom)
        with self.assertRaises(RuntimeError) as ctx:
            asyncio.run(_shot(p, self.dest))
        self.assertIs(ctx.exception, boom,
                      "#769 must still see the original cause, not the retry's")
        self.assertEqual(p.calls, 2, "bounded — exactly one retry, never a loop")

    def test_a_broken_wait_does_not_mask_the_failure(self):
        class _NoWait(_Page):
            async def wait_for_timeout(self, ms):
                raise RuntimeError("page is gone")
        p = _NoWait(fail_times=2)
        with self.assertRaises(RuntimeError):
            asyncio.run(_shot(p, self.dest))
        self.assertEqual(p.calls, 2, "the retry still happens if the settle fails")


if __name__ == "__main__":
    unittest.main()
