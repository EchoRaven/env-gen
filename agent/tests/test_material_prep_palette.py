"""Material-prep brick 1: MEASURED color extraction (PIPELINE.md §3 — "don't guess colors").
Row-mode background sampling + saturation accent scan, deterministic (PIL only).
"""

import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

import pytest  # noqa: E402

PIL = pytest.importorskip("PIL")
from PIL import Image, ImageDraw  # noqa: E402
from multi_agent.runtime.material_prep import (  # noqa: E402
    row_mode_color, region_background, find_accent, extract_palette)


def _synthetic(tmp_path):
    # a 200x200 image: neutral-gray chrome background with a royal-blue button + red icon,
    # so row-mode must return the gray (not the button) and the blue scan must find the button
    im = Image.new("RGB", (200, 200), (0x29, 0x29, 0x29))
    d = ImageDraw.Draw(im)
    d.rectangle([10, 80, 70, 110], fill=(0x27, 0x5d, 0xa0))   # royal blue button
    d.rectangle([150, 10, 165, 25], fill=(0xc8, 0x30, 0x30))  # small red icon
    p = tmp_path / "ref.png"
    im.save(p)
    return p


def test_row_mode_returns_background_not_a_small_element(tmp_path):
    p = _synthetic(tmp_path)
    im = Image.open(p).convert("RGB")
    # top row is pure gray chrome → row-mode = gray, never the red icon
    assert row_mode_color(im, 0.02) == "#292929"
    assert region_background(im) == "#292929"


def test_find_accent_picks_the_saturated_button(tmp_path):
    p = _synthetic(tmp_path)
    im = Image.open(p).convert("RGB")
    blue = find_accent(im, hue="blue")
    assert blue == "#275da0"                       # the royal-blue button, not the gray bg
    red = find_accent(im, hue="red")
    assert red == "#c83030"


def test_extract_palette_shape(tmp_path):
    p = _synthetic(tmp_path)
    pal = extract_palette(p)
    assert pal["background"] == "#292929"
    assert pal["accents"].get("blue") == "#275da0"
    assert pal["accents"].get("red") == "#c83030"


def test_no_such_hue_returns_none(tmp_path):
    im = Image.new("RGB", (50, 50), (0x29, 0x29, 0x29))   # all neutral gray
    p = tmp_path / "g.png"; im.save(p)
    assert find_accent(Image.open(p).convert("RGB"), hue="blue") is None


def test_missing_file_does_not_raise(tmp_path):
    out = extract_palette(tmp_path / "nope.png")
    assert "error" in out


def test_on_real_outlook_component_crop_if_present():
    # if the reference component crops are on disk, the command-ribbon crop must yield a
    # royal-blue accent (the New-mail button) — the methodology's measured #275da0-ish
    crop = Path("/data/common/haibotong/outlook_components/inbox__03_command_ribbon.png")
    if not crop.exists():
        pytest.skip("reference crop not present")
    pal = extract_palette(crop)
    blue = pal["accents"].get("blue")
    assert blue is not None and blue.startswith("#")
    r = int(blue[1:3], 16); g = int(blue[3:5], 16); b = int(blue[5:7], 16)
    assert b > r and b > 100          # genuinely blue, measured not guessed


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
