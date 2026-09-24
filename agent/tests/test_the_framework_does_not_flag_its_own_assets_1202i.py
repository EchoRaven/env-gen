r"""#1202i: the framework's own staged asset paths are not lane-authored placeholder content.

`ensure_assets_staged_for_build` writes avatars as `/assets/placeholders/ph-avatar-N.svg`, and
the advisory placeholder scan — which matches its word list as SUBSTRINGS, deliberately — then
reads that filename as evidence the lane seeded placeholder data.

Measured over the 94 generated seeds: 181 tables cross the advisory threshold, and 74 of them
(41%) do so ONLY because of these paths. After excluding them: 107.

What this does NOT change is the policy the module documents. The BLOCKING check keeps its
strict, word-boundary vocabulary — its comment is explicit that "latest" must not hit "test"
and that 'test'/'sample' are not in that set at all — and the advisory scan keeps its
substring match over the full list. The framework's own filenames were never the lane's
content, so reading them as such was not a judgement about seeds.

★ Found by following a false positive of my own: a first pass at auditing seeds flagged
netflix r22 for "placeholder" data, and the hits were all `sample-videos.com` — a real CDN
hostname containing the word `sample`. Tightening my own regex led to the same pattern here,
where it costs 41% of an advisory's volume.
"""

import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

from multi_agent.runtime.seed_audit import (  # noqa: E402
    _PLACEHOLDER_THRESHOLD, detect_placeholder_score,
)


def test_the_frameworks_avatar_paths_do_not_score():
    rows = [{"name": "Ava Chen", "avatar": "/assets/placeholders/ph-avatar-%d.svg" % i}
            for i in range(1, 7)]
    assert detect_placeholder_score(rows) < _PLACEHOLDER_THRESHOLD


def test_real_placeholder_content_still_scores():
    rows = [{"title": "lorem ipsum", "body": "placeholder text"},
            {"title": "dummy", "body": "TODO"}]
    assert detect_placeholder_score(rows) >= _PLACEHOLDER_THRESHOLD


def test_an_asset_path_does_not_mask_placeholder_content_beside_it():
    """Excluding the path must not excuse the row it sits in."""
    rows = [{"avatar": "/assets/placeholders/ph-avatar-1.svg",
             "title": "lorem ipsum", "body": "dummy placeholder"}] * 3
    assert detect_placeholder_score(rows) >= _PLACEHOLDER_THRESHOLD


def test_a_real_cdn_hostname_containing_a_marker_word_is_still_matched():
    """Not fixed here, and deliberately so: the advisory scan's substring match is documented
    (`sample-videos.com` contains `sample`). The BLOCKING check is the one with word
    boundaries, and it does not carry `sample` at all."""
    rows = [{"video_url": "https://sample-videos.com/video321/mp4/720/x.mp4"}] * 6
    assert detect_placeholder_score(rows) >= _PLACEHOLDER_THRESHOLD


def test_the_blocking_vocabulary_keeps_word_boundaries():
    """The strict set must never gain `test`/`sample`, or a QA tracker's realistic seed and
    every `latest`/`greatest` string starts failing delivery."""
    src = (THIS_DIR.parent
           / "env_generator/llm_generator/multi_agent/runtime/seed_audit.py"
           ).read_text(encoding="utf-8")
    at = src.index("Strict subset of _PLACEHOLDER_WORDS")
    strict = src[at:src.index("\n\n\n", at)]
    assert '"test"' not in strict and '"sample"' not in strict
