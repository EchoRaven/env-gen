"""Agent-driven Design-Prep wiring: write_skeleton_design_system (the agent's starting doc, on
disk) + build_design_analyst_briefing (the spawn task description). LOCAL-ONLY.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.design_prep import (  # noqa: E402
    write_skeleton_design_system, build_design_analyst_briefing)


def _png(path, size=(64, 24), color=(255, 255, 255)):
    from PIL import Image
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path)


def test_write_skeleton_persists_the_agent_starting_doc(tmp_path):
    di = tmp_path / "design_input"
    (di / "references").mkdir(parents=True)
    (di / "assets").mkdir(parents=True)
    _png(di / "references" / "home.png")
    (di / "assets" / "logo.png").write_bytes(b"x")

    out = tmp_path / "out"
    resolved = {"references": [str(di / "references" / "home.png")], "docs": [],
                "assets_dir": str(di / "assets")}
    ds = write_skeleton_design_system(resolved, out)

    # the agent reads this exact file; it must exist with the staged assets + a measured palette
    ondisk = json.loads((out / "design" / "design_system.json").read_text())
    assert ondisk == ds
    assert ondisk["design_system"]["palette"].get("bg")
    assert [a["id"] for a in ondisk["assets"]] == ["logo"]
    assert (out / "design" / "assets" / "logo.png").exists()   # staged
    assert ondisk["screens"][0]["name"] == "home"


def test_briefing_points_the_agent_at_the_work(tmp_path):
    resolved = {"references": [str(tmp_path / "home.png"), str(tmp_path / "feed.png")],
                "docs": [], "assets_dir": str(tmp_path / "assets")}
    b = build_design_analyst_briefing(tmp_path / "out", resolved)
    assert "design_system.json" in b
    assert "home.png" in b and "feed.png" in b        # names the screens to cover
    assert "finish()" in b
    assert "measure" in b.lower()


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
