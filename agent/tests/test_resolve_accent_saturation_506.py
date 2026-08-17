"""#506 (netflix r82, 2026-08-05) — _resolve_accent shipped a BLUE accent on every CTA
because the analyst mis-recorded the link-blue under `accent`.

GROUND TRUTH: r82's rendered landing (screenshots/landing.png) showed BLUE Sign-In +
Get-Started buttons vs the reference's Netflix RED. design_system.json palette had
`accent: #3470e8` (IDENTICAL to `accent_link`) while the true brand color was
`brand_red: #e50914` (note: "#e50914 is the canonical Netflix Red"). The projector's
_landing_page_src / auth pages call _resolve_accent(pal), whose old FIRST-MATCH loop
returned `accent` (blue) before ever checking `brand_red` — so every projected CTA shipped
blue, the dominant cross-screen fidelity delta (landing 0.32, login 0.40).

FIX: among the CORE brand-identity scalar keys (accent/primary/brand/brand_red), return the
MOST SATURATED — honoring the function's OWN documented principle ("the brand color is
vivid, the neutrals are not"), which was previously applied ONLY to the `accents` map. A
mis-recorded low-saturation link-blue can no longer beat the vivid brand red. Coherent
single-accent apps are unaffected. Generalizes to every app; no product/hue literals.

These tests lock: (1) the r82 repro (blue accent + red brand → red wins), (2) coherent
palettes unchanged, (3) accent-only unchanged, (4) secondary/accents-map/gray fallbacks."""
from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import _resolve_accent


# ---- the r82 case: blue `accent` mis-recorded, true brand red under brand_red ----
def test_r82_blue_accent_loses_to_vivid_brand_red():
    pal = {"accent": "#3470e8", "accent_link": "#3470e8", "brand_red": "#e50914"}
    assert _resolve_accent(pal).lower() == "#e50914"


def test_r82_full_palette_shape_resolves_red():
    # the real r82 palette shape (subset): blue accent + many red brand keys.
    pal = {
        "text": "#ffffff", "accent_link": "#3470e8", "brand_red": "#e50914",
        "live_badge_red": "#e50914", "top10_red": "#e50914",
        "accents": {"blue": "#3470e8", "red": "#e02c1b"}, "accent": "#3470e8",
    }
    assert _resolve_accent(pal).lower() == "#e50914"


# ---- coherent single-accent apps: UNCHANGED (all brand keys same hue) ----
def test_coherent_red_accent_unchanged():
    assert _resolve_accent({"accent": "#e50914", "brand": "#e50914"}).lower() == "#e50914"


def test_accent_only_no_brand_unchanged():
    # no competing brand key → the lone accent is returned (even if it is a blue).
    assert _resolve_accent({"accent": "#3470e8"}).lower() == "#3470e8"


def test_muted_coherent_accent_not_overridden_by_nothing():
    # a genuinely muted brand accent with no more-saturated core key stays put.
    assert _resolve_accent({"accent": "#a3b18a", "brand": "#a3b18a"}).lower() == "#a3b18a"


# ---- most-saturated among core keys ----
def test_brand_beats_less_saturated_primary():
    pal = {"primary": "#8899aa", "brand": "#ff1122"}  # brand far more saturated
    assert _resolve_accent(pal).lower() == "#ff1122"


# ---- fallback ladder unchanged when no core key present ----
def test_secondary_key_fallback_when_no_core():
    assert _resolve_accent({"cta": "#ff6600"}).lower() == "#ff6600"


def test_accents_map_fallback_when_no_scalar():
    pal = {"accents": {"blue": "#3470e8", "red": "#e02c1b", "gray": "#888888"}}
    # most saturated of the map (red beats blue beats gray)
    assert _resolve_accent(pal).lower() == "#e02c1b"


def test_gray_fallback_when_empty():
    assert _resolve_accent({}) == "#6b7280"


def test_non_mapping_returns_gray():
    assert _resolve_accent(None) == "#6b7280"
    assert _resolve_accent("nope") == "#6b7280"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
