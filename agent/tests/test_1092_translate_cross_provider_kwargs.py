"""#1092 — 33 MB of requests that could never succeed, in r95's first twelve minutes.

`design_prep._chat_ladder_inner` is a deliberate three-rung ladder — forced-function →
JSON-mode → plain text — and each rung degrades on `except Exception`. The rungs speak two
foreign dialects:

    rung 1   tool_choice={"type": "tool", "name": "submit_screen_enrichment"}   (Anthropic)
    rung 2   response_mime_type="application/json"                              (Gemini)

`OpenAIClient.chat` ends in `request_params.update(kwargs)`, so both go straight to the SDK.
Live in r95, against the OpenAI-compatible gateway the whole tiktok/netflix corpus runs on:

    Error code: 400 — 'Invalid `tool_choice` parameter'                         x15
    TypeError: AsyncCompletions.create() got an unexpected keyword 'response_mime_type'  x15

Each is retried three times by the client before the ladder degrades, and these are multimodal
design payloads: the failed requests measured 1.9 MB, 2.3 MB, 4.5 MB, 4.7 MB and 7.9 MB —
**33.1 MB sent in twelve minutes that could not have worked**. Rung 3 then succeeds, so the
run is correct and merely pays for it; the TypeError rung is worse than useless, since a
TypeError is deterministic and retrying it can never change the answer.

Both dialects have exact OpenAI equivalents, so the fix is a translation rather than a drop —
strictly better than degrading, because the rung then does what it was written to do:

    {"type": "tool", "name": X}      ->  {"type": "function", "function": {"name": X}}
    response_mime_type="application/json"  ->  response_format={"type": "json_object"}

The Gemini path is untouched (`test_enrich_json_mode.py`'s contract: google honours
response_mime_type), an already-OpenAI-shaped value passes through, and an explicit
`response_format` from the caller always wins.
"""
from __future__ import annotations

import asyncio
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from utils.llm import (LLMConfig, LLMProvider, Message,  # noqa: E402
                       OpenAIClient)


class _Captured(Exception):
    def __init__(self, params):
        self.params = params


class _FakeCompletions:
    async def create(self, **params):
        raise _Captured(params)


class _FakeClient:
    def __init__(self):
        self.chat = types.SimpleNamespace(completions=_FakeCompletions())


def _params(**kw) -> dict:
    """#1202zm: the capture sentinel is an EXCEPTION, so `chat`'s retry path treats it as a
    failure and backs off — measured in-process, this file asked `asyncio.sleep` for **30.0
    seconds across 20 calls**, and the whole file took 30.3 s of a 720 s suite. Neutering the
    backoff takes it to 0.71 s.

    This test is about PARAMETER TRANSLATION, not about retry timing, so it says so by making
    the wait a no-op for the duration of the capture. `time.sleep` is not touched because it
    was measured at 0 calls here; patching what is not used would be cargo cult.
    """
    cfg = LLMConfig(provider=LLMProvider.OPENAI, model_name="m", api_key="k")
    c = OpenAIClient(cfg)
    c._client = _FakeClient()
    _real_sleep = asyncio.sleep

    async def _no_wait(_delay, *a, **k):
        return await _real_sleep(0)

    asyncio.sleep = _no_wait
    try:
        asyncio.run(c.chat([Message.user("hi")], **kw))
    except _Captured as e:
        return e.params
    except Exception as e:                      # any other error means it never reached create()
        raise AssertionError(f"did not reach the SDK: {type(e).__name__}: {e}")
    finally:
        asyncio.sleep = _real_sleep             # never leave the module patched
    raise AssertionError("create() did not raise the capture sentinel")


class TheAnthropicToolChoiceIsTranslated(unittest.TestCase):

    def test_the_rung_1_shape_becomes_the_openai_shape(self):
        p = _params(tools=[{"name": "submit_screen_enrichment", "description": "d",
                            "input_schema": {"type": "object", "properties": {}}}],
                    tool_choice={"type": "tool", "name": "submit_screen_enrichment"})
        self.assertEqual(p.get("tool_choice"),
                         {"type": "function",
                          "function": {"name": "submit_screen_enrichment"}})

    def test_an_openai_shaped_value_is_untouched(self):
        native = {"type": "function", "function": {"name": "x"}}
        self.assertEqual(_params(tool_choice=native).get("tool_choice"), native)

    def test_the_string_forms_are_untouched(self):
        for s in ("auto", "none", "required"):
            self.assertEqual(_params(tool_choice=s).get("tool_choice"), s)


class TheGeminiJsonModeIsTranslated(unittest.TestCase):

    def test_application_json_becomes_response_format(self):
        p = _params(response_mime_type="application/json")
        self.assertEqual(p.get("response_format"), {"type": "json_object"})
        self.assertNotIn("response_mime_type", p,
                         "the Gemini-only kwarg still reaches the SDK (TypeError x3)")

    def test_an_explicit_response_format_wins(self):
        p = _params(response_mime_type="application/json",
                    response_format={"type": "text"})
        self.assertEqual(p.get("response_format"), {"type": "text"})

    def test_an_unsupported_mime_type_is_dropped_not_forwarded(self):
        p = _params(response_mime_type="text/x-python")
        self.assertNotIn("response_mime_type", p)
        self.assertNotIn("response_format", p)


class OrdinaryCallsAreUnchanged(unittest.TestCase):

    def test_nothing_is_invented_when_neither_is_passed(self):
        p = _params()
        self.assertNotIn("tool_choice", p)
        self.assertNotIn("response_format", p)

    def test_other_kwargs_still_forward(self):
        self.assertEqual(_params(seed=7).get("seed"), 7)


if __name__ == "__main__":
    unittest.main()


class TheCaptureHelperLeavesTheEventLoopAlone(unittest.TestCase):
    """#1202zm: `_params` neuters `asyncio.sleep` so the retry backoff does not cost 30 s.

    A patch that LEAKED would be far worse than the 30 s it saves: every other test in the
    suite would silently stop waiting, and a real backoff regression would pass unnoticed.
    """

    def test_the_sleep_is_restored(self):
        before = asyncio.sleep
        _params(tool_choice="auto")
        self.assertIs(asyncio.sleep, before, "asyncio.sleep is still patched")

    def test_it_is_restored_even_when_the_capture_fails(self):
        before = asyncio.sleep
        cfg = LLMConfig(provider=LLMProvider.OPENAI, model_name="m", api_key="k")
        c = OpenAIClient(cfg)

        class _Boom:
            def __init__(self):
                self.chat = types.SimpleNamespace(
                    completions=types.SimpleNamespace(create=self._raise))
            async def _raise(self, **params):
                raise RuntimeError("not the sentinel")
        c._client = _Boom()
        _real = asyncio.sleep

        async def _no_wait(_d, *a, **k):
            return await _real(0)
        asyncio.sleep = _no_wait
        try:
            with self.assertRaises(Exception):
                asyncio.run(c.chat([Message.user("hi")]))
        finally:
            asyncio.sleep = _real
        self.assertIs(asyncio.sleep, before)

    def test_the_helper_declares_why_it_patches(self):
        """A bare `asyncio.sleep = ...` in a test reads as a mistake; the measurement is what
        makes it a decision."""
        import inspect
        src = inspect.getsource(_params)
        self.assertIn("30.0", src, "the measured cost is not recorded next to the patch")
        self.assertIn("finally", src, "nothing restores the real sleep")
