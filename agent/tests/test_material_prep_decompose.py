"""Material-prep Brick 2: decompose_reference — gemini-vision names the components + regions,
material_prep MEASURES the colors per region (PIPELINE.md §2-4). Mock the vision call; assert the
parse + per-region color measurement.
"""

import asyncio
import sys
from pathlib import Path

import pytest

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

pytest.importorskip("PIL")
from PIL import Image, ImageDraw  # noqa: E402
from multi_agent.runtime.material_prep import decompose_reference  # noqa: E402


class _Resp:
    def __init__(self, content):
        self.content = content


class _Client:
    def __init__(self, content):
        self._content = content
    async def chat(self, messages, **kw):
        return _Resp(self._content)


class _LLM:
    """Mirrors the real wrapper: decompose_reference reads llm._client.chat."""
    def __init__(self, content):
        self._client = _Client(content)


def _ref(tmp_path):
    # top strip = gray chrome; a blue button in the lower-left region
    im = Image.new("RGB", (200, 200), (0x29, 0x29, 0x29))
    ImageDraw.Draw(im).rectangle([10, 120, 90, 180], fill=(0x27, 0x5d, 0xa0))
    p = tmp_path / "ref.png"
    im.save(p)
    return p


def test_decompose_parses_and_measures(tmp_path):
    p = _ref(tmp_path)
    vision_json = (
        'Here you go:\n['
        '{"name":"top_bar","region":[0,0,1,0.1],"role":"chrome strip","state":"neutral"},'
        '{"name":"action_button","region":[0.05,0.6,0.45,0.9],"role":"primary button","state":"default"}'
        ']'
    )
    res = asyncio.run(decompose_reference(p, _LLM(vision_json)))
    assert res.get("count") == 2 and "error" not in res
    comps = {c["name"]: c for c in res["components"]}
    # the top strip measures as gray chrome
    assert comps["top_bar"]["background"] == "#292929"
    # the button region measures the royal-blue accent
    assert comps["action_button"]["accents"].get("blue") == "#275da0"
    # regions + role/state preserved
    assert comps["action_button"]["region"] == [0.05, 0.6, 0.45, 0.9]
    assert comps["top_bar"]["role"] == "chrome strip"


def test_bad_region_falls_back_to_whole_image(tmp_path):
    p = _ref(tmp_path)
    res = asyncio.run(decompose_reference(
        p, _LLM('[{"name":"x","region":[2,2,1,1],"role":"r","state":"s"}]')))
    # invalid region (x0>x1) → background measured on the whole image instead of crashing
    assert res["count"] == 1 and res["components"][0]["background"] is not None


def test_non_json_response_errors_cleanly(tmp_path):
    res = asyncio.run(decompose_reference(_ref(tmp_path), _LLM("sorry, I cannot do that")))
    assert "error" in res and "components" not in res


def test_vision_call_failure_is_caught(tmp_path):
    class _Boom:
        class _c:
            async def chat(self, *a, **k):
                raise RuntimeError("rate limited")
        _client = _c()
    res = asyncio.run(decompose_reference(_ref(tmp_path), _Boom()))
    assert "error" in res and "vision call failed" in res["error"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
