"""Design-Prep Task 2 — --design-input resolution + back-compat.

``resolve_design_input(design_input, reference_dir, reference_images)`` returns
{references:[paths], docs:[paths], assets_dir: str|None}. With --design-input it reads the
references/ docs/ assets/ subfolders; without it, falls back to today's --reference-dir /
--reference-images (references-only). LOCAL-ONLY (agent/tests/ gitignored).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.design_prep import resolve_design_input  # noqa: E402


def test_design_input_three_folders(tmp_path):
    di = tmp_path / "design_input"
    (di / "references").mkdir(parents=True)
    (di / "docs").mkdir(parents=True)
    (di / "assets").mkdir(parents=True)
    (di / "references" / "a.png").write_bytes(b"x")
    (di / "references" / "notes.txt").write_text("skip me")  # non-image → not a reference
    (di / "docs" / "x.md").write_text("# design")
    (di / "assets" / "i.svg").write_text("<svg/>")

    out = resolve_design_input(str(di), None, [])
    assert [Path(p).name for p in out["references"]] == ["a.png"]
    assert [Path(p).name for p in out["docs"]] == ["x.md"]
    assert out["assets_dir"] and Path(out["assets_dir"]).name == "assets"


def test_design_input_missing_subfolders(tmp_path):
    di = tmp_path / "design_input"
    (di / "references").mkdir(parents=True)
    (di / "references" / "a.png").write_bytes(b"x")
    out = resolve_design_input(str(di), None, [])
    assert [Path(p).name for p in out["references"]] == ["a.png"]
    assert out["docs"] == []
    assert out["assets_dir"] is None  # no assets/ subfolder


def test_backcompat_reference_dir(tmp_path):
    rd = tmp_path / "refs"
    rd.mkdir()
    (rd / "home.png").write_bytes(b"x")
    (rd / "feed.jpg").write_bytes(b"y")
    out = resolve_design_input(None, str(rd), [])
    assert sorted(Path(p).name for p in out["references"]) == ["feed.jpg", "home.png"]
    assert out["docs"] == []
    assert out["assets_dir"] is None


def test_backcompat_reference_images_passthrough(tmp_path):
    p = tmp_path / "shot.png"
    p.write_bytes(b"x")
    out = resolve_design_input(None, None, [str(p)])
    assert [Path(x).name for x in out["references"]] == ["shot.png"]
    assert out["assets_dir"] is None


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
