"""#476 (BUG C + real-imagery) — the hero rendered a title-art crop over a FIXED staged
photo ('boxed card over unrelated background', persistent r46-r49), and rails/cards fell
back to staged photos, because the frontend never used each title's OWN real backdrop/
poster. ROOT: the DB DOES carry real per-title refs (VERIFIED live: titles.poster=
'assets/posters/movie_*.jpg', backdrop='assets/backdrops/movie_*.jpg' — the seed loader's
dataset-wins merge populates them, and the assets ARE served at public/assets/…), but
_imgOf only checked '*_url'/'image'/'thumbnail' keys — NOT the raw 'poster'/'backdrop'
field names media titles carry — so _imgOf(title)=null and the projector used the staged
_refImg pool instead of the real per-title imagery.

FIX: (1) _imgOf recognizes raw 'poster'/'still'/'cover'/'banner'/'backdrop' (poster-FIRST
so rail/grid CARDS stay portrait); (2) new _backdropOf (backdrop-FIRST, landscape) for the
HERO; (3) hero _bg prefers (cur && _backdropOf(cur)) — the featured title's OWN real
backdrop — over the fixed staged photo. Strictly-improving (real served per-title imagery
> a fixed unrelated photo) + honest (real seeded refs, served assets) + null-safe fallback
to the staged pool. Generalizable to any media app whose titles carry poster/backdrop.
VERIFY-BEFORE-SHIP discipline: an earlier read of the LANE seed_data.json (picsum) nearly
mis-scoped this as a seed-loader regression; querying the LIVE DB proved real refs → this
fix (use them) is correct, not a regression."""
import re
from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    _REF_HELPERS_JS, _render_reference_page)


def _keys_of(fn_name: str):
    """Extract the ordered key array from `const <fn> = (r) => { for (const k of [...]`."""
    m = re.search(fn_name + r"\s*=\s*\(r\)\s*=>\s*\{\s*for\s*\(const k of \[([^\]]*)\]",
                  _REF_HELPERS_JS)
    assert m, f"{fn_name} not found in _REF_HELPERS_JS"
    return [x.strip().strip("'\"") for x in m.group(1).split(",") if x.strip()]


def test_imgof_recognizes_raw_poster_backdrop():
    keys = _keys_of("_imgOf")
    for k in ("poster", "backdrop", "still", "cover"):
        assert k in keys, f"#476: _imgOf must recognize raw '{k}' field (media titles carry it)"
    # CARDS keep portrait posters → poster must come before backdrop in _imgOf
    assert keys.index("poster") < keys.index("backdrop"), \
        "#476: _imgOf poster-first so rail/grid cards stay portrait (no #429 regression)"


def test_backdropof_landscape_first():
    assert "_backdropOf" in _REF_HELPERS_JS, "#476: _backdropOf helper added"
    keys = _keys_of("_backdropOf")
    assert keys and keys[0] == "backdrop", "#476: _backdropOf is backdrop-FIRST (landscape hero)"
    # must fall back to _imgOf so a title without a landscape field still resolves
    assert "return _imgOf(r)" in _REF_HELPERS_JS.split("_backdropOf", 1)[1][:200], \
        "#476: _backdropOf falls back to _imgOf (null-safe)"


def test_hero_bg_prefers_featured_title_backdrop():
    # the projected reference page's hero must prefer the featured title's own backdrop
    src = _render_reference_page.__code__.co_consts
    # cheap, robust: the module source of the hero _bg carries the preference string
    import inspect
    body = inspect.getsource(_render_reference_page)
    assert "(cur && _backdropOf(cur))" in body, \
        "#476: hero _bg prefers the featured title's own real backdrop over the staged photo"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
