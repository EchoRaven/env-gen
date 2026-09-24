"""FIX #167 — the frontend prompt must state, PROMINENTLY, the gate-enforced hard rules the
lane kept violating (gmrun7): no blank/mock/placeholder pages, no fake maps, consistent
real iconography, consistent typography, images must resolve (placeholder fallback, not a
404). The existing rules were buried in a 900-line wall of text and ignored; this asserts a
short high-contrast block renders near the TOP of the mandate. LOCAL-ONLY.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

_J2 = (LLM / "multi_agent" / "prompts" / "v3" / "frontend_agent.j2").read_text(encoding="utf-8")


def test_hard_rules_block_present():
    assert "NON-NEGOTIABLE" in _J2, "a prominent hard-rules block must exist"


def test_forbids_blank_mock_placeholder_pages():
    low = _J2.lower()
    assert "no blank" in low or "blank / mock" in low or "blank/mock" in low
    assert "placeholder" in low and "mock" in low
    assert "coming soon" in low or "stub page" in low or "'coming soon'" in low


def test_forbids_fake_map():
    low = _J2.lower()
    assert "fake map" in low or ("real" in low and "map" in low and "leaflet" in low)
    assert "map-surface gate" in low or "map surface gate" in low or "rejected (map" in low


def test_mandates_consistent_icons_and_typography():
    low = _J2.lower()
    assert "consistent" in low and ("icon" in low)
    assert "typography" in low and "type_scale" in low
    assert "do not mix" in low or "one icon set" in low or "one style" in low


def test_mandates_image_fallback_not_404():
    low = _J2.lower()
    assert "onerror" in low
    assert "placeholder" in low and ("ph-img" in low or "/assets/placeholders" in low)


def test_forbids_invented_field_hardcoded_fallback():
    # the ResultCard.jsx anti-pattern: place.capacity || 'Sleeps 4' → fake data on every row
    low = _J2.lower()
    assert "invent" in low and "hardcoded fallback" in low
    assert "capacity" in low and "sleeps 4" in low.replace("'", "")
    assert "only the fields the backend actually returns" in low or "render only the fields" in low


def test_rules_block_near_top_of_mandate():
    # it must appear BEFORE the long Phase-A dimensions paragraph, so the lane reads it first
    idx_rules = _J2.find("NON-NEGOTIABLE")
    idx_phaseA = _J2.find("Phase A — Author design")
    assert idx_rules != -1 and idx_phaseA != -1 and idx_rules < idx_phaseA


def test_prompt_still_renders_via_jinja():
    # the added block must not break Jinja parsing / the existing template
    try:
        from jinja2 import Environment
        Environment().parse(_J2)
    except Exception as e:  # pragma: no cover
        raise AssertionError(f"frontend_agent.j2 no longer parses: {e}")
