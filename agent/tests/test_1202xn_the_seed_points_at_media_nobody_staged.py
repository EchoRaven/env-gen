"""#1202xn: the stager guarantees seed IMAGES resolve; the seed also references VIDEO.

`stage_missing_seed_photos` exists because "a seed `photo_url` like
/assets/photos/restaurant_2.jpg is a local path ... so the file was never created -> every
<img> 404s (a broken-image glyph on every card)". Its regex is `jpe?g|png|webp|gif`.

A missing video fails the same way for a viewer, and more quietly: the card RENDERS, because
its `thumbnail_url` is an image and therefore IS staged, and the media only fails when played.

MEASURED across the 154 delivered runs carrying seeded /assets references: 246 of 10,227 point
at a file that is not on disk, in 16 runs. Time-sliced it is live but thin -- of the last
fourteen tiktok runs, r124 (2), r129 (3) and r135 (1) ship some and the rest none. Confirmed
over HTTP against the running stacks, not the filesystem alone: r135's
`spencerx__7656058026427763973.mp4` answers 404 from the delivered frontend.

r132 is the case this deliberately does NOT claim: two of its media files EXIST on disk and
the container still 404s them -- a staging-versus-build-order fault, a different owner.

REPORTS, NEVER BLOCKS, and synthesises no placeholder video: the framework stages REAL media
(71 files in r135), a grey stand-in would be worse than a stated gap, and choosing between
dropping the row and repointing it is a behaviour change that deserves a live run.
"""
import ast
import json
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

from multi_agent.runtime.frontend_scaffold import (  # noqa: E402
    record_unstaged_seed_media_1202xn,
    unstaged_seed_media_1202xn,
)

_FS = os.path.join(_AGENT, "env_generator", "llm_generator", "multi_agent", "runtime",
                   "frontend_scaffold.py")


def _run(tmp_path, seed, staged=()):
    be = tmp_path / "app" / "backend"
    pub = tmp_path / "app" / "frontend" / "public" / "assets" / "real_videos"
    be.mkdir(parents=True)
    pub.mkdir(parents=True)
    (be / "seed_dataset.json").write_text(json.dumps(seed), encoding="utf-8")
    for name in staged:
        (pub / name).write_bytes(b"x" * 64)
    return tmp_path


_SEED = {"videos": [
    {"id": 1, "video_url": "/assets/real_videos/a.mp4",
     "thumbnail_url": "/assets/real_videos/a.jpg"},
    {"id": 2, "video_url": "/assets/real_videos/b.mp4",
     "thumbnail_url": "/assets/real_videos/b.jpg"},
]}


def test_an_unstaged_video_is_reported(tmp_path):
    got = unstaged_seed_media_1202xn(_run(tmp_path, _SEED, staged=["a.mp4"]))
    assert got == ["/assets/real_videos/b.mp4 (not staged)"], got


def test_everything_staged_is_silent(tmp_path):
    assert unstaged_seed_media_1202xn(_run(tmp_path, _SEED, staged=["a.mp4", "b.mp4"])) == []


def test_images_are_not_this_check(tmp_path):
    """★ `stage_missing_seed_photos` owns those and CREATES them; reporting them here would
    duplicate a fix as a finding."""
    got = unstaged_seed_media_1202xn(_run(tmp_path, _SEED, staged=["a.mp4", "b.mp4"]))
    assert got == [], got
    assert not any(g.endswith((".jpg", ".png")) for g in
                   unstaged_seed_media_1202xn(_run(tmp_path / "x", _SEED)))


def test_framework_owned_directories_are_skipped(tmp_path):
    """icons/ and placeholders/ are staged by other mechanisms; claiming them would be noise."""
    seed = {"x": [{"u": "/assets/placeholders/ph.mp4"}, {"u": "/assets/icons/i.mp4"},
                  {"u": "/assets/real_videos/c.mp4"}]}
    got = unstaged_seed_media_1202xn(_run(tmp_path, seed))
    assert got == ["/assets/real_videos/c.mp4 (not staged)"], got


def test_a_missing_or_unreadable_run_is_silent(tmp_path):
    assert unstaged_seed_media_1202xn(tmp_path) == []
    assert unstaged_seed_media_1202xn("/nonexistent/xn") == []


def test_the_artifact_is_written_and_appends(tmp_path):
    assert record_unstaged_seed_media_1202xn(tmp_path, ["/assets/real_videos/b.mp4"]) is True
    assert record_unstaged_seed_media_1202xn(tmp_path, ["/assets/real_videos/c.mp4"]) is True
    p = tmp_path / "logs" / "unstaged_seed_media_1202xn.jsonl"
    rows = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(rows) == 2 and rows[0]["media"] == ["/assets/real_videos/b.mp4"]


def test_an_empty_finding_writes_nothing(tmp_path):
    assert record_unstaged_seed_media_1202xn(tmp_path, []) is False
    assert not (tmp_path / "logs" / "unstaged_seed_media_1202xn.jsonl").exists()


def test_the_detector_runs_after_the_stager_and_reaches_an_artifact():
    """★ Order matters: run before `stage_missing_seed_photos` and it would report what
    staging is about to fix. Asserted on AST Call nodes, not on the names appearing in the
    source -- an import line makes a name present without a call (#1202xk)."""
    with open(_FS, encoding="utf-8") as fh:      # #1202eu
        tree = ast.parse(fh.read())
    calls = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            nm = getattr(node.func, "id", "")
            if nm in ("stage_missing_seed_photos", "unstaged_seed_media_1202xn",
                      "record_unstaged_seed_media_1202xn"):
                calls.setdefault(nm, node.lineno)
    for nm in ("unstaged_seed_media_1202xn", "record_unstaged_seed_media_1202xn"):
        assert nm in calls, "%s is never called" % nm
    assert calls["stage_missing_seed_photos"] < calls["unstaged_seed_media_1202xn"], (
        "the report runs before the stager, so it would name files staging then creates")


# --- #1202xo: on disk is not the same as in the image -------------------------------------

def _with_dockerignore(tmp_path, lines):
    fe = tmp_path / "app" / "frontend"
    fe.mkdir(parents=True, exist_ok=True)
    (fe / ".dockerignore").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return tmp_path


def test_a_staged_video_excluded_from_the_image_is_reported(tmp_path):
    """★ r109/r110/r114/r119 each exclude `public/assets/real_videos/*.mp4` -- EVERY video,
    35/35/36/35 of them, all present on disk. The disk check alone reports 0 for all four."""
    root = _run(tmp_path, _SEED, staged=["a.mp4", "b.mp4"])
    _with_dockerignore(root, ["node_modules", "public/assets/real_videos/*.mp4"])
    got = unstaged_seed_media_1202xn(root)
    assert len(got) == 2, got
    assert all("excluded from the image" in g for g in got), got


def test_the_r132_shape_a_single_named_exclusion(tmp_path):
    root = _run(tmp_path, _SEED, staged=["a.mp4", "b.mp4"])
    _with_dockerignore(root, ["# the corrupt large media pair",
                              "public/assets/real_videos/b.mp4"])
    got = unstaged_seed_media_1202xn(root)
    assert got == ["/assets/real_videos/b.mp4 (excluded from the image by .dockerignore)"], got


# A `test_a_comment_line_is_not_a_pattern` stood here and was REMOVED as vacuous. r132's real
# .dockerignore does carry its reason in comments naming the very files, so the case looked
# worth pinning -- but a comment can never match as a pattern anyway: `#` is a literal in
# fnmatch, so `# public/assets/real_videos/a.mp4 was corrupt` matches nothing with or without
# the `startswith("#")` filter. The test passed under a mutation that removed that filter,
# which is #1202's rule that a green test proving nothing is not a test. The filter stays in
# the code as cheap defence; it simply cannot be exercised from behaviour.


def test_the_cause_is_named_so_the_owner_is_clear(tmp_path):
    """★ "not staged" and "staged then excluded" have different owners; a reader who cannot
    tell them apart looks in the wrong place."""
    root = _run(tmp_path, _SEED, staged=["a.mp4"])      # b.mp4 absent
    _with_dockerignore(root, ["public/assets/real_videos/a.mp4"])
    got = unstaged_seed_media_1202xn(root)
    assert sorted(got) == [
        "/assets/real_videos/a.mp4 (excluded from the image by .dockerignore)",
        "/assets/real_videos/b.mp4 (not staged)",
    ], got


def test_an_unrelated_ignore_entry_changes_nothing(tmp_path):
    root = _run(tmp_path, _SEED, staged=["a.mp4", "b.mp4"])
    _with_dockerignore(root, ["node_modules", "dist", "*.log"])
    assert unstaged_seed_media_1202xn(root) == []
