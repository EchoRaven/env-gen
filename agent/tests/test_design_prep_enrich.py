"""Design-Prep Task 4 — single-shot analyst enrichment.

enrich_design_system(skeleton, resolved, output_dir, llm) makes ONE multimodal call (measured
facts + reference/asset images + manifest + docs → enriched JSON), merges it so MEASURED colors
always win, and writes design/design_system.json + design/design_system.md. Best-effort: on any
LLM error the SKELETON is written (deterministic facts still ship). LOCAL-ONLY.
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

from multi_agent.runtime.design_prep import enrich_design_system  # noqa: E402


class _MockLLM:
    def __init__(self, content=None, raise_=False):
        self._content, self._raise = content, raise_
        self.calls = 0

    async def chat(self, messages, **kw):
        self.calls += 1
        if self._raise:
            raise RuntimeError("vision boom")
        return types.SimpleNamespace(content=self._content)


def _png(path, size=(24, 24), color=(52, 128, 243)):
    from PIL import Image
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path)


def _skeleton(out, ref_path):
    _png(out / "design" / "assets" / "logo.png")  # staged raster asset
    return {
        "design_system": {"palette": {"bg": "#ffffff", "accent": "#3880f3"},
                           "theme": {"default": "light", "themes": ["light"]},
                           "type_scale": [], "radius_scale": {}, "shadow_scale": [],
                           "iconography": {}},
        "assets": [{"id": "logo", "file": "logo.png", "type": "png", "dims": [24, 24],
                    "transparent": False, "dominant_colors": ["#3880f3"],
                    "staged_path": "public/assets/logo.png"}],
        "screens": [{"name": "home", "reference": Path(ref_path).name, "layout": "",
                     "components": [{"id": "top-nav", "region": [0, 0, 1, 0.1],
                                     "colors": {"bg": "#ffffff", "accent": "#3880f3"},
                                     "assets": [], "role": "chrome", "state": "",
                                     "crop": None, "build_notes": ""}]}],
    }


_ENRICHED = json.dumps({
    "design_system": {"palette": {"bg": "#000000", "surface": "#1f1f22", "text": "#f5f5f5"},
                      "type_scale": [{"role": "h1", "size_px": 40, "weight": 700}],
                      "iconography": {"style": "line"}},
    "assets": [{"id": "logo", "description": "brand wordmark", "use": ["top nav"]}],
    "screens": [{"name": "home", "layout": "top bar + feed",
                 "components": [{"id": "top-nav", "assets": ["logo"],
                                 "build_notes": "white bar, wordmark left",
                                 "typography": {"brand": {"size_px": 24, "weight": 700}}}]}],
})


def test_enrich_maps_assets_and_preserves_measured_colors(tmp_path):
    ref = tmp_path / "refs" / "home.png"
    _png(ref)
    out = tmp_path / "out"
    skel = _skeleton(out, ref)
    resolved = {"references": [str(ref)], "docs": [], "assets_dir": None}

    ds = asyncio.run(enrich_design_system(skel, resolved, out, _MockLLM(content=_ENRICHED),
                                          docs_text="brand guide"))

    comp = ds["screens"][0]["components"][0]
    assert comp["assets"] == ["logo"]                     # analyst mapped the real asset
    assert comp["build_notes"] == "white bar, wordmark left"
    assert comp["typography"]["brand"]["size_px"] == 24
    # MEASURED colors survive the merge (enriched tried to set bg #000000 on the component — ignored)
    assert comp["colors"]["bg"] == "#ffffff"
    # measured palette bg preserved; analyst-only keys (surface/text) added
    assert ds["design_system"]["palette"]["bg"] == "#ffffff"
    assert ds["design_system"]["palette"]["surface"] == "#1f1f22"
    assert ds["design_system"]["type_scale"][0]["role"] == "h1"
    a = {x["id"]: x for x in ds["assets"]}["logo"]
    assert a["description"] == "brand wordmark" and a["use"] == ["top nav"]

    # both artifacts written
    written = json.loads((out / "design" / "design_system.json").read_text())
    assert written["screens"][0]["components"][0]["assets"] == ["logo"]
    assert (out / "design" / "design_system.md").exists()


def test_enrich_llm_error_writes_skeleton(tmp_path):
    ref = tmp_path / "refs" / "home.png"
    _png(ref)
    out = tmp_path / "out"
    skel = _skeleton(out, ref)
    resolved = {"references": [str(ref)], "docs": [], "assets_dir": None}

    ds = asyncio.run(enrich_design_system(skel, resolved, out, _MockLLM(raise_=True)))
    # never raises; skeleton is written (measured facts preserved), no analyst mapping
    assert ds["screens"][0]["components"][0]["assets"] == []
    assert ds["design_system"]["palette"]["bg"] == "#ffffff"
    written = json.loads((out / "design" / "design_system.json").read_text())
    assert written["screens"][0]["components"][0]["build_notes"] == ""


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
