"""Design-Prep Task 3 — deterministic skeleton design_system (measure, no LLM).

build_skeleton_design_system(resolved, output_dir, existing_specs=None) measures the palette
from the references, ingests+stages the assets into design/assets/, and carries the pre-measured
component colors (from design/component_specs/<stem>.json) into screens[].components[], leaving
assets:[] for the analyst to map. Deterministic, best-effort. LOCAL-ONLY (agent/tests/ gitignored).
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


def _write_png(path, size=(64, 24), color=(255, 255, 255)):
    from PIL import Image
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path)


def test_skeleton_has_palette_assets_and_measured_components(tmp_path):
    di = tmp_path / "design_input"
    (di / "references").mkdir(parents=True)
    (di / "assets").mkdir(parents=True)
    _write_png(di / "references" / "home.png")
    (di / "assets" / "logo.svg").write_text('<svg width="10" height="10"/>', encoding="utf-8")

    out = tmp_path / "out"
    # a pre-measured component spec on disk (as reference_materials writes it), keyed by stem
    specs = out / "design" / "component_specs"
    specs.mkdir(parents=True)
    (specs / "home.json").write_text(json.dumps({
        "reference": "home.png", "count": 1,
        "components": [{"name": "top_nav", "region": [0, 0, 1, 0.1],
                        "role": "global chrome", "state": "",
                        "background": "#ffffff", "accents": {"blue": "#3880f3"}}],
    }), encoding="utf-8")

    resolved = {"references": [str(di / "references" / "home.png")], "docs": [],
                "assets_dir": str(di / "assets")}
    ds = build_skeleton_design_system(resolved, out)

    # palette measured (non-empty bg)
    assert ds["design_system"]["palette"].get("bg")
    assert ds["design_system"]["theme"]["default"] in ("light", "dark")

    # assets ingested + staged under design/assets
    assert [a["id"] for a in ds["assets"]] == ["logo"]
    assert (out / "design" / "assets" / "logo.svg").exists()

    # screen carries the measured component colors; assets left empty for the analyst
    screen = ds["screens"][0]
    assert screen["name"] == "home"
    comp = screen["components"][0]
    assert comp["id"] == "top-nav"
    assert comp["colors"]["bg"] == "#ffffff"
    assert comp["colors"]["accent"] == "#3880f3"
    assert comp["assets"] == []
    assert comp["region"] == [0, 0, 1, 0.1]
    assert comp["role"] == "global chrome"


def test_skeleton_no_specs_still_produces_screen(tmp_path):
    di = tmp_path / "design_input"
    (di / "references").mkdir(parents=True)
    _write_png(di / "references" / "feed.png", color=(12, 16, 19))  # dark → theme dark
    resolved = {"references": [str(di / "references" / "feed.png")], "docs": [], "assets_dir": None}
    ds = build_skeleton_design_system(resolved, tmp_path / "out")
    assert ds["assets"] == []
    assert ds["screens"][0]["name"] == "feed"
    assert ds["screens"][0]["components"] == []          # no specs → no components yet
    assert ds["design_system"]["theme"]["default"] == "dark"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
