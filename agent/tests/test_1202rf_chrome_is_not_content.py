r"""#1202rf: an icon sitting in a content-image field is repaired, not left to render.

#1202jz measured this harm and closed one door: 193 corpus bindings served an icon as
someone's photograph, and it stopped the filename-token matcher from producing them. The lane
can write one directly, and tiktok-r130 did -- all ten `live_streams.stream_url` rows read
`/assets/icons/go-to-tiktok-for-you-feed_50508994.svg`, an arrow glyph standing in for a live
video, on the `live_discover` page that has scored at or below 0.50 in ten consecutive runs.

The localizer never saw them: it inspects http(s) values only, and a local chrome path is worse
than an unresolvable URL because it RENDERS -- nothing looks broken, so nothing gets reported.
#934's rule is that a guard belongs at the common ancestor of every producing branch, and this
harm had two.

Routing the repair through `_local_ref_for` does not work and the first draft proved it: handed
an icon path, the token matcher returns ANOTHER icon (r130:
go-to-tiktok-for-you-feed_50508994 -> _d58e3f44), which changes the value and repairs nothing.
A chrome path in a content field needs a picture, so it asks for one directly.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "env_generator" / "llm_generator")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime.frontend_scaffold import (  # noqa: E402
    _chrome_as_content_1202rf, localize_seed_external_images)


def test_the_r130_case_is_recognised():
    assert _chrome_as_content_1202rf(
        "stream_url", "/assets/icons/go-to-tiktok-for-you-feed_50508994.svg")


def test_a_real_photo_in_a_content_field_is_fine():
    assert not _chrome_as_content_1202rf("stream_url", "/assets/real_videos/clip.mp4")


def test_a_logo_may_legitimately_be_an_icon():
    """Flagging it would be a false positive on a correct binding."""
    assert not _chrome_as_content_1202rf("logo_url", "/assets/icons/wordmark.svg")


def test_an_icon_field_is_left_alone():
    assert not _chrome_as_content_1202rf("icon_url", "/assets/icons/heart.svg")


def test_a_font_in_a_content_field_counts_too():
    assert _chrome_as_content_1202rf("avatar_url", "/assets/fonts/TikTokFont.woff2")


def _project(tmp_path, seed):
    be, fe = tmp_path / "app" / "backend", tmp_path / "app" / "frontend"
    be.mkdir(parents=True)
    a = fe / "public" / "assets"
    (a / "real_videos").mkdir(parents=True)
    (a / "real_avatars").mkdir()
    (a / "icons").mkdir()
    for i in range(3):
        (a / "real_videos" / ("clip%d.mp4" % i)).write_bytes(b"x")
        (a / "real_videos" / ("clip%d.jpg" % i)).write_bytes(b"x")
        (a / "real_avatars" / ("face%d.jpg" % i)).write_bytes(b"x")
    (a / "icons" / "arrow_50508994.svg").write_bytes(b"x")
    (be / "seed_data.json").write_text(json.dumps(seed), encoding="utf-8")
    return be, fe


def test_the_live_stream_icon_becomes_a_playable_clip(tmp_path):
    be, fe = _project(tmp_path, {"live_streams": [
        {"id": 1, "stream_url": "/assets/icons/arrow_50508994.svg"}]})
    localize_seed_external_images(be, fe)
    out = json.loads((be / "seed_data.json").read_text(encoding="utf-8"))
    got = out["live_streams"][0]["stream_url"]
    assert got.startswith("/assets/real_videos/") and got.endswith(".mp4")


def test_an_avatar_icon_becomes_a_face(tmp_path):
    be, fe = _project(tmp_path, {"users": [
        {"id": 1, "avatar_url": "/assets/icons/arrow_50508994.svg"}]})
    localize_seed_external_images(be, fe)
    out = json.loads((be / "seed_data.json").read_text(encoding="utf-8"))
    assert out["users"][0]["avatar_url"].startswith("/assets/real_avatars/")


def test_nothing_else_in_the_seed_is_touched(tmp_path):
    be, fe = _project(tmp_path, {"videos": [
        {"id": 1, "caption": "pov: the skyline hits the beat",
         "sound": "original sound", "like_count": 3860,
         "thumbnail_url": "/assets/real_videos/clip0.jpg"}]})
    localize_seed_external_images(be, fe)
    out = json.loads((be / "seed_data.json").read_text(encoding="utf-8"))
    row = out["videos"][0]
    assert row["caption"] == "pov: the skyline hits the beat"
    assert row["like_count"] == 3860
    assert row["thumbnail_url"] == "/assets/real_videos/clip0.jpg"   # already correct


def test_it_is_idempotent(tmp_path):
    be, fe = _project(tmp_path, {"live_streams": [
        {"id": 1, "stream_url": "/assets/icons/arrow_50508994.svg"}]})
    localize_seed_external_images(be, fe)
    once = (be / "seed_data.json").read_text(encoding="utf-8")
    localize_seed_external_images(be, fe)
    assert (be / "seed_data.json").read_text(encoding="utf-8") == once
