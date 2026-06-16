"""Reference-spec compile robustness (2026-06-13): per-image fallback + merge.

A single combined multimodal call (all reference screenshots at once) is what
gpt-class models handle in one shot, but gemini-3.x intermittently returns
``MALFORMED_FUNCTION_CALL`` on the large multimodal request — observed live on
the instagram run, where the reference design spec compiled to NOTHING and the
frontend built blind (visual fidelity 0.20). ``compile_reference_spec`` now tries
the combined call first (unchanged fast path) and, when it yields nothing usable,
recompiles PER-IMAGE (plus one text-only call) and merges. The smaller calls
succeed where the combined one malforms.
"""

from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

import multi_agent.runtime.reference_materials as RM  # noqa: E402


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    finally:
        asyncio.set_event_loop(None)
        loop.close()


# ── _merge_specs (pure) ──────────────────────────────────────────────────────

def test_merge_unions_and_dedups():
    merged = RM._merge_specs([
        {"screens": [{"name": "login"}], "endpoints": [{"method": "GET", "path": "/api/feed"}],
         "entities": [{"name": "users"}], "acceptance": ["a"]},
        {"screens": [{"name": "login"}, {"name": "feed"}],  # login dup
         "endpoints": [{"method": "POST", "path": "/api/feed"},  # same path, diff method → kept
                       {"method": "GET", "path": "/api/feed"}],  # full dup
         "entities": [{"name": "posts"}], "acceptance": ["a", "b"]},
    ])
    assert [s["name"] for s in merged["screens"]] == ["login", "feed"]
    assert {(e["method"], e["path"]) for e in merged["endpoints"]} == {
        ("GET", "/api/feed"), ("POST", "/api/feed")}
    assert {e["name"] for e in merged["entities"]} == {"users", "posts"}
    assert merged["acceptance"] == ["a", "b"]


def test_merge_handles_empty_and_nondict():
    assert RM._merge_specs([]) == {k: [] for k in RM._SPEC_LIST_KEYS}
    assert RM._merge_specs([{}, None, {"screens": [{"name": "x"}]}])["screens"] == [{"name": "x"}]


def test_spec_nonempty_requires_buildable_signal():
    assert RM._spec_nonempty({"screens": [{"name": "x"}]}) is True
    assert RM._spec_nonempty({"endpoints": [{"path": "/api/x"}]}) is True
    assert RM._spec_nonempty({"acceptance": ["only criteria"]}) is False  # acceptance alone ≠ usable
    assert RM._spec_nonempty({}) is False


# ── orchestration: combined-first, per-image fallback ─────────────────────────

class _FakeLLM:
    """Stands in for the orchestrator's LLM wrapper. compile_reference_spec calls
    ``getattr(llm, "_client", llm).chat([...])`` → ``.content``. We sequence the
    canned responses so the test can simulate combined-success vs combined-fail."""

    def __init__(self, contents):
        self._contents = list(contents)
        self.calls = 0
        self._client = self

    async def chat(self, messages, **kwargs):
        i = min(self.calls, len(self._contents) - 1)
        self.calls += 1
        return types.SimpleNamespace(content=self._contents[i])


_VALID = '{"screens":[{"name":"feed"}],"endpoints":[{"method":"GET","path":"/api/feed"}],"entities":[{"name":"posts"}],"mcp_tools":[],"acceptance":[]}'
_EMPTY = "I could not produce a spec."  # no JSON object → _parse_spec returns {}


def _compile(llm, imgs):
    # patch base64-readable images: point at this very file (any readable bytes)
    return _run(RM.compile_reference_spec(llm, imgs, [], "raw req"))


def test_combined_success_takes_fast_path(tmp_path):
    img = tmp_path / "a.png"
    img.write_bytes(b"\x89PNG fake")
    llm = _FakeLLM([_VALID])
    spec = _compile(llm, [str(img)])
    assert RM._spec_nonempty(spec)
    assert llm.calls == 1  # one combined call, no fallback


def test_combined_failure_falls_back_per_image(tmp_path):
    imgs = []
    for n in ("a", "b", "c"):
        p = tmp_path / f"{n}.png"
        p.write_bytes(b"\x89PNG fake")
        imgs.append(str(p))
    # call 1 = combined (empty/MALFORMED-like) → fallback: text-only + 3 per-image (valid)
    llm = _FakeLLM([_EMPTY, _VALID, _VALID, _VALID, _VALID])
    spec = _compile(llm, imgs)
    assert RM._spec_nonempty(spec)              # rescued via fallback
    assert llm.calls == 1 + 1 + 3               # combined + text-only + 3 images
    assert [s["name"] for s in spec["screens"]] == ["feed"]  # merged + deduped


def test_all_calls_fail_returns_empty(tmp_path):
    img = tmp_path / "a.png"
    img.write_bytes(b"\x89PNG fake")
    llm = _FakeLLM([_EMPTY])  # every call yields nothing parseable
    spec = _compile(llm, [str(img)])
    assert spec == {}                            # graceful: callers treat spec as optional


def test_no_materials_short_circuits():
    llm = _FakeLLM([_VALID])
    assert _run(RM.compile_reference_spec(llm, [], [], "")) == {}
    assert llm.calls == 0
