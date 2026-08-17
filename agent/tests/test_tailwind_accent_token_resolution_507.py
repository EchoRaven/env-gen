"""#507 (netflix r82, 2026-08-05) — the Tailwind `accent` TOKEN shipped BLUE, so every
bg-accent/text-accent surface (login/signup submit buttons, nav active, badges) rendered
blue instead of brand-red. This is the TWIN of #506 (which fixed the landing's INLINE
_resolve_accent path); #507 fixes the Tailwind-CLASS path.

GROUND TRUTH: r82's generated tailwind.theme.js had `'accent': '#3470e8'` (blue) —
render_measured_tailwind_theme emits every palette key verbatim, and the analyst mis-records
`accent` as the link-blue while the vivid brand color is under brand_red (#e50914). So
`bg-accent` (auth submit via _auth_page_classes) rendered blue (login 0.40).

FIX: after emitting the palette tokens, when an `accent` token exists, resolve it to the
vivid brand accent via _resolve_accent (the SAME rule as the inline path) so both paths
agree. Byte-identical when no `accent` key exists. Generalizes to every app.

These tests lock: (1) blue `accent` token → resolved to red, (2) other tokens untouched,
(3) coherent/absent-accent palettes unchanged, (4) accents-map hue tokens still emitted."""
import re

from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    render_measured_tailwind_theme)


def _accent_token(theme_js: str):
    m = re.search(r"'accent':\s*'([^']+)'", theme_js)
    return m.group(1).lower() if m else None


# ---- the r82 case: blue accent token resolved to the vivid brand red ----
def test_blue_accent_token_resolved_to_brand_red():
    ds = {"palette": {
        "bg": "#141414", "accent_link": "#3470e8", "brand_red": "#e50914",
        "accents": {"blue": "#3470e8", "red": "#e02c1b"}, "accent": "#3470e8",
    }}
    js = render_measured_tailwind_theme(ds)
    assert _accent_token(js) == "#e50914"          # was #3470e8 pre-fix


def test_other_tokens_untouched():
    ds = {"palette": {"bg": "#141414", "accent": "#3470e8", "brand_red": "#e50914",
                      "surface": "#181818"}}
    js = render_measured_tailwind_theme(ds)
    assert "'bg': '#141414'" in js
    assert "'surface': '#181818'" in js
    assert "'brand-red': '#e50914'" in js
    # the accents-map / hue tokens path unaffected
    assert _accent_token(js) == "#e50914"


# ---- coherent single-accent app: accent token unchanged ----
def test_coherent_red_accent_token_unchanged():
    ds = {"palette": {"bg": "#141414", "accent": "#e50914", "brand": "#e50914"}}
    js = render_measured_tailwind_theme(ds)
    assert _accent_token(js) == "#e50914"


# ---- palette with NO accent key: byte-identical (no accent token added) ----
def test_no_accent_key_no_accent_token_added():
    ds = {"palette": {"bg": "#141414", "surface": "#181818"}}
    js = render_measured_tailwind_theme(ds)
    assert _accent_token(js) is None               # no accent token fabricated


# ---- accents-map hue tokens still emitted alongside resolved accent ----
def test_accents_map_hue_tokens_still_present():
    ds = {"palette": {"accent": "#3470e8", "brand_red": "#e50914",
                      "accents": {"blue": "#3470e8", "red": "#e02c1b", "gold": "#eace61"}}}
    js = render_measured_tailwind_theme(ds)
    assert "'accent-blue': '#3470e8'" in js
    assert "'accent-red': '#e02c1b'" in js
    assert "'accent-gold': '#eace61'" in js
    assert _accent_token(js) == "#e50914"           # scalar accent resolved to brand red


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
