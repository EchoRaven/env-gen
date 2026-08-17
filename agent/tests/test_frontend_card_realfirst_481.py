"""#481 — the projector's RAIL/GRID cards + title-detail modal bg painted the staged
reference pool (#415 `_refImg`) BEFORE each row's own real image: `_refImg(i) || _imgOf(row)`.
Because `_ref_image_pool` is non-empty for a media app, `_refImg(i)` ALWAYS won, so every
card at a given position showed the SAME positional reference photo regardless of the title
the API returned. Consequences, seen live on netflix-web-r53 (and every prior run — this is
a STATIC projector emit, not a run-specific artifact):
  • repeat delivery-gate P0 "MyListPage renders HARDCODED data" — the frontend lane was
    nudged twice and could not fix it (the precedence is baked into the projector, not the
    lane's editable page body) → delivery churned, never released;
  • fidelity cap — cards never showed the real per-title posters the DB carries.
ROOT: #415 chose reference-FIRST when seed rows had generic placeholders; #476 established
the seed loader now populates REAL per-title refs (assets/posters|backdrops/movie_*.jpg,
served) and made the HERO real-first — but the rail/grid CARDS and the detail-modal bg were
left reference-first.
FIX: flip every PER-TITLE image site to real-first — `_imgOf(row) || _refImg(i)` (cards),
`(cur && _imgOf(cur)) || _refImg(0)` (detail modal bg) — keeping the staged pool as the
null-safe FALLBACK for a title with no image. Consistent with #476's hero; generalizable to
any media app; strictly-improving (real per-title imagery > a fixed positional photo)."""
import inspect
from env_generator.llm_generator.multi_agent.runtime import frontend_scaffold as fs


def _body():
    return inspect.getsource(fs._render_reference_page)


def test_no_reference_first_per_title_card():
    body = _body()
    # the exact reference-FIRST card precedence must be gone (all rail/grid emitters)
    assert "_refImg(i) || _imgOf(row)" not in body, \
        "#481: rail/grid cards must NOT paint the positional reference pool before the row's own image"
    # and the reference-first detail-modal bg must be gone
    assert "_refImg(0) || (cur && _imgOf(cur))" not in body, \
        "#481: the title-detail modal bg must NOT prefer _REFIMGS[0] over the opened title (cur)"


def test_cards_are_real_first():
    body = _body()
    # rail + all three grid emitters resolve to the row's own image first
    assert "_imgOf(row) || _refImg" in body, \
        "#481: cards prefer the row's OWN image, falling back to the staged pool"
    # detail-modal bg prefers the opened title's own image
    assert "(cur && _imgOf(cur)) || _refImg(0)" in body, \
        "#481: the detail overlay paints the OPENED title's image first, _refImg(0) as fallback"


def test_reference_pool_retained_as_fallback():
    # the staged pool must remain wired as a fallback (null-safe) — not deleted
    body = _body()
    assert "_refImg(" in body and "_REFIMGS" in fs._REF_HELPERS_JS or "_refImg" in body, \
        "#481: the reference pool stays as the fallback for titles with no image"
    # a card whose row lacks any image still renders via _refImg → both sides present
    assert body.count("_imgOf(row) || _refImg") >= 3, \
        "#481: all rail+grid card emitters flipped (>=3 real-first card sites)"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
