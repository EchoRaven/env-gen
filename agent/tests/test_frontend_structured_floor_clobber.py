"""#221 AUTHORITATIVE STRUCTURED FLOOR (re-enabled page-projector).

Confirmed UI-fidelity gap: the frontend page-projector emits a REFERENCE-STRUCTURED
page (_render_reference_page: measured component-region bands + real data, marked
_STRUCTURED_MARKER / data-projected="ref") for any ui_page whose route matches a
MEASURED design screen — but scaffold_pages_from_contract only wrote projected pages
when-MISSING, so the lane (which authors every page) was never clobbered and the
structured projection never shipped (r7/r8: 0 projected pages; per-screen fidelity
~0.10-0.15 vs the 0.65 bar).

Fix: for a ui_page WITH a matching design screen, the structured projection is
authoritative — it clobbers a lane-authored page (the measured floor the lane then
refines in place). Guards:
  (a) a matched screen → the file is (re)written with the structured floor EVEN when
      it already exists (clobbers the lane's generic page);
  (b) NO matched screen → an existing lane page is NEVER clobbered;
  (c) a page that ALREADY carries the structured marker (the lane refined it in place)
      is NOT re-clobbered → refinement survives.
Everything derives from design_system.json — app-agnostic; no product literals.
"""
import json
import tempfile
from pathlib import Path

from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    scaffold_pages_from_contract)
from env_generator.llm_generator.multi_agent.runtime.frontend_page_projector import (
    _STRUCTURED_MARKER)


# A measured design with ONE screen (route /browse) carrying component regions, so
# _design_screen_for_route matches it and _render_reference_page projects the floor.
# No screen for /settings → that route has no reference-faithful layout.
_DESIGN = {
    "design_system": {
        "palette": {"bg": "#141414", "accent": "#e50914",
                    "surface": "#222222", "text": "#f5f5f5"},
        "theme": {"default": "dark"},
    },
    "screens": [
        {"route": "/browse", "kind": "page", "name": "browse_home",
         "components": [
             {"region": [0.0, 0.0, 0.17, 1.0], "role": "nav",
              "colors": {"bg": "#000000"}},
             {"region": [0.17, 0.0, 1.0, 1.0], "role": "main",
              "colors": {"bg": "#141414"}},
         ]},
    ],
}

# lane-authored, GENERIC page bodies — no structured marker / data-projected attr.
_LANE_BROWSE = ("export default function BrowseHomePage() {\n"
                "  return <div className=\"lane-generic\">hand-authored browse</div>;\n"
                "}\n")
_LANE_SETTINGS = ("export default function SettingsPage() {\n"
                  "  return <div className=\"lane-generic\">hand-authored settings</div>;\n"
                  "}\n")


def _mk_env(pages_on_disk):
    """<out>/app/frontend + <out>/design/design_system.json (the convention
    _load_design_for_projection reads: frontend_dir.parent.parent/design/...).
    Pre-writes the given {ComponentName: body} page files (simulating the lane)."""
    out = Path(tempfile.mkdtemp())
    fe = out / "app" / "frontend"
    pages = fe / "src" / "pages"
    pages.mkdir(parents=True, exist_ok=True)
    (out / "design").mkdir(parents=True, exist_ok=True)
    (out / "design" / "design_system.json").write_text(
        json.dumps(_DESIGN), encoding="utf-8")
    for comp, body in (pages_on_disk or {}).items():
        (pages / f"{comp}.jsx").write_text(body, encoding="utf-8")
    return fe, pages


def _is_structured(text: str) -> bool:
    return (_STRUCTURED_MARKER in text) or ('data-projected="ref"' in text)


def test_matched_screen_clobbers_existing_lane_page():
    # (a) a ui_page WITH a matching design screen: the lane already authored a
    #     generic page, but the structured floor CLOBBERS it (target.exists()).
    fe, pages = _mk_env({"BrowseHomePage": _LANE_BROWSE})
    ui_pages = [
        {"name": "browse_home_page", "route": "/browse",
         "component": "BrowseHomePage", "apis_used": ["GET /api/titles"]},
    ]
    scaffold_pages_from_contract(fe, ui_pages)
    out = (pages / "BrowseHomePage.jsx").read_text(encoding="utf-8")
    assert _is_structured(out), "matched-screen page must ship the structured floor"
    assert "lane-generic" not in out, "the lane's generic page must be clobbered"
    # non-breaking to the functional half: the page still wires its GET endpoint.
    assert "/api/titles" in out, "projected page must still fetch its GET endpoint"


def test_no_matched_screen_preserves_lane_page():
    # (b) a ui_page WITHOUT a matching design screen: the lane's real UI is NEVER
    #     clobbered (design has no /settings screen).
    fe, pages = _mk_env({"SettingsPage": _LANE_SETTINGS})
    ui_pages = [
        {"name": "settings_page", "route": "/settings",
         "component": "SettingsPage", "apis_used": ["GET /api/settings"]},
    ]
    scaffold_pages_from_contract(fe, ui_pages)
    out = (pages / "SettingsPage.jsx").read_text(encoding="utf-8")
    assert out == _LANE_SETTINGS, "no matched screen → lane page untouched"
    assert not _is_structured(out)


def test_already_structured_page_not_reclobbered():
    # (c) refinement survives: a page that ALREADY carries the structured marker
    #     (the lane refined the floor in place) is NOT re-clobbered — otherwise the
    #     lane could never lift fidelity past the raw floor.
    refined = (_STRUCTURED_MARKER + "\n"
               "export default function BrowseHomePage() {\n"
               "  // LANE REFINEMENT sentinel\n"
               "  return <div data-projected=\"ref\">refined-by-lane</div>;\n"
               "}\n")
    fe, pages = _mk_env({"BrowseHomePage": refined})
    ui_pages = [
        {"name": "browse_home_page", "route": "/browse",
         "component": "BrowseHomePage", "apis_used": ["GET /api/titles"]},
    ]
    scaffold_pages_from_contract(fe, ui_pages)
    out = (pages / "BrowseHomePage.jsx").read_text(encoding="utf-8")
    assert out == refined, "an already-structured (lane-refined) page must survive"
    assert "refined-by-lane" in out


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
