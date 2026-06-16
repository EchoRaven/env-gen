# agent/tests/test_project_resume_e2e.py
import shutil
import sys
import tarfile
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

import pytest

from multi_agent.runtime.hub_registry import HubRegistry
from multi_agent.runtime.project import (
    list_projects,
    resume_project,
    load_project_metadata,
)


def test_e2e_create_two_workspaces_then_list_them(tmp_path):
    root = tmp_path / "workspaces"
    root.mkdir()

    reg_a = HubRegistry(root / "proj_a_ws", project_id="proj_a", project_name="App A")
    reg_b = HubRegistry(root / "proj_b_ws", project_id="proj_b", project_name="App B")

    listed = list_projects(root)
    ids = sorted(p.id for p in listed)
    assert ids == ["proj_a", "proj_b"]


def test_e2e_resume_returns_workspace_path_and_reusable_registry(tmp_path):
    root = tmp_path / "workspaces"
    root.mkdir()
    reg1 = HubRegistry(root / "proj_a_ws", project_id="proj_a", project_name="App A")

    # Create some state on hub A
    reg1.workhub.create_task(
        task_id="t1", title="initial task", description="", agent="orchestrator",
        domain="any", priority="P1",
    )

    # "Exit": drop the registry handle
    del reg1

    # Resume from project_id alone (UI/CLI scenario)
    workspace = resume_project(root, "proj_a")
    assert workspace == root / "proj_a_ws"

    reg2 = HubRegistry(workspace)
    task = reg2.workhub.get_task("t1")
    assert task is not None
    assert task["title"] == "initial task"


def test_e2e_resume_unknown_project_returns_none(tmp_path):
    assert resume_project(tmp_path, "nope") is None


def test_e2e_completed_project_still_listed(tmp_path):
    root = tmp_path / "workspaces"
    root.mkdir()
    reg = HubRegistry(root / "proj_done_ws", project_id="proj_done", project_name="done app")
    reg.set_project_status("completed")
    del reg

    listed = list_projects(root)
    assert any(p.id == "proj_done" and p.status == "completed" for p in listed)


def test_e2e_workspace_is_self_contained_tarball_backup_restores(tmp_path):
    """A workspace dir + project.json is enough to back up and restore."""
    root = tmp_path / "workspaces"
    root.mkdir()
    reg = HubRegistry(root / "orig_ws", project_id="proj_backup", project_name="backup demo")
    reg.workhub.create_task(
        task_id="t_backup", title="will be backed up", description="", agent="orchestrator",
        domain="any", priority="P2",
    )
    del reg

    # Tarball the workspace
    backup = tmp_path / "backup.tar"
    with tarfile.open(backup, "w") as tar:
        tar.add(root / "orig_ws", arcname="restored_ws")

    # Wipe original
    shutil.rmtree(root / "orig_ws")
    assert load_project_metadata(root / "orig_ws") is None  # confirm gone

    # Restore elsewhere
    restore_root = tmp_path / "restored"
    restore_root.mkdir()
    with tarfile.open(backup) as tar:
        tar.extractall(restore_root)

    # Open as a fresh HubRegistry and prove state survived
    reg2 = HubRegistry(restore_root / "restored_ws")
    assert reg2.project_metadata.id == "proj_backup"
    assert reg2.workhub.get_task("t_backup")["title"] == "will be backed up"
