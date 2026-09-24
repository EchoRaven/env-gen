"""Material-prep AGENT TOOLS (USER directive 2026-06-29): sample_color / crop_reference /
extract_palette — pipeline-conforming tool calls so the frontend lane MEASURES colors + crops
components off the reference at runtime (PIPELINE.md §3) instead of guessing.
"""

import asyncio
import sys
from pathlib import Path

import pytest

AGENT_DIR = Path(__file__).resolve().parents[1]
LLM_DIR = AGENT_DIR / "env_generator" / "llm_generator"
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(LLM_DIR))

pytest.importorskip("PIL")
from PIL import Image, ImageDraw  # noqa: E402
from tools.material_prep_tools import create_material_prep_tools  # noqa: E402


class _WS:
    """Minimal workspace stub: resolve(path) -> base/path (what the real Workspace does)."""
    def __init__(self, base):
        self._base = Path(base)
    def resolve(self, p):
        return self._base / p


@pytest.fixture
def ws(tmp_path):
    im = Image.new("RGB", (200, 120), (0x29, 0x29, 0x29))
    ImageDraw.Draw(im).rectangle([10, 80, 70, 110], fill=(0x27, 0x5d, 0xa0))  # blue button
    (tmp_path / "design" / "references").mkdir(parents=True)
    im.save(tmp_path / "design" / "references" / "ref.png")
    return _WS(tmp_path)


def _tools(ws):
    return {t.NAME: t for t in create_material_prep_tools(workspace=ws)}


def test_deterministic_tools_present(ws):
    assert set(_tools(ws)) == {"sample_color", "crop_reference", "extract_palette",
                               "zoom_compare", "measure_layout"}
    for t in _tools(ws).values():
        assert t.tool_definition is not None         # has a schema for the agent runtime


def test_sample_color_background_and_accent(ws):
    t = _tools(ws)["sample_color"]
    bg = asyncio.run(t.execute(image="design/references/ref.png", kind="background"))
    assert bg.success and bg.data["hex"] == "#292929"
    ac = asyncio.run(t.execute(image="design/references/ref.png", kind="accent", hue="blue"))
    assert ac.success and ac.data["hex"] == "#275da0"


def test_extract_palette(ws):
    r = asyncio.run(_tools(ws)["extract_palette"].execute(image="design/references/ref.png"))
    assert r.success and r.data["background"] == "#292929"
    assert r.data["accents"].get("blue") == "#275da0"


def test_crop_reference_saves_and_points_to_view_image(ws):
    r = asyncio.run(_tools(ws)["crop_reference"].execute(
        image="design/references/ref.png", region=[0, 0.6, 0.4, 0.95],
        save_as="design/component_crops/btn.png"))
    assert r.success and r.data["saved_path"] == "design/component_crops/btn.png"
    assert "view_image" in r.data["next"]
    assert (ws.resolve("design/component_crops/btn.png")).exists()


def test_missing_image_fails_cleanly(ws):
    r = asyncio.run(_tools(ws)["sample_color"].execute(image="design/references/nope.png"))
    assert r.success is False and "not found" in (r.error_message or "")


def test_bad_region_fails_cleanly(ws):
    r = asyncio.run(_tools(ws)["crop_reference"].execute(
        image="design/references/ref.png", region=[1, 2], save_as="x.png"))
    assert r.success is False


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
