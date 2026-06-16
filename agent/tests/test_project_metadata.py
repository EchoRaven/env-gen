import json
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

import pytest
from multi_agent.runtime.project import (
    ProjectMetadata,
    load_project_metadata,
    save_project_metadata,
)


def test_project_metadata_save_load_roundtrip(tmp_path: Path):
    md = ProjectMetadata(
        id="proj_abc",
        name="Demo App",
        description="todo app for testing",
        created_at=1000.0,
        last_active_at=1500.0,
        status="active",
        agents_used=["orchestrator", "frontend"],
    )
    save_project_metadata(tmp_path, md)
    loaded = load_project_metadata(tmp_path)
    assert loaded == md


def test_load_project_metadata_returns_none_when_missing(tmp_path: Path):
    assert load_project_metadata(tmp_path) is None


def test_save_creates_project_json_file(tmp_path: Path):
    md = ProjectMetadata(id="x", name="x", created_at=0.0, last_active_at=0.0)
    save_project_metadata(tmp_path, md)
    p = tmp_path / "project.json"
    assert p.exists()
    data = json.loads(p.read_text())
    assert data["id"] == "x"


def test_status_must_be_known_value():
    with pytest.raises(ValueError):
        ProjectMetadata(id="x", name="x", created_at=0.0, last_active_at=0.0, status="bogus")


def test_default_status_is_active():
    md = ProjectMetadata(id="x", name="x", created_at=0.0, last_active_at=0.0)
    assert md.status == "active"


def test_legacy_workspace_without_project_json_treated_as_unregistered(tmp_path: Path):
    # Simulate pre-cutover workspace: shared/hubs/ exists but no project.json
    (tmp_path / "shared" / "hubs").mkdir(parents=True)
    assert load_project_metadata(tmp_path) is None
