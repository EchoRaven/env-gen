"""Design-Prep Task 1 — deterministic asset ingestion + staging.

``ingest_assets(assets_dir, stage_dir)`` scans a user-provided ``assets/`` folder, produces a
manifest entry per image {id,file,type,dims,transparent,dominant_colors,staged_path}, and copies
each file into ``stage_dir`` (preserving any icons/ logos/ subfolder grouping). Best-effort: a
missing dir → [], unreadable files skipped, never raises. LOCAL-ONLY (agent/tests/ gitignored).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import multi_agent.runtime.material_prep as mp  # noqa: E402


def _write_png(path, size=(16, 16), color=(52, 128, 243), alpha=None):
    from PIL import Image
    if alpha is not None:
        im = Image.new("RGBA", size, color + (alpha,))
    else:
        im = Image.new("RGB", size, color)
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path)


_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="103" height="29" viewBox="0 0 103 29">'
    '<path fill="#3880f3" d="M0 0h10v10H0z"/></svg>'
)


def test_manifest_and_staging(tmp_path):
    assets = tmp_path / "assets"
    (assets / "icons").mkdir(parents=True)
    (assets / "icons" / "Heart Icon.svg").write_text(_SVG, encoding="utf-8")
    _write_png(assets / "logo.png", alpha=0)  # fully transparent → transparent=True

    stage = tmp_path / "staged"
    manifest = mp.ingest_assets(assets, stage)

    assert isinstance(manifest, list) and len(manifest) == 2
    by_id = {m["id"]: m for m in manifest}

    heart = by_id["heart-icon"]
    assert heart["type"] == "svg"
    assert heart["transparent"] is True
    assert heart["dims"] == [103, 29]              # parsed from width/height
    assert "#3880f3" in heart["dominant_colors"]   # fill parsed from SVG source
    assert heart["staged_path"] == "public/assets/icons/Heart Icon.svg"
    assert (stage / "icons" / "Heart Icon.svg").exists()   # copied, grouping preserved

    logo = by_id["logo"]
    assert logo["type"] == "png"
    assert logo["transparent"] is True
    assert logo["dims"] == [16, 16]
    assert logo["staged_path"] == "public/assets/logo.png"
    assert (stage / "logo.png").exists()


def test_missing_dir_is_empty(tmp_path):
    assert mp.ingest_assets(tmp_path / "nope", tmp_path / "s") == []


def test_id_collision_disambiguated(tmp_path):
    assets = tmp_path / "assets"
    (assets / "a").mkdir(parents=True)
    (assets / "b").mkdir(parents=True)
    _write_png(assets / "a" / "logo.png")
    _write_png(assets / "b" / "logo.png")
    ids = sorted(m["id"] for m in mp.ingest_assets(assets, tmp_path / "s"))
    assert ids == ["logo", "logo-2"]


def test_svg_dims_from_viewbox_not_inner_element(tmp_path):
    # a real-world trap (IG comment icon): the root is 24x24 but an inner <rect> has width='2' —
    # dims must come from viewBox (or the ROOT width/height), never a later inner element's.
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "comment.svg").write_text(
        '<svg width="24" height="24" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">'
        '<rect x="0" y="0" width="2" height="24" fill="#000"/></svg>', encoding="utf-8")
    m = mp.ingest_assets(assets, tmp_path / "s")[0]
    assert m["dims"] == [24, 24]                     # viewBox wins, not the inner rect's width=2


def test_opaque_png_not_transparent(tmp_path):
    assets = tmp_path / "assets"
    assets.mkdir()
    _write_png(assets / "bg.jpg", size=(8, 8))  # saved as jpg → no alpha
    m = mp.ingest_assets(assets, tmp_path / "s")[0]
    assert m["type"] == "jpg" and m["transparent"] is False


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
