"""FIX #132 — the design-prep analyst's per-screen classification (kind/requires_auth/
route in design_system.json) is the AUTHORITATIVE reference->route/overlay mapping for
the visual gate; filename heuristics (#128 regex, keyword catalog) become the fallback.

Root cause (run-47 autopsy, user question 3): "which pages get compared" was decided by
GUESSING routes from reference FILENAMES at judge time, while design_system.json screens
carried route=None/interaction='' — mislabeled references (search_flyout = feed+modal)
produced permanent 0.00s. Now the analyst classifies each reference FROM PIXELS at
design-prep time and the gate reads it back.

ENV-AGNOSTIC + LOCAL-ONLY (agent/tests/ gitignored).
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.visual_fidelity import (  # noqa: E402
    load_screen_classifications, map_reference_screens)
from multi_agent.runtime.design_prep import _SCREEN_TOOL, _merge_enrichment  # noqa: E402


def _mk_ref(tmp_path, name):
    p = tmp_path / f"{name}.png"
    p.write_bytes(b"\x89PNG\r\n\x1a\n")
    return str(p)


def _mk_ds(tmp_path, screens):
    d = tmp_path / "design"
    d.mkdir(exist_ok=True)
    (d / "design_system.json").write_text(json.dumps({"screens": screens}), encoding="utf-8")


# ── load_screen_classifications ─────────────────────────────────────────────

def test_load_classifications_reads_screen_keys(tmp_path):
    _mk_ds(tmp_path, [
        {"name": "search_flyout", "kind": "overlay", "requires_auth": True, "route": "/"},
        {"name": "login_light", "kind": "page", "requires_auth": False, "route": "/login"},
        {"name": "unclassified", "layout": "x"},   # no classification keys -> omitted
    ])
    cls = load_screen_classifications(tmp_path)
    assert cls["search_flyout"] == {"kind": "overlay", "requires_auth": True, "route": "/"}
    assert cls["login_light"]["route"] == "/login"
    assert "unclassified" not in cls


def test_load_classifications_tolerates_missing_and_garbage(tmp_path):
    assert load_screen_classifications(tmp_path) == {}          # no file
    d = tmp_path / "design"; d.mkdir()
    (d / "design_system.json").write_text("{not json", encoding="utf-8")
    assert load_screen_classifications(tmp_path) == {}          # unparseable


# ── map_reference_screens with authoritative classifications ────────────────

def test_authoritative_overlay_beats_innocent_filename(tmp_path):
    # filename has NO overlay token -> #128 regex would say blocking; the analyst
    # SAW a modal in the pixels -> advisory must win.
    ref = _mk_ref(tmp_path, "search_results")
    out = map_reference_screens([ref], {"/search"},
                                classifications={"search_results": {"kind": "overlay"}})
    assert out[0]["advisory"] is True


def test_authoritative_page_beats_overlay_looking_filename(tmp_path):
    # filename says "flyout" (#128 regex -> advisory) but the analyst saw a real
    # standalone PAGE -> it must stay blocking.
    ref = _mk_ref(tmp_path, "notifications_flyout")
    out = map_reference_screens([ref], {"/notifications"},
                                classifications={"notifications_flyout": {"kind": "page"}})
    assert out[0]["advisory"] is False


def test_authoritative_route_used_when_app_serves_it(tmp_path):
    # filename maps nowhere, analyst supplied the route and the app serves it.
    ref = _mk_ref(tmp_path, "moments_gallery")
    out = map_reference_screens([ref], {"/explore", "/feed"},
                                classifications={"moments_gallery": {"route": "/explore"}})
    assert out[0]["route"] == "/explore"


def test_authoritative_route_not_served_falls_back(tmp_path):
    # the analyst's semantic suggestion isn't a registered route -> never navigate
    # to a 404; the filename heuristics still resolve normally.
    ref = _mk_ref(tmp_path, "explore")
    out = map_reference_screens([ref], {"/explore"},
                                classifications={"explore": {"route": "/discover-x"}})
    assert out[0]["route"] == "/explore"      # generic filename match won


def test_authoritative_requires_auth_beats_keyword_catalog(tmp_path):
    # "feed" keyword says auth=True; the analyst says this particular screen is
    # public -> authoritative wins.
    ref = _mk_ref(tmp_path, "feed")
    out = map_reference_screens([ref], {"/feed"},
                                classifications={"feed": {"requires_auth": False}})
    assert out[0]["auth"] is False


def test_no_classifications_keeps_existing_behavior(tmp_path):
    ref = _mk_ref(tmp_path, "search_flyout")
    out = map_reference_screens([ref], {"/explore"})
    assert out[0]["advisory"] is True          # #128 regex fallback unchanged


# ── design-prep side: schema + merge carry the new keys ─────────────────────

def test_screen_tool_schema_has_classification_fields():
    props = _SCREEN_TOOL[0]["function"]["parameters"]["properties"]
    assert props["kind"]["enum"] == ["page", "overlay"]
    assert props["requires_auth"]["type"] == "boolean"
    assert props["route"]["type"] == "string"


def test_merge_enrichment_carries_classification_to_written_screen():
    skeleton = {"design_system": {"palette": {"bg": "#000"}},
                "assets": [],
                "screens": [{"name": "reels", "reference": "reels.png",
                             "layout": "", "components": []}]}
    enriched = {"design_system": {}, "assets": [],
                "screens": [{"name": "reels", "layout": "full-bleed video",
                             "kind": "page", "requires_auth": True, "route": "/reels",
                             "components": []}]}
    ds = _merge_enrichment(skeleton, enriched)
    s = ds["screens"][0]
    assert s["kind"] == "page" and s["requires_auth"] is True and s["route"] == "/reels"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
