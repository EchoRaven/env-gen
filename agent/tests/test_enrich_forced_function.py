"""FIX #92 — deliver the single-shot enrichment AS A FORCED FUNCTION CALL (run-12 live).

The -customtools Gemini variant resists no-tools long-form generation: run-8 answered the
enrich mega-prompt with a hallucinated 20-token tool call; with #88's JSON mode (run-12,
10:22:34) it answered finish=STOP but completion_tokens=11 — an empty JSON object. Same
prompt, AGENT path (with tools) produced 34 build_notes in run-9. Play WITH the model's
tuning: offer ONE function `submit_enriched_design_system` whose parameters ARE the
enriched doc and force the call (tool_choice='required' → Gemini FunctionCallingConfig
mode=ANY). Text-JSON stays as the fallback ladder. LOCAL-ONLY (agent/tests/ gitignored).
"""

import asyncio
import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.design_prep import _run_analyst  # noqa: E402

_SKEL = {"design_system": {"palette": {"bg": "#000"}}, "assets": [],
         "screens": [{"name": "home", "reference": "home.png",
                      "components": [{"id": "nav", "colors": {"bg": "#000"}}]}]}
_DOC = '{"design_system": {"type_scale": [{"role": "body", "size_px": 14}]}, "screens": [], "assets": []}'


class _Resp:
    def __init__(self, content="", tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls


class _ToolCallingClient:
    """Returns the doc as a forced tool call (the customtools happy path)."""
    def __init__(self):
        self.kwargs = None

    async def chat(self, messages, **kwargs):
        self.kwargs = kwargs
        if kwargs.get("tools"):
            return _Resp(tool_calls=[
                {"function": {"name": "submit_enriched_design_system",
                              "arguments": _DOC}}])
        return _Resp(content="{}")


class _TextOnlyClient:
    """Ignores tools, answers text JSON (fallback path must still parse)."""
    async def chat(self, messages, **kwargs):
        return _Resp(content=_DOC)


def test_enrich_offers_forced_function_and_parses_tool_args(tmp_path):
    c = _ToolCallingClient()
    out = asyncio.run(_run_analyst(_SKEL, {"references": []}, tmp_path, c, "", 6, 24))
    assert c.kwargs.get("tools"), "must offer the submit function"
    # #480: a bare "required" is rejected by the (now-stricter) vertex proxy with
    # BadRequestError 400 'tool_choice: Input should be a valid dictionary' — 59x in
    # r53, 0 in r51/r52, i.e. an environment tightening, not the caller. The single
    # screen-enrichment tool is now forced BY NAME, which is a stronger constraint
    # than "any tool", not a weaker one.
    assert c.kwargs.get("tool_choice") == {"type": "tool",
                                           "name": "submit_screen_enrichment"}
    assert out and out["design_system"]["type_scale"][0]["size_px"] == 14


def test_enrich_falls_back_to_text_json_when_no_tool_call(tmp_path):
    out = asyncio.run(_run_analyst(_SKEL, {"references": []}, tmp_path,
                                   _TextOnlyClient(), "", 6, 24))
    assert out and out["design_system"]["type_scale"][0]["role"] == "body"


def test_google_chat_maps_required_tool_choice_to_forced_mode():
    import utils.llm as ul
    src = inspect.getsource(ul)
    assert "FunctionCallingConfigMode.ANY" in src     # forced-call mode plumbed
