"""#1203kx: an avatar is not a poster, and the pool that feeds poster tiles cycles it.

`_ref_image_pool` (#415) collects the app's staged PHOTOGRAPHIC assets "for the page-
projector's HERO bg + RAIL/GRID posters". Its consumers cycle the pool:

    const _REFIMGS = [...]; const _refImg = (i) => _REFIMGS[i % _REFIMGS.length]

so #543's grid padding and the collage background draw from it by index. A pool with one
entry therefore paints that one image into every tile.

The function has an `_EXCLUDE` list for staged images that are not content photography —
icon, logo, placeholder, sprite, favicon, wordmark. A profile avatar belongs there: it is
not a backdrop, a poster or a still.

MEASURED, and only reachable because #1203kv restored `type` (before that this function
returned [] in all 39 modern runs): 36 of the 39 restored pools were exactly
`['/assets/real_avatars/therock.jpg']` — one person's face as every padded poster — arriving
through the "else fall back to ALL qualifying photos" branch, because no corpus run stages
anything carrying a poster/backdrop/still token. With `avatar` excluded all 39 are [] again,
which is what the projector did before the restore.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.frontend_scaffold import _ref_image_pool  # noqa: E402


def _asset(aid, rel, typ="jpg"):
    return {"id": aid, "file": rel, "type": typ, "staged_path": "public/assets/" + rel}


def test_an_avatar_is_not_part_of_the_poster_pool():
    # the corpus shape: one avatar photo and nothing else photographic
    only_avatar = {"assets": [_asset("therock", "real_avatars/therock.jpg")]}
    assert _ref_image_pool(only_avatar) == [], _ref_image_pool(only_avatar)

    # NON-VACUITY: the pool is alive — a real still comes through from the same document
    with_still = {"assets": [_asset("therock", "real_avatars/therock.jpg"),
                             _asset("hero-1", "backdrops/hero_1.jpg")]}
    assert _ref_image_pool(with_still) == ["/assets/backdrops/hero_1.jpg"], (
        _ref_image_pool(with_still))


def test_the_fallback_branch_is_what_made_it_reachable():
    """#415 prefers poster/backdrop/still tokens and FALLS BACK to every qualifying photo.
    The avatar arrived through the fallback, so the exclusion has to apply there — a test
    that only ever exercises the preferred branch would pass with the exclusion removed."""
    # no token in _PREFER anywhere: the fallback is the only branch that can return anything
    fallback_only = {"assets": [_asset("therock", "real_avatars/therock.jpg"),
                                _asset("grid-1", "stills_untagged/img_1.jpg")]}
    got = _ref_image_pool(fallback_only)
    assert got == ["/assets/stills_untagged/img_1.jpg"], got


def test_the_exclusion_is_not_wider_than_the_word():
    """#647: no collateral. A file whose name merely CONTAINS the letters in another word is
    still excluded (the list is substring-based by design, like its five siblings), but an
    unrelated photo is not."""
    d = {"assets": [_asset("poster-1", "posters/avatar_of_the_night.jpg"),
                    _asset("poster-2", "posters/the_rock_movie.jpg")]}
    got = _ref_image_pool(d)
    assert got == ["/assets/posters/the_rock_movie.jpg"], got


def test_every_modern_corpus_pool_is_empty_again():
    """The measurement in the docstring. Skipped when the corpus is not on this disk."""
    import json
    import re
    import pytest
    pools = []
    for p in sorted((ROOT.parent / "generated").glob("*/design/design_system.json")):
        m = re.search(r"r(\d+)$", p.parent.parent.name)
        if not m or int(m.group(1)) < 150:
            continue
        try:
            d = json.loads(p.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        # the restored state #1203kv produces, without re-running the whole pass
        for a in (d.get("assets") or []):
            if isinstance(a, dict) and not a.get("type"):
                sfx = Path(str(a.get("file") or "")).suffix.lower()
                a["type"] = {".svg": "svg", ".png": "png", ".jpg": "jpg",
                             ".jpeg": "jpg", ".webp": "webp"}.get(sfx) or ""
        pools.append((p.parent.parent.name, _ref_image_pool(d)))
    if len(pools) < 10:
        pytest.skip("too few corpus design docs on this disk (%d)" % len(pools))
    bad = [(n, u) for n, u in pools if u]
    assert bad == [], (
        "a corpus pool that is not empty is either a real poster set (good, update this "
        "test) or another non-photograph class to exclude", bad[:4])
