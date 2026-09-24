"""frontend prompt must anchor the frontend root at `app/frontend/`.

Root cause of a stranded-app delivery deadlock (gemini instagram 2026-06-13): the
Phase-A ARCHITECTURE CONTRACT described the fixed layout with BARE `src/` paths
(`src/pages/`, `src/App.jsx`) while the deliverable checklist, few-shot tool
calls, the frontend baseline scaffold, docker-compose (`build: ../app/frontend`)
and the lifecycle audit ALL use `app/frontend/src/`. A literal-minded model
followed the architecture contract and authored a COMPLETE Vite app at the repo
ROOT (`./src`, `./package.json`) — which the framework never builds or gates, so
delivery saw a blank shell forever despite a real app existing.

This guards the disambiguation: the architecture contract must state the frontend
lives under `app/frontend/` and warn against scaffolding a second app at the repo
root, so the lane writes to the one path the build + gate read.
"""

from __future__ import annotations

from pathlib import Path

PROMPT = (
    Path(__file__).resolve().parents[1]
    / "env_generator" / "llm_generator" / "multi_agent" / "prompts" / "v3"
    / "frontend_agent.j2"
)


def _contract_region() -> str:
    text = PROMPT.read_text(encoding="utf-8")
    i = text.find("ARCHITECTURE CONTRACT")
    assert i != -1, "ARCHITECTURE CONTRACT section not found in frontend prompt"
    return text[i:i + 1400]


def test_architecture_contract_anchors_app_frontend_root():
    region = _contract_region()
    assert "app/frontend/" in region, \
        "architecture contract must anchor the frontend root at app/frontend/"
    # the canonical full paths must be shown so a literal model uses them
    assert "app/frontend/src/App.jsx" in region


def test_architecture_contract_warns_against_repo_root_scaffold():
    region = _contract_region().lower()
    # must explicitly tell the lane NOT to build a second app at the repo root
    assert "repo root" in region or "repo-root" in region
    assert "blank shell" in region  # the consequence is named so the model heeds it


def test_deliverable_and_contract_agree_on_app_frontend():
    # the deliverable checklist already uses app/frontend/ paths; the contract
    # must not contradict it with a bare-src layout claim.
    text = PROMPT.read_text(encoding="utf-8")
    assert "app/frontend/src/App.jsx" in text
    assert "app/frontend/src/pages" in text
