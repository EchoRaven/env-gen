"""§15 PIL layout measurement — the field manual's "key weapon" for spacing/columns/width the
agent can't eyeball. Theme-agnostic (content = pixels far from the region's measured background),
so it works on light AND dark UIs. LOCAL-ONLY (agent/tests/ gitignored).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import multi_agent.runtime.material_prep as mp  # noqa: E402


def _img(w, h, bg=(12, 14, 20)):
    from PIL import Image
    return Image.new("RGB", (w, h), bg)


def _fill(im, x0, y0, x1, y1, color):
    from PIL import ImageDraw
    ImageDraw.Draw(im).rectangle([x0, y0, x1 - 1, y1 - 1], fill=color)


def test_content_bounds_finds_the_content_box():
    im = _img(100, 100)
    _fill(im, 20, 30, 60, 70, (210, 210, 210))       # bright content block
    b = mp.content_bounds(im)
    assert abs(b["left_px"] - 20) <= 3 and abs(b["right_px"] - 60) <= 3
    assert abs(b["top_px"] - 30) <= 3 and abs(b["bottom_px"] - 70) <= 3
    assert abs(b["width_px"] - 40) <= 5
    assert abs(b["left"] - 0.20) <= 0.03            # fractions too


def test_content_bounds_empty_region():
    im = _img(40, 40)
    assert mp.content_bounds(im).get("content") is False


def test_grid_columns_counts_cells_between_gap_lines():
    # 4 bright cells (24px) separated by 6px dark gaps → 4 columns (the §15② explore case)
    im = _img(120, 40)
    for c in range(4):
        x0 = c * 30
        _fill(im, x0, 0, x0 + 24, 40, (200, 200, 200))
    g = mp.grid_columns(im)
    assert g["columns"] == 4, g
    assert len(g["band_centers_px"]) == 4


def test_row_bands_finds_nav_item_centers_and_spacing():
    # a left-nav column: 3 icons as bright bands at known y-centers (§15③)
    im = _img(30, 210)
    for cy in (40, 90, 140):
        _fill(im, 5, cy - 10, 25, cy + 10, (220, 220, 220))
    r = mp.row_bands(im)
    assert r["bands"] == 3
    centers = r["centers_px"]
    assert all(abs(a - b) <= 4 for a, b in zip(centers, [40, 90, 140]))
    assert abs(r["item_gap_px"] - 50) <= 6          # 90-40, 140-90


def test_row_bands_clusters_fragmented_line_icons():
    # a nav of 3 "line icons", each fragmented into 2 sub-bands (internal gap) — clustering must
    # recover 3 ITEMS with the true item gap, not 6 fragmented bands (§15③ 聚类成各图标 y 中心)
    im = _img(30, 260)
    for cy in (40, 120, 200):                     # true item centers, 80px apart
        _fill(im, 5, cy - 12, 25, cy - 4, (220, 220, 220))   # top half of the icon
        _fill(im, 5, cy + 4, 25, cy + 12, (220, 220, 220))   # bottom half (internal gap between)
    r = mp.row_bands(im)
    assert r["bands"] >= 6                         # raw bands fragmented
    assert r["items"] == 3                         # clustered back to 3 items
    assert abs(r["item_gap_px"] - 80) <= 8         # true item pitch recovered
    assert all(abs(a - b) <= 6 for a, b in zip(r["item_centers_px"], [40, 120, 200]))


def test_measure_layout_dispatch():
    im = _img(120, 40)
    for c in range(3):
        _fill(im, c * 40, 0, c * 40 + 30, 40, (200, 200, 200))
    assert mp.measure_layout(im, None, "grid_columns")["columns"] == 3
    assert "width_px" in mp.measure_layout(im, None, "content_width")
    assert "bands" in mp.measure_layout(im, None, "row_spacing")


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
