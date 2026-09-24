"""FIX #220 — deterministic per-component GEOMETRY in the skeleton design system.

The design_analyst schema has always promised a structured ``geometry`` per
component (columns / gaps), but no run ever fills it (LLM-optional), so page
projection has only fractional regions to work from. The skeleton now MEASURES
geometry deterministically (material_prep.grid_columns / row_bands) for every
component with a usable region, and screen-level content bounds — no LLM.
LOCAL-ONLY (agent/tests/ gitignored).
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.design_prep import build_skeleton_design_system  # noqa: E402


def _grid_png(path, size=(300, 300), bg=(255, 255, 255)):
    """White canvas with three dark full-height column blocks in y ∈ [60, 300)."""
    from PIL import Image, ImageDraw
    path.parent.mkdir(parents=True, exist_ok=True)
    im = Image.new("RGB", size, bg)
    d = ImageDraw.Draw(im)
    # keep the white background DOMINANT (real screenshots are bg-dominant);
    # otherwise the region's measured bg flips to the ink and gutters count
    for x0, x1 in ((20, 60), (120, 160), (220, 260)):
        d.rectangle([x0, 60, x1, 299], fill=(20, 20, 20))
    im.save(path)


def test_component_geometry_measured_deterministically(tmp_path):
    di = tmp_path / "design_input"
    (di / "references").mkdir(parents=True)
    _grid_png(di / "references" / "explore.png")

    out = tmp_path / "out"
    specs = out / "design" / "component_specs"
    specs.mkdir(parents=True)
    (specs / "explore.json").write_text(json.dumps({
        "reference": "explore.png", "count": 2,
        "components": [
            {"name": "content_grid", "region": [0.0, 0.2, 1.0, 1.0],
             "role": "masonry grid of cards", "state": "",
             "background": "#ffffff", "accents": {}},
            # tiny chrome sliver — too small to measure meaningfully
            {"name": "dot", "region": [0.0, 0.0, 0.02, 0.02],
             "role": "", "state": "", "background": "#ffffff", "accents": {}},
        ],
    }), encoding="utf-8")

    resolved = {"references": [str(di / "references" / "explore.png")],
                "docs": [], "assets_dir": None}
    ds = build_skeleton_design_system(resolved, out)

    screen = ds["screens"][0]
    grid = screen["components"][0]
    geo = grid.get("geometry") or {}
    assert geo.get("columns") == 3          # measured, not guessed
    assert geo.get("pitch_px")              # column pitch present
    # tiny region → no geometry fabricated
    assert not (screen["components"][1].get("geometry") or {})
    # screen-level content bounds measured
    lm = screen.get("layout_metrics") or {}
    assert lm.get("content") is True
    assert lm.get("width_px")


def test_missing_image_still_builds_without_geometry(tmp_path):
    """Unreadable reference → skeleton still builds; geometry simply absent."""
    di = tmp_path / "design_input"
    (di / "references").mkdir(parents=True)
    ref = di / "references" / "home.png"
    ref.write_text("not a png", encoding="utf-8")
    out = tmp_path / "out"
    specs = out / "design" / "component_specs"
    specs.mkdir(parents=True)
    (specs / "home.json").write_text(json.dumps({
        "reference": "home.png", "count": 1,
        "components": [{"name": "nav", "region": [0, 0, 1, 0.1],
                        "role": "", "state": "", "background": "#ffffff",
                        "accents": {}}],
    }), encoding="utf-8")
    resolved = {"references": [str(ref)], "docs": [], "assets_dir": None}
    ds = build_skeleton_design_system(resolved, out)
    comp = ds["screens"][0]["components"][0]
    assert not (comp.get("geometry") or {})


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))


def test_screen_tool_schema_offers_all_scales():
    """#220b — shadow_scale was absent from the forced-function schema, so on
    the tool-call path it was STRUCTURALLY impossible to fill; and the prompt's
    'if readable' invited omission. All four global scale keys must be offered."""
    from multi_agent.runtime.design_prep import _SCREEN_TOOL, _SCREEN_PROMPT
    props = _SCREEN_TOOL[0]["function"]["parameters"]["properties"]
    for key in ("type_scale", "radius_scale", "shadow_scale", "iconography"):
        assert key in props, key
    assert "if readable" not in _SCREEN_PROMPT
    assert "shadow_scale" in _SCREEN_PROMPT
