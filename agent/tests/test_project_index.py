import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

import pytest
from multi_agent.runtime.project import (
    ProjectIndex,
    ProjectMetadata,
    save_project_metadata,
)


def _seed(root: Path, pid: str, name: str, status: str, last_active: float):
    ws = root / pid
    ws.mkdir(parents=True, exist_ok=True)
    save_project_metadata(
        ws,
        ProjectMetadata(id=pid, name=name, created_at=last_active, last_active_at=last_active, status=status),
    )


def test_list_empty_workspaces_root(tmp_path):
    idx = ProjectIndex(tmp_path)
    assert idx.list() == []


def test_list_returns_all_projects(tmp_path):
    _seed(tmp_path, "proj_a", "App A", "active", 100.0)
    _seed(tmp_path, "proj_b", "App B", "completed", 200.0)
    idx = ProjectIndex(tmp_path)
    ids = sorted(p.id for p in idx.list())
    assert ids == ["proj_a", "proj_b"]


def test_list_skips_directories_without_project_json(tmp_path):
    (tmp_path / "not_a_project").mkdir()
    _seed(tmp_path, "proj_a", "App A", "active", 100.0)
    idx = ProjectIndex(tmp_path)
    ids = [p.id for p in idx.list()]
    assert ids == ["proj_a"]


def test_list_filters_by_status(tmp_path):
    _seed(tmp_path, "proj_a", "A", "active", 1.0)
    _seed(tmp_path, "proj_b", "B", "completed", 2.0)
    _seed(tmp_path, "proj_c", "C", "completed", 3.0)
    idx = ProjectIndex(tmp_path)
    completed_ids = sorted(p.id for p in idx.list(status="completed"))
    assert completed_ids == ["proj_b", "proj_c"]


def test_list_sorted_by_last_active_desc(tmp_path):
    _seed(tmp_path, "proj_old", "old", "active", 100.0)
    _seed(tmp_path, "proj_new", "new", "active", 999.0)
    _seed(tmp_path, "proj_mid", "mid", "active", 500.0)
    idx = ProjectIndex(tmp_path)
    ids = [p.id for p in idx.list()]
    assert ids == ["proj_new", "proj_mid", "proj_old"]


def test_get_returns_workspace_path_for_known_project(tmp_path):
    _seed(tmp_path, "proj_a", "A", "active", 1.0)
    idx = ProjectIndex(tmp_path)
    md, workspace = idx.get("proj_a")
    assert md.id == "proj_a"
    assert workspace == tmp_path / "proj_a"


def test_get_unknown_project_returns_none(tmp_path):
    idx = ProjectIndex(tmp_path)
    assert idx.get("nope") == (None, None)


def test_list_skips_corrupted_project_json(tmp_path):
    _seed(tmp_path, "proj_a", "A", "active", 1.0)
    bad = tmp_path / "broken"
    bad.mkdir()
    (bad / "project.json").write_text("{not valid json")
    idx = ProjectIndex(tmp_path)
    ids = [p.id for p in idx.list()]
    assert ids == ["proj_a"]
