"""Guard: FIX #187 — Gemini-variance hardening in utils/llm.py.

Three env-agnostic robustness rungs (evidence: handoff 2026-07-18 §3-1/3-3):
1. _prune_stale_images_for_reroll — MALFORMED_FUNCTION_CALL storms correlate with
   huge MULTIMODAL contexts (tiktok-r4 design analyst died mid a 3.98M-char
   request; gm_val_run14 hit 571 MALFORMEDs). After repeated malformed re-rolls,
   drop all but the newest inline image (replaced with a text placeholder) so the
   re-roll isn't the same doomed payload.
2. _retry_with_backoff grants MALFORMED-specific extra attempts (mirror of the
   existing rate-limit extension): temperature re-rolls need more than 2 shots
   during a storm, but generic errors must NOT get a bigger budget.
3. _llm_hard_timeout — config.timeout defaults to 1800s, so the per-call
   watchdog could hold a lane 30min on one wedged SDK call before cancelling
   (§3-3 "silent stall" appearance). Cap the watchdog at 600s by default
   (observed real-call max 237s), tunable via ENVGEN_LLM_HARD_TIMEOUT_S.
"""

import asyncio
import sys
import unittest
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AGENT_DIR))

from utils.llm import (  # noqa: E402
    BaseLLMClient, _prune_stale_images_for_reroll, _llm_hard_timeout,
    _extend_retry_budget,
)
from utils.config import LLMConfig, LLMProvider  # noqa: E402


class _FakePart:
    def __init__(self, text=None, inline_data=None):
        self.text = text
        self.inline_data = inline_data


class _FakeContent:
    def __init__(self, role, parts):
        self.role = role
        self.parts = parts


def _mk_text(t):
    return _FakePart(text=t)


class PruneStaleImagesTests(unittest.TestCase):
    def test_keeps_only_last_image_and_replaces_older(self):
        c1 = _FakeContent("user", [_FakePart(text="a"), _FakePart(inline_data=b"img1")])
        c2 = _FakeContent("user", [_FakePart(inline_data=b"img2"),
                                   _FakePart(text="b"),
                                   _FakePart(inline_data=b"img3")])
        pruned, n = _prune_stale_images_for_reroll([c1, c2], 1, _mk_text)
        self.assertEqual(n, 2)
        # newest image (img3) survives; img1/img2 became text placeholders
        self.assertIsNone(pruned[0].parts[1].inline_data)
        self.assertTrue(pruned[0].parts[1].text)
        self.assertIsNone(pruned[1].parts[0].inline_data)
        self.assertEqual(pruned[1].parts[2].inline_data, b"img3")
        # original inputs never mutated (the caller may retry with them again)
        self.assertEqual(c1.parts[1].inline_data, b"img1")
        self.assertEqual(c2.parts[0].inline_data, b"img2")

    def test_no_images_is_noop(self):
        c1 = _FakeContent("user", [_FakePart(text="a")])
        pruned, n = _prune_stale_images_for_reroll([c1], 1, _mk_text)
        self.assertEqual(n, 0)
        self.assertEqual(pruned[0].parts[0].text, "a")

    def test_keep_last_two(self):
        cs = [_FakeContent("user", [_FakePart(inline_data=bytes([i]))]) for i in range(4)]
        pruned, n = _prune_stale_images_for_reroll(cs, 2, _mk_text)
        self.assertEqual(n, 2)
        self.assertIsNone(pruned[0].parts[0].inline_data)
        self.assertIsNone(pruned[1].parts[0].inline_data)
        self.assertEqual(pruned[2].parts[0].inline_data, bytes([2]))
        self.assertEqual(pruned[3].parts[0].inline_data, bytes([3]))

    def test_never_raises_on_weird_shapes(self):
        pruned, n = _prune_stale_images_for_reroll(None, 1, _mk_text)
        self.assertEqual(n, 0)
        pruned, n = _prune_stale_images_for_reroll(
            [_FakeContent("user", None)], 1, _mk_text)
        self.assertEqual(n, 0)


class _StubClient(BaseLLMClient):
    async def chat(self, *a, **k):
        raise NotImplementedError

    async def chat_stream(self, *a, **k):
        raise NotImplementedError

    async def complete(self, *a, **k):
        raise NotImplementedError


def _cfg():
    return LLMConfig(provider=LLMProvider.GOOGLE, model_name="test-model",
                     retry_attempts=3, retry_delay=0.001)


class MalformedExtraRetryTests(unittest.TestCase):
    def _run(self, coro):
        return asyncio.run(coro)

    def test_malformed_gets_extra_attempts(self):
        client = _StubClient(_cfg())
        calls = {"n": 0}

        async def flaky():
            calls["n"] += 1
            if calls["n"] <= 4:
                raise RuntimeError(
                    "gemini returned MALFORMED_FUNCTION_CALL — retrying generation")
            return "ok"

        # 3 normal attempts fail, MALFORMED extension (default 2) grants more:
        # the 5th call succeeds. Without the extension this raises.
        self.assertEqual(self._run(client._retry_with_backoff(flaky)), "ok")
        self.assertEqual(calls["n"], 5)

    def test_generic_error_gets_no_extension(self):
        client = _StubClient(_cfg())
        calls = {"n": 0}

        async def broken():
            calls["n"] += 1
            raise RuntimeError("boom")

        with self.assertRaises(RuntimeError):
            self._run(client._retry_with_backoff(broken))
        self.assertEqual(calls["n"], 3)  # plain budget, no extension

    def test_malformed_extension_is_bounded(self):
        client = _StubClient(_cfg())
        calls = {"n": 0}

        async def always_malformed():
            calls["n"] += 1
            raise RuntimeError("gemini returned MALFORMED_FUNCTION_CALL")

        with self.assertRaises(RuntimeError):
            self._run(client._retry_with_backoff(always_malformed))
        self.assertEqual(calls["n"], 5)  # 3 + exactly 2 extra, then give up


class ExtendRetryBudgetTests(unittest.TestCase):
    """_extend_retry_budget is the pure extension rule. NOTE: the old inline
    rate-limit extension was DEAD CODE (the `attempt == max_retries-1` check sat
    inside `attempt < total_attempts-1` — mutually exclusive on the last
    attempt), so rate limits never actually got their extra attempts. The pure
    function is called on EVERY failure, so both extensions really fire."""

    def test_malformed_extends_once_on_last_attempt(self):
        # last normal attempt (attempt=2 of 3): extend to 3+2
        self.assertEqual(
            _extend_retry_budget(True, False, 2, 3, 3, 2, 3), 5)

    def test_malformed_does_not_extend_twice(self):
        # already extended to 5: attempt 4 is the true last — no re-extension
        self.assertEqual(
            _extend_retry_budget(True, False, 4, 5, 3, 2, 3), 5)

    def test_rate_limit_extension_now_fires(self):
        self.assertEqual(
            _extend_retry_budget(False, True, 2, 3, 3, 2, 3), 6)

    def test_generic_error_never_extends(self):
        self.assertEqual(
            _extend_retry_budget(False, False, 2, 3, 3, 2, 3), 3)

    def test_no_extension_before_last_attempt(self):
        self.assertEqual(
            _extend_retry_budget(True, False, 0, 3, 3, 2, 3), 3)
        self.assertEqual(
            _extend_retry_budget(True, False, 1, 3, 3, 2, 3), 3)

    def test_both_flags_take_the_larger_budget(self):
        self.assertEqual(
            _extend_retry_budget(True, True, 2, 3, 3, 2, 3), 6)


class HardTimeoutCapTests(unittest.TestCase):
    def test_default_caps_large_config_timeout(self):
        self.assertEqual(_llm_hard_timeout(1800, {}), 600.0)

    def test_small_config_timeout_wins(self):
        self.assertEqual(_llm_hard_timeout(240, {}), 240.0)

    def test_none_falls_back(self):
        self.assertEqual(_llm_hard_timeout(None, {}), 240.0)

    def test_env_override_raises_cap(self):
        self.assertEqual(
            _llm_hard_timeout(1800, {"ENVGEN_LLM_HARD_TIMEOUT_S": "1200"}), 1200.0)

    def test_env_garbage_ignored(self):
        self.assertEqual(
            _llm_hard_timeout(1800, {"ENVGEN_LLM_HARD_TIMEOUT_S": "nope"}), 600.0)


if __name__ == "__main__":
    unittest.main()
