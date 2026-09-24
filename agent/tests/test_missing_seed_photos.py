"""FIX #168 — guarantee every LOCAL image asset the seed references exists (gmrun7 404 photos).

gmrun7's place cards showed a broken-image glyph: the seed's ``photo_url`` was
``/assets/photos/restaurant_2.jpg`` — a LOCAL path — but that file was never created (the
design-input had 63 icon SVGs and zero place photos), so every <img> 404'd. The framework's
external-image localizer only rewrites EXTERNAL stock URLs (unsplash/picsum/...), not a
missing LOCAL path. Stage a neutral placeholder IMAGE (correct format) at each missing
seed-referenced local image path so images always resolve. LOCAL-ONLY (agent/tests/).
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.frontend_scaffold import stage_missing_seed_photos  # noqa: E402


def _seed(tmp_path, dataset=None, data=None):
    be = tmp_path / "app" / "backend"
    be.mkdir(parents=True, exist_ok=True)
    (tmp_path / "app" / "frontend" / "public" / "assets").mkdir(parents=True, exist_ok=True)
    if dataset is not None:
        (be / "seed_dataset.json").write_text(json.dumps(dataset))
    if data is not None:
        (be / "seed_data.json").write_text(json.dumps(data))
    return tmp_path


def _pub(tmp_path):
    return tmp_path / "app" / "frontend" / "public" / "assets"


def test_missing_photo_is_generated(tmp_path):
    _seed(tmp_path, dataset={"places": [
        {"id": 1, "name": "Pinecrest Diner", "photo_url": "/assets/photos/restaurant_2.jpg"},
        {"id": 2, "name": "Bean Bag", "photo_url": "/assets/photos/cafe_1.jpg"}]})
    staged = stage_missing_seed_photos(tmp_path)
    assert set(staged) == {"photos/restaurant_2.jpg", "photos/cafe_1.jpg"}
    p = _pub(tmp_path) / "photos" / "restaurant_2.jpg"
    assert p.exists() and p.stat().st_size > 0
    # it must be a REAL decodable image (correct format), not junk
    from PIL import Image
    with Image.open(p) as im:
        assert im.format == "JPEG" and im.size[0] > 0


def test_png_path_saved_as_png(tmp_path):
    _seed(tmp_path, dataset={"x": [{"img": "/assets/photos/a.png"}]})
    stage_missing_seed_photos(tmp_path)
    from PIL import Image
    with Image.open(_pub(tmp_path) / "photos" / "a.png") as im:
        assert im.format == "PNG"


def test_existing_file_not_overwritten(tmp_path):
    _seed(tmp_path, dataset={"p": [{"photo_url": "/assets/photos/keep.jpg"}]})
    dest = _pub(tmp_path) / "photos" / "keep.jpg"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"ORIGINAL-REAL-PHOTO-BYTES")
    staged = stage_missing_seed_photos(tmp_path)
    assert "photos/keep.jpg" not in staged
    assert dest.read_bytes() == b"ORIGINAL-REAL-PHOTO-BYTES"  # untouched


def test_icons_and_placeholders_skipped(tmp_path):
    _seed(tmp_path, dataset={"p": [
        {"icon": "/assets/icons/map_24.svg"},
        {"ph": "/assets/placeholders/ph-img-0.svg"},
        {"photo_url": "/assets/photos/real.jpg"}]})
    staged = stage_missing_seed_photos(tmp_path)
    assert staged == ["photos/real.jpg"]  # only the real photo path


def test_dual_source_both_scanned(tmp_path):
    _seed(tmp_path,
          dataset={"p": [{"photo_url": "/assets/photos/from_dataset.jpg"}]},
          data={"q": [{"photo_url": "/assets/photos/from_data.png"}]})
    staged = set(stage_missing_seed_photos(tmp_path))
    assert staged == {"photos/from_dataset.jpg", "photos/from_data.png"}


def test_no_seed_no_photos_empty(tmp_path):
    (tmp_path / "app" / "frontend" / "public" / "assets").mkdir(parents=True, exist_ok=True)
    assert stage_missing_seed_photos(tmp_path) == []


def test_no_image_refs_empty(tmp_path):
    _seed(tmp_path, dataset={"p": [{"name": "x", "rating": 4.1, "website": "https://x.com"}]})
    assert stage_missing_seed_photos(tmp_path) == []


def test_external_urls_not_localized_here(tmp_path):
    # an http(s) stock URL is the localizer's job, not ours — don't stage a local file for it
    _seed(tmp_path, dataset={"p": [{"photo_url": "https://picsum.photos/400"}]})
    assert stage_missing_seed_photos(tmp_path) == []


# ------------------------- real gmrun7 archive empiricism -------------------------

def test_real_gmrun7_photo_would_be_staged(tmp_path):
    import shutil
    gm7 = (ROOT.parent / "generated" /
           "googlemaps-core-di.SUCCESS-gmrun7-2of3-forcedeliver-M1M2realdata" /
           "app" / "backend" / "seed_dataset.json")
    if not gm7.exists():
        import pytest
        pytest.skip("gmrun7 archive absent")
    be = tmp_path / "app" / "backend"
    be.mkdir(parents=True, exist_ok=True)
    (tmp_path / "app" / "frontend" / "public" / "assets").mkdir(parents=True, exist_ok=True)
    shutil.copy2(gm7, be / "seed_dataset.json")
    staged = stage_missing_seed_photos(tmp_path)
    # the real dataset references /assets/photos/*.jpg → at least one must be generated
    assert any(s.startswith("photos/") for s in staged), staged
