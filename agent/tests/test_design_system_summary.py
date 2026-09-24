"""The measured design_system is folded into the requirements every lane reads (non-voluntary),
mirroring reference_materials.spec_summary_for_requirements. LOCAL-ONLY (agent/tests/ gitignored).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.design_prep import design_system_summary_for_requirements  # noqa: E402


def _ds():
    return {
        "design_system": {
            "palette": {"bg": "#0c1014", "surface": "#25292e", "accent_link": "#708dff",
                        "accent_button": "#0064e0"},
            "theme": {"default": "dark", "themes": ["dark"]},
            "type_scale": [{"role": "body", "size_px": 14, "weight": 400}],
            "material": "flat dark",
        },
        "assets": [{"id": "logo", "file": "icons/ig.svg", "staged_path": "public/assets/icons/ig.svg"},
                   {"id": "heart", "file": "icons/heart.svg"}],
        "screens": [{"name": "home_feed", "layout": "top bar + feed",
                     "components": [{"id": "top_nav", "colors": {"bg": "#0c1014"}, "assets": ["logo"]},
                                    {"id": "post_actions", "colors": {"accent": "#ff3040"},
                                     "assets": ["heart"]}]}],
    }


def test_summary_carries_measured_palette_and_assets_and_components():
    s = design_system_summary_for_requirements(_ds())
    assert "DESIGN SYSTEM" in s and "measured" in s.lower()
    # measured palette hexes present
    assert "#0c1014" in s and "#708dff" in s
    assert "dark" in s.lower()
    # real assets mapped with the /assets path + "don't draw"
    assert "logo" in s and "/assets/icons/ig.svg" in s
    assert "public/assets" in s
    # per-screen component colors + asset map
    assert "home_feed" in s and "top_nav" in s and "#ff3040" in s
    # binding pointer + measure-don't-guess
    assert "design_system.json" in s
    assert "guess" in s.lower()


def test_empty_design_system_yields_empty_summary():
    assert design_system_summary_for_requirements({}) == ""
    assert design_system_summary_for_requirements({"design_system": {}, "screens": []}) == ""


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
