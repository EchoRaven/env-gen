"""Cutover 26: orchestrator marks project_metadata.status during a run."""
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.hub_registry import HubRegistry


def test_hub_registry_constructed_with_name_persists_name(tmp_path):
    # Mirrors the orchestrator's construction call.
    reg = HubRegistry(tmp_path, project_name="my_app")
    assert reg.project_metadata.name == "my_app"


def test_set_status_completed_persists_across_reload(tmp_path):
    reg = HubRegistry(tmp_path, project_name="my_app")
    reg.set_project_status("completed")
    del reg
    reg2 = HubRegistry(tmp_path)
    assert reg2.project_metadata.status == "completed"


def test_resume_after_failed_status(tmp_path):
    reg = HubRegistry(tmp_path, project_name="my_app")
    reg.set_project_status("failed")
    del reg
    # Resuming a failed project is allowed — orchestrator can re-run it
    reg2 = HubRegistry(tmp_path)
    assert reg2.project_metadata.status == "failed"
    reg2.set_project_status("active")  # resume bumps back to active
    assert reg2.project_metadata.status == "active"
