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
    cfg = LLMConfig(provider=LLMProvider.OPENAI, model_name="m", api_key="k")
    c = OpenAIClient(cfg)
    c._client = _FakeClient()
    try:
        asyncio.run(c.chat([Message.user("hi")], **kw))
    except _Captured as e:
        return e.params
    except Exception as e:                      # any other error means it never reached create()
        raise AssertionError(f"did not reach the SDK: {type(e).__name__}: {e}")
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
