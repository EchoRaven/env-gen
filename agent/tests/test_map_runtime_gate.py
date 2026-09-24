"""FIX #172 — a declared MAP SURFACE that renders NO real map at RUNTIME (a fake <div>
background instead of a Leaflet/Mapbox map) must FAIL the browser test-user gate.

gmrun9 M3 regression (runtime-verified): the M2/M3 hotel/vacation-rentals redesign replaced
HomeMapPage's <MapCanvas> (real react-leaflet) with a fake `bg-[#a0d7ea]` div + a single
static pin; the real MapCanvas.jsx went ORPHANED (imported by nobody). The #166 gate does
`_frontend_uses_map_lib(src)` over the WHOLE source tree → it still finds react-leaflet in
the dead MapCanvas.jsx → gate PASSES → but at RUNTIME the map surface has zero
`.leaflet-container`. Source-presence ≠ runtime render (the IRON LAW). Only a runtime,
surface-specific assertion catches a fake-div map. This flags it as a SOFT-unusable signal
(bounded-defer + escape, like no_real_data) so the map is rebuilt but a non-map env never
deadlocks. LOCAL-ONLY.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.test_user_runner import (  # noqa: E402
    _finalize_walkthrough, browser_report_unusable,
)
from multi_agent.runtime.frontend_audit import _is_map_page  # noqa: E402


def _report(pages):
    return {"ran": True, "steps": [{"ok": True, "step": "login"}], "pages": pages,
            "real_data": {"checked": True, "rendered": True, "matched": ["Pinecrest"]}}


def test_map_surface_without_map_dom_is_fake_map():
    r = _finalize_walkthrough(_report([
        {"name": "home_map", "route": "/", "blank": False,
         "is_map_surface": True, "map_rendered": False},
    ]))
    assert r["fake_map_pages"] == ["home_map"]
    assert browser_report_unusable(r) is True


def test_map_surface_with_real_map_is_usable():
    r = _finalize_walkthrough(_report([
        {"name": "home_map", "route": "/", "blank": False,
         "is_map_surface": True, "map_rendered": True},
    ]))
    assert r["fake_map_pages"] == []
    assert browser_report_unusable(r) is False


def test_non_map_page_never_flagged_fake_map():
    r = _finalize_walkthrough(_report([
        {"name": "saved_page", "route": "/saved", "blank": False,
         "is_map_surface": False, "map_rendered": False},
    ]))
    assert r["fake_map_pages"] == []
    assert browser_report_unusable(r) is False


def test_blank_map_page_caught_by_blank_not_double_flagged():
    # a blank map page is already caught by blank_pages; fake_map targets the specific
    # RENDERED-content-but-no-map case (the fake-div map), so it must not double-flag.
    r = _finalize_walkthrough(_report([
        {"name": "home_map", "route": "/", "blank": True,
         "is_map_surface": True, "map_rendered": False},
    ]))
    assert r["fake_map_pages"] == []
    assert "home_map" in r["blank_pages"]


def test_fake_map_is_soft_signal_not_hard_gate():
    # SOFT (auth works, only the map surface is fake) → honor the bounded escape, never a
    # permanent hard-hold like a broken login. browser_gate_decision must pass squad thru.
    from multi_agent.runtime.test_user_runner import browser_gate_decision
    r = _finalize_walkthrough(_report([
        {"name": "home_map", "route": "/", "blank": False,
         "is_map_surface": True, "map_rendered": False},
    ]))
    assert browser_gate_decision(r, "release") == "release"


def test_is_map_page_identifies_home_map():
    # the identifier the browser loop uses to mark is_map_surface
    assert _is_map_page("home_map", {"name": "home_map", "route": "/"}) is True
    assert _is_map_page("saved_page", {"name": "saved_page", "route": "/saved"}) is False


def test_feedback_tells_lane_to_build_a_real_map():
    from multi_agent.runtime.test_user_runner import format_feedback
    r = _finalize_walkthrough(_report([
        {"name": "home_map", "route": "/", "blank": False,
         "is_map_surface": True, "map_rendered": False},
    ]))
    fb = format_feedback(r)
    assert "FAKE MAP" in fb
    # actionable: name the real lib + the anti-pattern it must stop using
    assert "MapContainer" in fb and "leaflet" in fb.lower()
    assert "div" in fb.lower()  # calls out the fake background <div>
    # per-page flag also present
    assert "/" in fb and "FAKE MAP" in fb


def test_feedback_no_fake_map_section_when_map_real():
    from multi_agent.runtime.test_user_runner import format_feedback
    r = _finalize_walkthrough(_report([
        {"name": "home_map", "route": "/", "blank": False,
         "is_map_surface": True, "map_rendered": True},
    ]))
    assert "FAKE MAP" not in format_feedback(r)
