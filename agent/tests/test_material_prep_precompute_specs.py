"""Material-prep PRE-GEN step (USER directive 2026-06-29 — "材料准备阶段在生成前"):
precompute_component_specs decomposes EACH reference screenshot into a per-component build
spec at design/component_specs/<stem>.json BEFORE any lane wakes, so the frontend lane builds
to MEASURED colors from its first turn. Mock the vision call; assert the artifacts + env gate.
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
from multi_agent.runtime.reference_materials import precompute_component_specs  # noqa: E402


class _Resp:
    def __init__(self, content):
        self.content = content


class _Client:
    def __init__(self, content):
        self._content = content
        self.calls = 0
    async def chat(self, messages, **kw):
        self.calls += 1
        return _Resp(self._content)


class _LLM:
    def __init__(self, content):
        self._client = _Client(content)


class _Log:
    def __init__(self):
        self.msgs = []
    def info(self, *a):
        self.msgs.append(("info", a))
    def warning(self, *a):
        self.msgs.append(("warning", a))


_VISION = (
    '[{"name":"top_bar","region":[0,0,1,0.12],"role":"chrome strip","state":"neutral"},'
    '{"name":"action_button","region":[0.05,0.6,0.45,0.9],"role":"primary button","state":"default"}]'
)


def _ref(dirpath, name="screen_one.png"):
    im = Image.new("RGB", (200, 200), (0x29, 0x29, 0x29))
    ImageDraw.Draw(im).rectangle([10, 120, 90, 180], fill=(0x27, 0x5d, 0xa0))
    p = Path(dirpath) / name
    im.save(p)
    return str(p)


def test_precompute_writes_per_screen_spec(tmp_path, monkeypatch):
    monkeypatch.delenv("ENVGEN_COMPONENT_SPECS", raising=False)
    img = _ref(tmp_path)
    written = asyncio.run(precompute_component_specs(
        [img], output_dir=tmp_path, llm=_LLM(_VISION), logger=_Log()))
    assert written == ["design/component_specs/screen_one.json"]
    spec_path = tmp_path / "design" / "component_specs" / "screen_one.json"
    assert spec_path.exists()
    import json
    data = json.loads(spec_path.read_text())
    assert data["reference"] == "screen_one.png" and data["count"] == 2
    comps = {c["name"]: c for c in data["components"]}
    # colors are MEASURED, not guessed
    assert comps["top_bar"]["background"] == "#292929"
    assert comps["action_button"]["accents"].get("blue") == "#275da0"


def test_multiple_references_each_get_a_spec(tmp_path, monkeypatch):
    monkeypatch.delenv("ENVGEN_COMPONENT_SPECS", raising=False)
    a = _ref(tmp_path, "inbox.png")
    b = _ref(tmp_path, "compose.png")
    written = asyncio.run(precompute_component_specs(
        [a, b], output_dir=tmp_path, llm=_LLM(_VISION), logger=_Log()))
    assert set(written) == {
        "design/component_specs/inbox.json", "design/component_specs/compose.json"}


def test_env_disable_returns_empty_and_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("ENVGEN_COMPONENT_SPECS", "0")
    img = _ref(tmp_path)
    written = asyncio.run(precompute_component_specs(
        [img], output_dir=tmp_path, llm=_LLM(_VISION), logger=_Log()))
    assert written == []
    assert not (tmp_path / "design" / "component_specs").exists()


def test_no_images_returns_empty(tmp_path, monkeypatch):
    monkeypatch.delenv("ENVGEN_COMPONENT_SPECS", raising=False)
    written = asyncio.run(precompute_component_specs(
        [], output_dir=tmp_path, llm=_LLM(_VISION), logger=_Log()))
    assert written == []


def test_vision_failure_skips_that_screen(tmp_path, monkeypatch):
    monkeypatch.delenv("ENVGEN_COMPONENT_SPECS", raising=False)
    img = _ref(tmp_path)
    # non-JSON vision response → decompose returns {error}; the screen is skipped, no crash
    written = asyncio.run(precompute_component_specs(
        [img], output_dir=tmp_path, llm=_LLM("sorry, cannot"), logger=_Log()))
    assert written == []
    assert not (tmp_path / "design" / "component_specs" / "screen_one.json").exists()


def test_default_cap_covers_a_full_reference_set(tmp_path, monkeypatch):
    # Regression (real run 2026-06-30): the decompose cap was inherited from the
    # spec-compile budget (6), so a 9-page app left 3 screens with NO measured
    # build spec. The default must cover a full reference set — every screen gets one.
    monkeypatch.delenv("ENVGEN_COMPONENT_SPECS", raising=False)
    imgs = [_ref(tmp_path, f"page_{i}.png") for i in range(9)]
    written = asyncio.run(precompute_component_specs(
        imgs, output_dir=tmp_path, llm=_LLM(_VISION), logger=_Log()))
    assert len(written) == 9


def test_max_images_caps_the_decomposition(tmp_path, monkeypatch):
    monkeypatch.delenv("ENVGEN_COMPONENT_SPECS", raising=False)
    imgs = [_ref(tmp_path, f"s{i}.png") for i in range(4)]
    written = asyncio.run(precompute_component_specs(
        imgs, output_dir=tmp_path, llm=_LLM(_VISION), logger=_Log(), max_images=2))
    assert len(written) == 2


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
