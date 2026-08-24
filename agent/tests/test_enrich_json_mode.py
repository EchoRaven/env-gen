"""FIX #88 — the single-shot enrich call must FORCE JSON output (run-8 live, 05:40:36).

Run-8's #85a fallback fired correctly but STILL produced a hollow doc. The LLM log shows
why: the enrich call (messages=1, tools=0, 3.28MB multimodal) 'succeeded' with
completion_tokens=20, finish=tool_calls — the -customtools Gemini variant emitted a TOOL
CALL on a NO-TOOLS call (its thinking hallucinated a code-agent persona: 'locate
orchestrator.py'), so the JSON-extraction regex found nothing → enriched=None → skeleton
written, silently. Second latent killer: max_tokens=4000 cannot hold a 93-component
enriched doc (skeleton alone ≈3k tokens) → truncated JSON → json.loads fails → same
silent skeleton. Fix: google chat() honors response_mime_type (Gemini JSON mode — no
tool-call emission possible, valid JSON guaranteed); _run_analyst requests it with a
16k output budget and degrades gracefully for providers without the kwarg.
LOCAL-ONLY (agent/tests/ gitignored)."""

import asyncio
import inspect
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.design_prep import _run_analyst  # noqa: E402


class _Resp:
    def __init__(self, content):
        self.content = content


class _CapturingClient:
    def __init__(self):
        self.kwargs = None

    async def chat(self, messages, **kwargs):
        self.kwargs = kwargs
        return _Resp('{"design_system": {}, "screens": [], "assets": []}')


class _LegacyClient:                       # no response_mime_type support
    def __init__(self):
        self.calls = 0

    async def chat(self, messages, temperature=None, max_tokens=None):
        self.calls += 1
        return _Resp('{"design_system": {}, "screens": [], "assets": []}')


_SKEL = {"design_system": {"palette": {"bg": "#000"}}, "assets": [],
         "screens": [{"name": "home", "reference": "home.png",
                      "components": [{"id": "nav", "colors": {"bg": "#000"}}]}]}


def test_enrich_json_mode_is_the_fallback_after_empty_tool_path(tmp_path):
    """#92 made the FORCED FUNCTION CALL the primary channel; JSON mode (#88) is the
    fallback when the tool path yields neither a tool call nor text content."""

    class _EmptyToolThenJson:
        def __init__(self):
            self.calls = []

        async def chat(self, messages, **kwargs):
            self.calls.append(kwargs)
            if kwargs.get("tools"):
                return _Resp("")                      # tool path: no call, no text
            return _Resp('{"design_system": {}, "screens": [], "assets": []}')

    c = _EmptyToolThenJson()
    out = asyncio.run(_run_analyst(_SKEL, {"references": []}, tmp_path, c, "", 6, 24))
    assert out is not None
    # #480: a bare "required" is rejected by the (now-stricter) vertex proxy with
    # BadRequestError 400 'tool_choice: Input should be a valid dictionary' — 59x in
    # r53, 0 in r51/r52, i.e. an environment tightening, not the caller. The single
    # screen-enrichment tool is now forced BY NAME, which is a stronger constraint
    # than "any tool", not a weaker one.
    assert c.calls[0].get("tool_choice") == {"type": "tool",
                                             "name": "submit_screen_enrichment"}
    assert c.calls[1].get("response_mime_type") == "application/json"  # fallback: JSON mode
    # #94 chunked per-screen: each call needs room for ONE screen's enrichment (the old
    # 4k whole-doc budget starved a ~100-component doc; per-screen 6k is comfortable)
    assert all(k.get("max_tokens", 0) >= 6000 for k in c.calls)


def test_enrich_degrades_for_clients_without_json_mode(tmp_path):
    c = _LegacyClient()
    out = asyncio.run(_run_analyst(_SKEL, {"references": []}, tmp_path, c, "", 6, 24))
    assert out is not None                            # TypeError → retried without the kwarg
    assert c.calls >= 1


def test_google_chat_plumbs_response_mime_type():
    import utils.llm as ul
    src = inspect.getsource(ul)
    assert "response_mime_type" in src                # kwarg honored in the google config
