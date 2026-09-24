"""FIX #178 — the pipeline sources icons + the OSM map for real, but ENTITY PHOTOS (place /
product / listing images) had NO real source, so stage_missing_seed_photos (#168) filled every
seed ``photo_url`` with a gray PLACEHOLDER. gmrun12 shipped 82 identical gray cards ("照片全是
占位图"). This adds a real-photo channel: derive a search query from each image ref (its
category/type, encoded in the filename), fetch a REAL photo (Unsplash when
ENVGEN_UNSPLASH_KEY is set, cached per query), and only fall back to the neutral placeholder
when there's no key or the fetch fails. Pure helpers unit-tested; the fetch is mocked. LOCAL-ONLY.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime import frontend_scaffold as fs  # noqa: E402
from multi_agent.runtime.frontend_scaffold import (  # noqa: E402
    _photo_query_from_ref, _photo_index_from_ref, stage_missing_seed_photos,
)


def test_query_from_category_filename():
    assert _photo_query_from_ref("photos/restaurant_2.jpg") == "restaurant"
    assert _photo_query_from_ref("photos/coffee_shop_1.jpg") == "coffee shop"
    assert _photo_query_from_ref("photos/museum.jpg") == "museum"       # no numeric suffix
    assert _photo_query_from_ref("photos/fast_food_10.jpg") == "fast food"


def test_index_from_filename():
    assert _photo_index_from_ref("photos/restaurant_4.jpg") == 4
    assert _photo_index_from_ref("photos/museum.jpg") == 1              # default when none


def _seed(tmp_path, refs):
    be = tmp_path / "app" / "backend"
    be.mkdir(parents=True)
    (tmp_path / "app" / "frontend" / "public" / "assets").mkdir(parents=True)
    rows = [{"id": i, "photo_url": f"/assets/{r}"} for i, r in enumerate(refs, 1)]
    (be / "seed_data.json").write_text(__import__("json").dumps(rows))
    return tmp_path


def test_real_photo_used_when_fetch_succeeds(tmp_path, monkeypatch):
    calls = []
    def fake_fetch(query, index, dest, key):
        calls.append((query, index))
        Path(dest).write_bytes(b"\xff\xd8\xff" + b"REALPHOTO" * 500)  # a "real" jpg
        return True
    monkeypatch.setenv("ENVGEN_UNSPLASH_KEY", "testkey")
    monkeypatch.setattr(fs, "_fetch_real_seed_photo", fake_fetch)
    root = _seed(tmp_path, ["photos/restaurant_1.jpg", "photos/cafe_2.jpg"])
    staged = stage_missing_seed_photos(root)
    assert set(staged) == {"photos/restaurant_1.jpg", "photos/cafe_2.jpg"}
    # the files hold the REAL bytes, not the ~2KB gray placeholder
    body = (root / "app/frontend/public/assets/photos/restaurant_1.jpg").read_bytes()
    assert b"REALPHOTO" in body
    assert ("restaurant", 1) in calls and ("cafe", 2) in calls


def test_placeholder_fallback_when_no_key(tmp_path, monkeypatch):
    monkeypatch.delenv("ENVGEN_UNSPLASH_KEY", raising=False)
    monkeypatch.delenv("UNSPLASH_ACCESS_KEY", raising=False)
    root = _seed(tmp_path, ["photos/restaurant_1.jpg"])
    staged = stage_missing_seed_photos(root)
    # still staged (placeholder), so no broken <img> — real-photo is an ENHANCEMENT, not a gate
    assert staged == ["photos/restaurant_1.jpg"]
    body = (root / "app/frontend/public/assets/photos/restaurant_1.jpg").read_bytes()
    assert b"REALPHOTO" not in body and len(body) > 0  # a real (placeholder) image, not empty


def test_placeholder_fallback_when_fetch_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("ENVGEN_UNSPLASH_KEY", "testkey")
    monkeypatch.setattr(fs, "_fetch_real_seed_photo", lambda *a, **k: False)  # fetch fails
    root = _seed(tmp_path, ["photos/restaurant_1.jpg"])
    staged = stage_missing_seed_photos(root)
    assert staged == ["photos/restaurant_1.jpg"]  # placeholder fallback → still resolves
