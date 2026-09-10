"""#1202jz: one shared word bound a video thumbnail to a "like" icon.

`_match_staged_asset` scored filename-token overlap with `best_n` starting at 0, so a SINGLE
accidental token won. Chrome assets carry descriptive names (`like-video-25-5m-likes.svg`) and
photographs often do not, so the icon won on the word "video" and the seed's `thumbnail` came
to hold a like button.

Measured over the recent corpus (googlemaps-r16 excluded, #1202jw), 896 content-image seed
fields: 646 hold a real asset, 57 an honest placeholder, and **193 an icon** — a wrong picture
presented as a real one, across 11 runs, tiktok-r111 alone with 55. That is 3.4x the
placeholder branch, and it hid inside the "staged" tally, which is why #1202jq could find no
correlation between placeholder share and visual score: the damage was in the other bucket.

The vocabulary is the framework's own — `_content_image_assets` already excludes exactly these
tokens when picking content imagery. It simply never reached the matcher.

HONEST LIMIT, pinned below: how often the fallback lands on a real photograph rather than a
placeholder is NOT measured and cannot be — the pre-rewrite URLs are overwritten in place. I
started a simulation on invented URLs, saw it was measuring my invention, and threw it away.
What is measured is the 193 bindings this removes.
"""
import sys
import pathlib

_AGENT = pathlib.Path(__file__).resolve().parents[1]
if str(_AGENT) not in sys.path:
    sys.path.insert(0, str(_AGENT))

import inspect                                                        # noqa: E402

from env_generator.llm_generator.multi_agent.runtime import frontend_scaffold as FS  # noqa: E402

_M = FS._match_staged_asset

_ASSETS = ["icons/like-video-25-5m-likes_d5105f7e.svg",
           "icons/explore-card-user-verified_6717018b.svg",
           "images/skateboard-video-still_9f2.jpeg",
           "avatars/creator-avatar-zach_1a2.jpeg"]


def test_a_thumbnail_no_longer_binds_to_a_like_icon():
    """★ tiktok-r105/r111's shape, by the exact filename."""
    got = _M("https://cdn.example.com/tos-video-cover-abc.jpeg", "thumbnail", _ASSETS)
    assert got != "icons/like-video-25-5m-likes_d5105f7e.svg"
    assert got == "images/skateboard-video-still_9f2.jpeg", (
        "the real photograph shares the same token and should win once chrome is out")


def test_nothing_rather_than_chrome_when_no_photo_matches():
    """A placeholder (which #1202jq counts and warns about) beats a wrong picture."""
    assert _M("https://cdn.example.com/tos-video-cover-abc.jpeg", "thumbnail",
              ["icons/like-video-25-5m-likes_d5105f7e.svg"]) is None


def test_an_icon_field_may_still_take_an_icon():
    """The exclusion is about CONTENT imagery — chrome fields still want chrome."""
    assert _M("https://cdn.example.com/verified-badge.svg", "icon_url",
              ["icons/explore-card-user-verified_6717018b.svg"]) is not None


def test_an_avatar_still_matches_an_avatar():
    """Non-regression: avatars are not chrome and must keep binding."""
    got = _M("https://cdn.example.com/avatar-zach.jpeg", "avatar", _ASSETS)
    assert got == "avatars/creator-avatar-zach_1a2.jpeg"


def test_every_content_word_is_covered():
    """The seed fields measured as damaged: thumb/poster/cover/backdrop/banner/video/media."""
    for field in ("thumbnail", "thumbnail_url", "poster", "cover_image", "backdrop_path",
                  "banner", "video_url", "media_url", "preview_image"):
        assert _M("https://x/y-video-1.jpg", field,
                  ["icons/like-video-25-5m-likes_d5105f7e.svg"]) is None, field


def test_the_unmeasured_half_is_labelled():
    """A count invites a causal reading; the half the corpus cannot answer must say so."""
    doc = inspect.getdoc(_M) or ""
    assert "HONEST LIMIT" in doc
    assert "overwritten in place" in doc, "why the corpus cannot answer it"
    assert "193" in doc, "and what IS measured"
