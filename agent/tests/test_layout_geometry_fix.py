"""A2 (direction A) — inline measured LAYOUT GEOMETRY into each failing screen's remediation.

A1 validation (run-75): asset uptake driven 57→2, blocking screens reached 100% asset
coverage, yet their scores stayed 0.15-0.40 — the residual gap is the layout skeleton
(single-column vs two-column login = the 0.0→0.4 jump class) and per-component theme
colors. #52 already inlines measured hex (_spec_snippet); what never reached the lane
numerically is GEOMETRY: design_system screens[].layout + components[].region
(normalized rects). A2 renders them as percentages per failing screen, after the A1
asset mandate and before the MEASURED SPEC block. ENVGEN_LAYOUT_GEOMETRY_FIX=0 reverts.
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

from multi_agent.runtime.visual_fidelity import remediation_text  # noqa: E402


def _ds():
    return {
        "assets": [],
        "screens": [
            {"name": "login_light", "route": "/login", "kind": "page",
             "layout": "Two-column split layout (left hero, right form).",
             "components": [
                 {"id": "hero-section", "region": [0.03, 0.04, 0.45, 0.78],
                  "colors": {"bg": "#ffffff"}, "assets": []},
                 {"id": "login-form", "region": [0.55, 0.10, 0.97, 0.70],
                  "colors": {"bg": "#fafafa"}, "assets": []},
             ]},
        ],
    }


def _mk_out(tmp_path):
    out = tmp_path / "out"
    (out / "design").mkdir(parents=True)
    (out / "design" / "design_system.json").write_text(json.dumps(_ds()))
    src = out / "app" / "frontend" / "src"
    src.mkdir(parents=True)
    (src / "App.jsx").write_text("export default () => <div/>;")
    return out


def _failing_login():
    return {"screens": [
        {"name": "login_light", "route": "/login", "similarity": 0.20, "passed": False,
         "dimensions": {}, "deviations": [], "fixes": ["match the reference"]},
    ]}


def test_geometry_block_inlined_for_failing_screen(tmp_path):
    out = _mk_out(tmp_path)
    text = remediation_text(_failing_login(), str(out))
    sect = text[text.index("## login_light"):]
    assert "LAYOUT GEOMETRY" in sect
    assert "Two-column split layout" in sect, "the analyst layout sentence must be stated"
    # region [0.03, 0.04, 0.45, 0.78] → x 3-45%, y 4-78%, width 42%
    assert "hero-section" in sect and "3" in sect and "45%" in sect
    assert "#fafafa" in sect, "per-component bg hex rides along"
    # ordering: geometry precedes the MEASURED SPEC / judge fixes
    assert sect.index("LAYOUT GEOMETRY") < sect.index("match the reference")


def test_no_design_system_no_block(tmp_path):
    text = remediation_text(_failing_login(), str(tmp_path / "empty"))
    assert "LAYOUT GEOMETRY" not in text


def test_screen_without_regions_is_silent(tmp_path):
    out = _mk_out(tmp_path)
    ds = _ds()
    for c in ds["screens"][0]["components"]:
        c.pop("region")
    ds["screens"][0].pop("layout")
    (out / "design" / "design_system.json").write_text(json.dumps(ds))
    text = remediation_text(_failing_login(), str(out))
    assert "LAYOUT GEOMETRY" not in text, "nothing measured → no empty block"


def test_disable_switch(tmp_path, monkeypatch):
    monkeypatch.setenv("ENVGEN_LAYOUT_GEOMETRY_FIX", "0")
    out = _mk_out(tmp_path)
    text = remediation_text(_failing_login(), str(out))
    assert "LAYOUT GEOMETRY" not in text


def test_passed_screen_gets_no_geometry(tmp_path):
    out = _mk_out(tmp_path)
    result = {"screens": [{"name": "login_light", "route": "/login",
                           "similarity": 0.90, "passed": True, "dimensions": {}}]}
    text = remediation_text(result, str(out))
    assert "LAYOUT GEOMETRY" not in text


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
