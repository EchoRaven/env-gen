"""FIX #183 — design-prep's ingest_assets stages only IMAGE assets: _ingest_one returns None for
a .woff2 font, so `if not entry: continue` SKIPS it — the file is never copied into design/assets.
gmtiktok provided 5 real TikTok fonts (TikTokFont/Display/Sans) in the design-input, yet
design/assets/fonts was ABSENT, so the clone falls back to generic fonts (a dead giveaway — real
typography is a top visual-fidelity lever, "文字风格一致"). ingest_assets now ALSO stages font files
(+ a minimal manifest entry, type=font) so design_system assets[] carries them and lanes can
@font-face the real fonts. Pure/deterministic; LOCAL-ONLY.
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.material_prep import ingest_assets  # noqa: E402


def _mk_assets(tmp):
    src = Path(tmp) / "assets"
    (src / "fonts").mkdir(parents=True)
    (src / "icons").mkdir(parents=True)
    (src / "fonts" / "TikTokFont-Bold.woff2").write_bytes(b"wOF2" + b"\x00" * 300)
    (src / "fonts" / "TikTokSans-VF.woff2").write_bytes(b"wOF2" + b"\x00" * 300)
    (src / "icons" / "like.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M0 0h24v24H0z"/></svg>')
    return src


def test_ingest_assets_stages_fonts():
    with tempfile.TemporaryDirectory() as tmp:
        src = _mk_assets(tmp)
        stage = Path(tmp) / "design" / "assets"
        manifest = ingest_assets(src, stage)
        # the font files are physically staged (the #183 gap: they were dropped)
        assert (stage / "fonts" / "TikTokFont-Bold.woff2").exists(), "woff2 font not staged"
        assert (stage / "fonts" / "TikTokSans-VF.woff2").exists()
        # and they appear in the manifest tagged as fonts (so design_system assets[] carries them)
        fonts = [m for m in manifest if m.get("type") == "font"]
        assert len(fonts) >= 2
        assert any("TikTokFont-Bold" in str(m.get("id", "") + m.get("file", "")) for m in fonts)


def test_ingest_assets_stages_video_and_audio():
    # #184: .mp4 videos + audio are non-image too, so _ingest_one → None → they were dropped like
    # fonts were. For a video-centric clone (TikTok) that's catastrophic — thumbnails but no
    # playable videos. gmtiktok proved it: design/assets/real_videos had 35 jpg / 0 mp4.
    import tempfile as _t
    with _t.TemporaryDirectory() as tmp:
        adir = Path(tmp) / "assets"
        (adir / "real_videos").mkdir(parents=True)
        (adir / "sounds").mkdir(parents=True)
        (adir / "real_videos" / "dance_1.mp4").write_bytes(b"\x00\x00\x00 ftypmp42" + b"\x00" * 400)
        (adir / "sounds" / "clip.mp3").write_bytes(b"ID3" + b"\x00" * 200)
        stage = Path(tmp) / "design" / "assets"
        manifest = ingest_assets(adir, stage)
        assert (stage / "real_videos" / "dance_1.mp4").exists(), "mp4 video not staged"
        assert (stage / "sounds" / "clip.mp3").exists(), "mp3 audio not staged"
        assert any(m.get("type") == "video" for m in manifest)
        assert any(m.get("type") == "audio" for m in manifest)


def test_ingest_assets_still_stages_images():
    # regression: image staging must keep working (icons were fine before).
    with tempfile.TemporaryDirectory() as tmp:
        src = _mk_assets(tmp)
        stage = Path(tmp) / "design" / "assets"
        ingest_assets(src, stage)
        assert (stage / "icons" / "like.svg").exists()
