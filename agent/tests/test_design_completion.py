"""FIX #80 — deterministic post-analyst design_system COMPLETION pass.

complete_design_system(ds, resolved, output_dir) runs AFTER the design_analyst (or the
single-shot fallback) accepted a design_system.json, and deterministically fills what the
LLM skipped (model-variance hardening, no LLM):
 - physical crops: every component with a region gets design/crops/<screen>__<comp>.png
 - missing colors.bg: measured via region_background on the reference region
 - empty component assets: conservative whole-token filename→role/id/state mapping
 - rewrites design_system.json + .md; best-effort, never raises; measured facts never change.
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

from multi_agent.runtime.design_prep import complete_design_system  # noqa: E402


def _write_png(path, size=(100, 100), color=(10, 20, 30), top_color=None):
    """Solid image; if top_color, the top 20% rows use it (a 'chrome strip')."""
    from PIL import Image
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    im = Image.new("RGB", size, color)
    if top_color:
        for y in range(int(size[1] * 0.2)):
            for x in range(size[0]):
                im.putpixel((x, y), top_color)
    im.save(path)


def _ds(components, assets=None, screen="home", reference="home.png"):
    return {
        "design_system": {"palette": {"bg": "#0a141e"}, "theme": {"default": "dark", "themes": ["dark"]},
                          "type_scale": [], "radius_scale": {}, "shadow_scale": [], "iconography": {}},
        "assets": assets or [],
        "screens": [{"name": screen, "reference": reference, "layout": "", "components": components}],
    }


def _setup(tmp_path, **png_kw):
    out = tmp_path / "out"
    ref = out / "design" / "references" / "home.png"
    _write_png(ref, **png_kw)
    resolved = {"references": [str(ref)], "docs": [], "assets_dir": None}
    return out, resolved


def test_completion_crops_every_component_region(tmp_path):
    out, resolved = _setup(tmp_path)
    ds = _ds([{"id": "top-nav", "region": [0.0, 0.0, 1.0, 0.2], "colors": {"bg": "#0a141e"},
               "assets": [], "role": "nav", "state": "", "crop": None, "build_notes": ""}])
    done = complete_design_system(ds, resolved, out)
    comp = done["screens"][0]["components"][0]
    assert comp["crop"] == "design/crops/home__top-nav.png"
    assert (out / "design" / "crops" / "home__top-nav.png").exists()


def test_completion_fills_missing_bg_measured(tmp_path):
    # top strip is a distinct solid color — the measured bg of the top region
    out, resolved = _setup(tmp_path, color=(10, 20, 30), top_color=(200, 100, 50))
    ds = _ds([{"id": "chrome", "region": [0.0, 0.0, 1.0, 0.2], "colors": {},
               "assets": [], "role": "", "state": "", "crop": None, "build_notes": ""}])
    done = complete_design_system(ds, resolved, out)
    assert done["screens"][0]["components"][0]["colors"]["bg"] == "#c86432"


def test_completion_preserves_existing_measurements_and_assets(tmp_path):
    out, resolved = _setup(tmp_path, color=(10, 20, 30))
    crop_rel = "design/crops/pre-existing.png"
    _write_png(out / crop_rel)
    ds = _ds([{"id": "card", "region": [0.0, 0.2, 1.0, 1.0], "colors": {"bg": "#123456"},
               "assets": ["logo"], "role": "card", "state": "", "crop": crop_rel,
               "build_notes": "keep"}],
             assets=[{"id": "logo", "file": "icons/Logo_ab12cd34.svg", "type": "svg"}])
    done = complete_design_system(ds, resolved, out)
    comp = done["screens"][0]["components"][0]
    assert comp["colors"]["bg"] == "#123456"          # measured fact untouched
    assert comp["crop"] == crop_rel                   # existing crop kept
    assert comp["assets"] == ["logo"]                 # analyst mapping kept
    assert comp["build_notes"] == "keep"


def test_completion_maps_assets_by_name_tokens_conservatively(tmp_path):
    out, resolved = _setup(tmp_path)
    assets = [
        {"id": "comment-03a4fe3b", "file": "icons/Comment_03a4fe3b.svg", "type": "svg"},
        {"id": "also-from-meta-12cc7c0e", "file": "icons/Also_from_Meta_12cc7c0e.svg", "type": "svg"},
        {"id": "icon-3e1a4815", "file": "icons/icon_3e1a4815.svg", "type": "svg"},  # generic → never auto-mapped
    ]
    ds = _ds([
        {"id": "post-actions", "region": [0.0, 0.5, 1.0, 0.6], "colors": {"bg": "#0a141e"},
         "assets": [], "role": "action bar with like, comment and share icons", "state": "",
         "crop": None, "build_notes": ""},
        {"id": "caption", "region": [0.0, 0.6, 1.0, 0.7], "colors": {"bg": "#0a141e"},
         "assets": [], "role": "caption text", "state": "", "crop": None, "build_notes": ""},
    ], assets=assets)
    done = complete_design_system(ds, resolved, out)
    comps = {c["id"]: c for c in done["screens"][0]["components"]}
    assert comps["post-actions"]["assets"] == ["comment-03a4fe3b"]
    assert comps["caption"]["assets"] == []            # no token match → stays empty


def test_completion_preserves_agent_authored_md(tmp_path):
    """FIX #85c (run-6 live): the analyst's ONE real deliverable — a hand-written 4665-char
    design_system.md — was clobbered by the completion pass's re-render. A .md without the
    framework's render marker is agent prose: leave it; write the render alongside."""
    out, resolved = _setup(tmp_path)
    agent_md = "# My hand-measured design doc\n\nnav rail is 72px, icons 24px stroke 1.5\n"
    (out / "design").mkdir(parents=True, exist_ok=True)
    (out / "design" / "design_system.md").write_text(agent_md, encoding="utf-8")
    ds = _ds([{"id": "top-nav", "region": [0.0, 0.0, 1.0, 0.2], "colors": {"bg": "#0a141e"},
               "assets": [], "role": "nav", "state": "", "crop": None, "build_notes": ""}])
    complete_design_system(ds, resolved, out)
    assert (out / "design" / "design_system.md").read_text(encoding="utf-8") == agent_md


def test_completion_overwrites_framework_rendered_md(tmp_path):
    """a framework-rendered .md (carries the render marker) is derived output — re-render."""
    out, resolved = _setup(tmp_path)
    ds = _ds([{"id": "top-nav", "region": [0.0, 0.0, 1.0, 0.2], "colors": {"bg": "#0a141e"},
               "assets": [], "role": "nav", "state": "", "crop": None, "build_notes": ""}])
    complete_design_system(ds, resolved, out)                 # writes marked render
    first = (out / "design" / "design_system.md").read_text(encoding="utf-8")
    assert "rendered by design-prep" in first                 # marker present
    ds["screens"][0]["components"][0]["build_notes"] = "new note"
    complete_design_system(ds, resolved, out)
    second = (out / "design" / "design_system.md").read_text(encoding="utf-8")
    assert "new note" in second                               # marked file re-rendered


def test_completion_rewrites_files_and_never_raises(tmp_path):
    out, resolved = _setup(tmp_path)
    ds = _ds([{"id": "top-nav", "region": [0.0, 0.0, 1.0, 0.2], "colors": {},
               "assets": [], "role": "nav", "state": "", "crop": None, "build_notes": ""}])
    complete_design_system(ds, resolved, out)
    on_disk = json.loads((out / "design" / "design_system.json").read_text(encoding="utf-8"))
    assert on_disk["screens"][0]["components"][0]["crop"] == "design/crops/home__top-nav.png"

    # best-effort: a screen whose reference image is MISSING must not raise
    ds_bad = _ds([{"id": "x", "region": [0, 0, 1, 1], "colors": {}, "assets": [],
                   "role": "", "state": "", "crop": None, "build_notes": ""}],
                 screen="ghost", reference="ghost.png")
    done = complete_design_system(ds_bad, {"references": []}, out)
    assert done["screens"][0]["components"][0]["crop"] is None
