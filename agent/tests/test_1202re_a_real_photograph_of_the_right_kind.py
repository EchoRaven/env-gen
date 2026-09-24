r"""#1202re: when no filename token matches, bind to a real staged asset of the right KIND.

`_match_staged_asset` matches a URL against staged filenames by shared token, and its own
docstring left the outcome open: "how often the fallback lands on a real photo versus a
placeholder is NOT measured."

Measured now, and it is bad: tiktok-r130 matched 5 of 55 refs by name (9%) and tiktok-r129
matched 0 of 27. The reason is structural -- design-prep stages media under CONTENT-HASH names
(`9932bdd955452673e344caf5ee4ae765_tplv-tiktokx-cropcenter_100_100.jpeg`), and a hash shares no
token with `avatar/alice.jpg`. The match was unwinnable by construction, which is why r130's
imagery went 91% unresolved, its live_discover scored 0.43 and the visual gate blocked at an
average of 0.56.

What design-prep DOES keep is its classification, as directories: r130 staged 9 files under
`real_avatars/`, 70 under `real_videos/` (35 .mp4 paired with 35 .jpg poster frames), 24 under
`images/`, beside 36 `icons/` and 5 `fonts/`.

This is NOT the placeholder #1202qo removed. These are the photographs this env's own reference
material supplied, which is the same choice #1202qd already makes for seed rows: a sibling real
image, never a generated glyph. And it is not chrome: `icons/` and `fonts/` are never
candidates, so #1202jz's 193 icon-served-as-a-photograph bindings cannot return by this route.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "env_generator" / "llm_generator")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime.frontend_scaffold import (  # noqa: E402
    _category_asset_1202re, _local_ref_for, _staged_media_1202rf)

# r130's staged tree, in miniature
ASSETS = (["real_avatars/a%d.jpg" % i for i in range(3)]
          + ["real_videos/v%d.mp4" % i for i in range(3)]
          + ["real_videos/v%d.jpg" % i for i in range(3)]
          + ["images/%032x_tplv-tiktokx-cropcenter_100_100.jpeg" % i for i in range(4)]
          + ["icons/like-video-25-5m-likes_d5105f7e.svg", "fonts/TikTokFont.woff2"])


def _pick(url, field, tally=None):
    return _category_asset_1202re(url, field, ASSETS, tally)


def test_an_avatar_gets_a_real_avatar():
    assert _pick("https://p16.tiktokcdn.com/aweme/100x100/xyz.jpeg", "avatar_url") \
        .startswith("real_avatars/")


def test_a_video_url_gets_a_PLAYABLE_file():
    """real_videos/ holds .mp4 AND their .jpg posters; <video src="...jpg"> plays nothing."""
    got = _pick("https://v16.tiktokcdn.com/video/abc.mp4", "video_url")
    assert got.startswith("real_videos/") and got.endswith(".mp4")


def test_a_video_THUMBNAIL_gets_the_poster_not_the_movie():
    """The mirror error: <img src="...mp4"> renders nothing."""
    got = _pick("https://x/y.jpg", "video_thumbnail")
    assert got.startswith("real_videos/") and not got.endswith(".mp4")


def test_a_plain_thumbnail_gets_an_image():
    assert _pick("https://p16.tiktokcdn.com/tos/thumb/q.jpeg", "thumbnail_url") \
        .startswith("images/")


def test_chrome_is_never_a_candidate():
    """#1202jz: 193 corpus bindings served an icon as someone's photograph. Not via this path."""
    for field in ("avatar_url", "video_url", "thumbnail_url", "cover_image", "banner"):
        got = _pick("https://example.com/whatever.png", field)
        assert got is None or not got.startswith(("icons/", "fonts/"))


def test_a_non_imagery_field_gets_nothing():
    """A sound id is not a picture; inventing one would be the substitute the user ruled out."""
    assert _pick("https://example.com/whatever.bin", "sound_id") is None


def test_the_same_url_always_maps_to_the_same_asset():
    """The seed fingerprint depends on it: an unstable pick re-seeds on every boot."""
    url = "https://p16.tiktokcdn.com/aweme/100x100/xyz.jpeg"
    assert _pick(url, "avatar_url") == _pick(url, "avatar_url")


def test_different_urls_spread_across_the_pool():
    """One asset for every avatar in the app would look like a bug of its own."""
    got = {_pick("https://cdn/%d.jpg" % i, "avatar_url") for i in range(30)}
    assert len(got) > 1


def test_an_empty_category_falls_through(tmp_path):
    assert _category_asset_1202re("https://x/a.jpg", "avatar_url", ["icons/i.svg"]) is None


def test_the_resolver_counts_it_apart_from_a_name_match(tmp_path):
    """Folding it into `staged` would hide how often the token match actually wins."""
    pub = tmp_path / "public"
    (pub / "assets").mkdir(parents=True)
    tally = {}
    out = _local_ref_for("https://p16.tiktokcdn.com/aweme/1.jpeg", "avatar_url", pub,
                         ASSETS, tally)
    assert out.startswith("/assets/real_avatars/")
    assert tally.get("category_1202re") == 1
    assert not tally.get("staged")


def test_an_unresolvable_ref_is_still_left_alone():
    """#1202qo stands: nothing of the right kind exists -> the URL keeps its honest breakage."""
    tally = {}
    url = "https://example.com/whatever.bin"
    assert _local_ref_for(url, "sound_id", Path("/nowhere"), ASSETS, tally) == url


# --- no needless repeats (r129's squad filed "duplicate content, placeholder avatars") ----

def test_distinct_urls_get_distinct_assets_while_the_pool_lasts():
    tally = {}
    got = [_pick("https://cdn/avatar/%d.jpg" % i, "avatar_url", tally) for i in range(3)]
    assert len(set(got)) == 3


def test_an_exhausted_pool_spills_into_a_COMPATIBLE_one():
    """r130 sent 30 image-ish refs at a 24-file images/ pool and repeated three, while 35
    unused .jpg poster frames sat in real_videos/ -- equally real photographs."""
    tally = {}
    got = [_pick("https://cdn/thumb/%d.jpg" % i, "thumbnail_url", tally) for i in range(7)]
    assert len(set(got)) == 7                      # images/ holds only 4 here
    assert any(g.startswith("real_videos/") for g in got)
    assert not any(g.endswith(".mp4") for g in got)   # posters, never the movie


def test_a_video_url_never_spills_into_a_still():
    """There is nothing compatible to spill into: a still cannot stand in for a clip."""
    tally = {}
    got = [_pick("https://cdn/v/%d.mp4" % i, "video_url", tally) for i in range(6)]
    assert all(g.endswith(".mp4") for g in got)


def test_the_same_url_keeps_its_asset_across_calls():
    tally = {}
    url = "https://cdn/avatar/stable.jpg"
    assert _pick(url, "avatar_url", tally) == _pick(url, "avatar_url", tally)


def test_a_spent_pool_repeats_deterministically_rather_than_failing():
    tally = {}
    got = [_pick("https://cdn/v/%d.mp4" % i, "video_url", tally) for i in range(9)]
    assert len(got) == 9 and all(g for g in got)    # 3 clips, 9 refs -> repeats, never None


# --- the pool the PRODUCTION path actually hands over --------------------------------------

def test_the_lister_the_localizers_use_includes_video(tmp_path):
    """`_staged_assets` filters on image extensions, which is right for an <img> binding and
    wrong for this fallback. Feeding it to the category picker left every `video_url` asking
    for a playable file, finding an empty pool, and keeping its picsum URL -- the video half
    had never run. This test exists because the first version of #1202re was validated against
    a hand-built asset list instead of the lister the localizers call."""
    a = tmp_path / "assets"
    (a / "real_videos").mkdir(parents=True)
    (a / "images").mkdir()
    (a / "real_videos" / "clip.mp4").write_bytes(b"x")
    (a / "real_videos" / "clip.jpg").write_bytes(b"x")
    (a / "images" / "pic.jpeg").write_bytes(b"x")
    got = _staged_media_1202rf(tmp_path)
    assert "real_videos/clip.mp4" in got
    assert "real_videos/clip.jpg" in got and "images/pic.jpeg" in got


def test_a_video_field_resolves_through_that_lister(tmp_path):
    a = tmp_path / "assets"
    (a / "real_videos").mkdir(parents=True)
    (a / "real_videos" / "clip.mp4").write_bytes(b"x")
    (a / "real_videos" / "clip.jpg").write_bytes(b"x")
    pool = _staged_media_1202rf(tmp_path)
    assert _category_asset_1202re("https://picsum.photos/seed/live-1/640/360",
                                  "stream_url", pool, {}).endswith(".mp4")


def test_the_token_matcher_never_crosses_media_kinds(tmp_path):
    """The pool now carries videos; an <img> bound to an .mp4 renders nothing."""
    a = tmp_path / "assets"
    (a / "real_videos").mkdir(parents=True)
    (a / "real_videos" / "sunset-video-clip.mp4").write_bytes(b"x")
    (a / "real_videos" / "sunset-video-clip.jpg").write_bytes(b"x")
    pool = _staged_media_1202rf(tmp_path)
    out = _local_ref_for("https://cdn/sunset-video-clip.png", "thumbnail_url",
                         tmp_path, pool, {})
    assert not out.endswith(".mp4")
