"""#296 — _measured_floor_colors extracts a measured color set for the no-reference floor."""
import sys
from pathlib import Path
THIS = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS.parent / "env_generator" / "llm_generator"))
from multi_agent.runtime.frontend_scaffold import _measured_floor_colors  # noqa: E402


def _design(palette, theme="dark"):
    return {"design_system": {"palette": palette, "theme": {"default": theme}}}


def test_full_palette_maps_all_roles():
    c = _measured_floor_colors(_design({
        "bg": "#000000", "surface": "#121212", "text": "#ffffff",
        "text_2": "rgba(255,255,255,0.75)", "accent_red": "#EA445A",
        "border": "#2a2a2a"}))
    assert c["bg"] == "#000000"
    assert c["surface"] == "#121212"
    assert c["text"] == "#ffffff"
    assert c["muted"] == "rgba(255,255,255,0.75)"
    assert c["accent"] == "#EA445A"      # accent_red picked
    assert c["border"] == "#2a2a2a"


def test_generic_accent_key_picked():
    c = _measured_floor_colors(_design({"bg": "#0b0b0b", "accent": "#1DB954"}))
    assert c["accent"] == "#1DB954"


def test_missing_bg_returns_none():
    assert _measured_floor_colors(_design({"accent": "#EA445A"})) is None
    assert _measured_floor_colors(_design({})) is None
    assert _measured_floor_colors({}) is None
    assert _measured_floor_colors(None) is None


def test_missing_subroles_derive_from_bg_and_neutrals():
    # only bg present -> other roles get measured-neutral defaults (never crash, never product color)
    c = _measured_floor_colors(_design({"bg": "#000000"}, theme="dark"))
    assert c["bg"] == "#000000"
    assert c["surface"] == "#000000"           # falls back to bg
    assert c["text"] == "#f5f5f5"              # dark-theme default text
    assert c["accent"] == "#2563eb"            # neutral accent default
    assert isinstance(c["muted"], str) and c["muted"]
    assert isinstance(c["border"], str) and c["border"]


def test_light_theme_text_default():
    c = _measured_floor_colors(_design({"bg": "#ffffff"}, theme="light"))
    assert c["text"] == "#18181b"


def test_theme_derived_from_bg_luminance_when_unspecified():
    c = _measured_floor_colors({"design_system": {"palette": {"bg": "#000000"}}})
    assert c["text"] == "#f5f5f5"              # dark bg -> dark theme -> light text
