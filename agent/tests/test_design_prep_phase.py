"""Design-Prep Task 5 — the phase entry (run_design_prep) composing resolve→skeleton→enrich.

run_design_prep(design_input, reference_dir, reference_images, output_dir, llm) reads the docs,
builds the measured skeleton (consuming any design/component_specs/* the upstream precompute
wrote), runs the single-shot analyst, and writes all artifacts under <output_dir>/design/.
Best-effort; {} on total failure. LOCAL-ONLY (agent/tests/ gitignored).
"""

import asyncio
import json
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.design_prep import run_design_prep  # noqa: E402


class _MockLLM:
    async def chat(self, messages, **kw):
        return types.SimpleNamespace(content=json.dumps({
            "design_system": {"palette": {"surface": "#1f1f22"}},
            "screens": [{"name": "home", "layout": "top bar + feed",
                         "components": [{"id": "top-nav", "assets": ["logo"],
                                         "build_notes": "white bar, wordmark left"}]}],
            "assets": [{"id": "logo", "description": "brand wordmark", "use": ["top nav"]}],
        }))


def _png(path, size=(64, 24), color=(255, 255, 255)):
    from PIL import Image
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path)


def test_phase_end_to_end(tmp_path):
    di = tmp_path / "design_input"
    (di / "references").mkdir(parents=True)
    (di / "docs").mkdir(parents=True)
    (di / "assets").mkdir(parents=True)
    _png(di / "references" / "home.png")
    (di / "docs" / "brand.md").write_text("# Brand\nUse the wordmark in the top bar.")
    _png(di / "assets" / "logo.png")

    out = tmp_path / "out"
    # simulate the upstream precompute having written a component spec for the 'home' screen
    specs = out / "design" / "component_specs"
    specs.mkdir(parents=True)
    (specs / "home.json").write_text(json.dumps({
        "reference": "home.png", "count": 1,
        "components": [{"name": "top_nav", "region": [0, 0, 1, 0.1], "role": "chrome",
                        "state": "", "background": "#ffffff", "accents": {"blue": "#3880f3"}}],
    }))

    ds = asyncio.run(run_design_prep(str(di), None, [], out, _MockLLM()))

    # returned + persisted design system carries the measured component + analyst mapping
    comp = ds["screens"][0]["components"][0]
    assert comp["colors"]["bg"] == "#ffffff"          # measured, from component_specs
    assert comp["assets"] == ["logo"]                 # analyst mapped the real asset
    assert comp["build_notes"] == "white bar, wordmark left"
    assert ds["design_system"]["palette"]["surface"] == "#1f1f22"

    # artifacts on disk
    assert (out / "design" / "design_system.json").exists()
    assert (out / "design" / "design_system.md").exists()
    assert (out / "design" / "assets" / "logo.png").exists()     # staged
    assert (out / "design" / "component_specs" / "home.json").exists()  # upstream, untouched


def test_phase_never_raises(tmp_path):
    # totally empty design_input + a broken llm → returns a dict, never raises
    class _Boom:
        async def chat(self, *a, **k):
            raise RuntimeError("boom")
    di = tmp_path / "empty"
    di.mkdir()
    ds = asyncio.run(run_design_prep(str(di), None, [], tmp_path / "out", _Boom()))
    assert isinstance(ds, dict)


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
