"""FIX #94 — CHUNK the single-shot enrichment per screen (run-13 + offline replay, 2026-07-06).

Three runs + a controlled offline replay pinned the residual cause: the -customtools model
refuses LARGE one-shot outputs on the mega multimodal prompt REGARDLESS of format — #88's
JSON mode got 11 tokens, #92's FORCED function call got a near-empty doc (1 screen, 0
components) on the exact same material where a tiny forced-call test returned instantly and
correctly. The model does small structured outputs happily; it collapses on big ones. So
the fallback now enriches PER SCREEN: one forced-function call per screen (its skeleton
slice + its reference image), merged best-effort — a failed screen never poisons the rest.
LOCAL-ONLY (agent/tests/ gitignored).
"""

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.design_prep import _run_analyst  # noqa: E402

_SKEL = {
    "design_system": {"palette": {"bg": "#000"}, "type_scale": []},
    "assets": [{"id": "logo", "file": "icons/logo.svg"}],
    "screens": [
        {"name": "home", "reference": "home.png",
         "components": [{"id": "nav", "colors": {"bg": "#000"}, "build_notes": ""}]},
        {"name": "profile", "reference": "profile.png",
         "components": [{"id": "header", "colors": {"bg": "#111"}, "build_notes": ""}]},
    ],
}


class _Resp:
    def __init__(self, content="", tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls


class _PerScreenClient:
    """Answers each per-screen call with that screen's enrichment."""
    def __init__(self, fail_screens=()):
        self.fail_screens = set(fail_screens)
        self.calls = 0

    async def chat(self, messages, **kwargs):
        self.calls += 1
        text = json.dumps([getattr(m, "content", "") for m in messages])
        screen = "home" if "home" in text else ("profile" if "profile" in text else "?")
        if screen in self.fail_screens:
            raise RuntimeError("boom")
        comp_id = {"home": "nav", "profile": "header"}.get(screen, "x")
        doc = {"layout": f"{screen} layout",
               "components": [{"id": comp_id, "build_notes": f"notes for {comp_id}"}],
               "type_scale": [{"role": "body", "size_px": 14, "weight": 400}]}
        return _Resp(tool_calls=[{"function": {
            "name": "submit_screen_enrichment", "arguments": json.dumps(doc)}}])


def test_per_screen_enrichment_merges_all_screens(tmp_path):
    c = _PerScreenClient()
    out = asyncio.run(_run_analyst(_SKEL, {"references": []}, tmp_path, c, "", 6, 24))
    assert out is not None
    assert c.calls >= 2                                    # one call per screen
    by_name = {s["name"]: s for s in out["screens"]}
    assert by_name["home"]["components"][0]["build_notes"] == "notes for nav"
    assert by_name["profile"]["components"][0]["build_notes"] == "notes for header"
    assert out["design_system"]["type_scale"]              # global scale harvested


def test_one_failed_screen_does_not_poison_the_rest(tmp_path):
    c = _PerScreenClient(fail_screens={"home"})
    out = asyncio.run(_run_analyst(_SKEL, {"references": []}, tmp_path, c, "", 6, 24))
    assert out is not None                                 # best-effort, not None
    by_name = {s["name"]: s for s in out["screens"]}
    assert by_name["profile"]["components"][0]["build_notes"] == "notes for header"
