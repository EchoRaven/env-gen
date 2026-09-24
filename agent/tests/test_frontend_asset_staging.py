"""Design-Prep Task 6 — stage real assets into the frontend + the use-real-assets rule.

stage_design_assets(output_dir) copies design/assets/* → app/frontend/public/assets/ so the
built frontend serves + bundles the real assets. The frontend_agent prompt gains a rule telling
the lane to REFERENCE the staged real assets (never draw approximations). LOCAL-ONLY.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.frontend_scaffold import stage_design_assets  # noqa: E402


def test_stage_copies_assets_into_public(tmp_path):
    out = tmp_path / "out"
    (out / "design" / "assets" / "icons").mkdir(parents=True)
    (out / "design" / "assets" / "logo.svg").write_text("<svg/>")
    (out / "design" / "assets" / "icons" / "heart.png").write_bytes(b"x")

    copied = stage_design_assets(out)

    assert (out / "app" / "frontend" / "public" / "assets" / "logo.svg").exists()
    assert (out / "app" / "frontend" / "public" / "assets" / "icons" / "heart.png").exists()
    assert sorted(copied) == ["icons/heart.png", "logo.svg"]  # grouping preserved


def test_stage_no_design_assets_is_empty(tmp_path):
    assert stage_design_assets(tmp_path / "out") == []


def test_frontend_prompt_has_use_real_assets_rule():
    j2 = (LLM / "multi_agent" / "prompts" / "v3" / "frontend_agent.j2").read_text()
    assert "public/assets" in j2
    assert "design_system.json" in j2


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
