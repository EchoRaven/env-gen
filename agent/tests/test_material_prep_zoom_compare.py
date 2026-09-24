"""Material-prep Brick 3: make_side_by_side / zoom_compare — labeled REFERENCE-over-MINE
2x-zoom diff of a component (PIPELINE.md §5.2/§6), so the lane/critic view_images it and
catches the micro-differences a whole-page glance misses.
"""

import asyncio
import sys
from pathlib import Path

import pytest

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

pytest.importorskip("PIL")
from PIL import Image  # noqa: E402
from multi_agent.runtime.material_prep import make_side_by_side  # noqa: E402
from tools.material_prep_tools import create_material_prep_tools  # noqa: E402


class _WS:
    def __init__(self, base):
        self._base = Path(base)
    def resolve(self, p):
        return self._base / p


def _imgs(tmp_path):
    Image.new("RGB", (300, 200), (0x29, 0x29, 0x29)).save(tmp_path / "ref.png")
    Image.new("RGB", (240, 160), (0x10, 0x10, 0x10)).save(tmp_path / "mine.png")  # different size on purpose


def test_make_side_by_side_whole(tmp_path):
    _imgs(tmp_path)
    w, h = make_side_by_side(tmp_path / "ref.png", tmp_path / "mine.png",
                             tmp_path / "out.png", width=400)
    assert (tmp_path / "out.png").exists()
    assert w == 400 and h > 0          # normalized to the requested width, stacked taller


def test_region_and_zoom(tmp_path):
    _imgs(tmp_path)
    make_side_by_side(tmp_path / "ref.png", tmp_path / "mine.png", tmp_path / "z.png",
                      region=[0.2, 0.3, 0.6, 0.7], scale=2, width=300)
    assert (tmp_path / "z.png").exists()


def test_empty_region_raises(tmp_path):
    _imgs(tmp_path)
    with pytest.raises(Exception):
        make_side_by_side(tmp_path / "ref.png", tmp_path / "mine.png", tmp_path / "x.png",
                          region=[0.5, 0.5, 0.5, 0.5])   # zero-area


def test_zoom_compare_tool(tmp_path):
    _imgs(tmp_path)
    tool = {t.NAME: t for t in create_material_prep_tools(workspace=_WS(tmp_path))}["zoom_compare"]
    r = asyncio.run(tool.execute(reference="ref.png", mine="mine.png",
                                 save_as="design/compare/c.png", region=[0, 0.5, 1, 1], scale=2))
    assert r.success and r.data["saved_path"] == "design/compare/c.png"
    assert "view_image" in r.data["next"]
    assert (_WS(tmp_path).resolve("design/compare/c.png")).exists()


def test_zoom_compare_tool_missing_mine_fails(tmp_path):
    _imgs(tmp_path)
    tool = {t.NAME: t for t in create_material_prep_tools(workspace=_WS(tmp_path))}["zoom_compare"]
    r = asyncio.run(tool.execute(reference="ref.png", mine="nope.png", save_as="x.png"))
    assert r.success is False and "screenshot not found" in (r.error_message or "")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
