"""#1202qf: an HEVC video is staged as H.264 (tiktok's 35 real videos were all hvc1, so every
feed card rendered black in Chromium); without ffmpeg it is staged as-is and marked."""
import shutil
import subprocess
from pathlib import Path

import pytest

from env_generator.llm_generator.multi_agent.runtime import material_prep as MP


def test_the_codec_is_read_from_the_container_tags(tmp_path):
    (tmp_path / "a.mp4").write_bytes(b"\x00" * 64 + b"hvc1" + b"\x00" * 64)
    (tmp_path / "b.mp4").write_bytes(b"\x00" * 64 + b"avc1" + b"\x00" * 64)
    assert MP._video_codec_1202qf(tmp_path / "a.mp4") == "hevc"
    assert MP._video_codec_1202qf(tmp_path / "b.mp4") == "h264"


def test_without_ffmpeg_hevc_is_staged_and_marked_unplayable(tmp_path, monkeypatch):
    src, stage = tmp_path / "in", tmp_path / "out"
    (src / "real_videos").mkdir(parents=True)
    (src / "real_videos" / "clip.mp4").write_bytes(b"\x00" * 64 + b"hvc1" + b"\x00" * 64)
    monkeypatch.setattr(MP, "_ffmpeg_1202qf", lambda: "")
    manifest = MP.ingest_assets(src, stage)
    entry = next(e for e in manifest if e["type"] == "video")
    assert entry["browser_playable"] is False and entry["codec"] == "hevc"
    assert (stage / "real_videos" / "clip.mp4").exists()


def test_a_real_hevc_clip_is_staged_as_h264(tmp_path):
    exe = MP._ffmpeg_1202qf()
    if not exe or "libx265" not in subprocess.run([exe, "-hide_banner", "-encoders"],
                                                  capture_output=True, text=True).stdout:
        pytest.skip("no ffmpeg with libx265 to make an HEVC fixture")
    src, stage = tmp_path / "in", tmp_path / "out"
    src.mkdir()
    subprocess.run([exe, "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                    "testsrc=size=64x64:rate=10:duration=1", "-c:v", "libx265", "-tag:v", "hvc1",
                    str(src / "clip.mp4")], check=True, timeout=120)
    assert MP._video_codec_1202qf(src / "clip.mp4") == "hevc"
    manifest = MP.ingest_assets(src, stage)
    entry = next(e for e in manifest if e["type"] == "video")
    assert entry.get("transcoded_from") == "hevc"
    assert MP._video_codec_1202qf(stage / "clip.mp4") == "h264"
    assert MP._video_codec_1202qf(src / "clip.mp4") == "hevc"   # the input is never modified
