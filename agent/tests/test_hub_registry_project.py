# agent/tests/test_hub_registry_project.py
import sys
import time
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

import pytest
from multi_agent.runtime.hub_registry import HubRegistry
from multi_agent.runtime.project import (
    load_project_metadata,
    ProjectMetadata,
)


def test_hub_registry_creates_project_json_on_first_init(tmp_path):
    reg = HubRegistry(tmp_path, project_name="My App", project_description="todo demo")
    md = load_project_metadata(tmp_path)
    assert md is not None
    assert md.name == "My App"
    assert md.description == "todo demo"
    assert md.status == "active"
    assert md.id  # auto-generated
    assert md.created_at > 0
    assert md.last_active_at >= md.created_at


def test_hub_registry_uses_explicit_project_id_when_provided(tmp_path):
    reg = HubRegistry(tmp_path, project_id="proj_custom_123", project_name="X")
    md = load_project_metadata(tmp_path)
    assert md.id == "proj_custom_123"


def test_hub_registry_reuses_existing_project_metadata_on_reload(tmp_path):
    reg1 = HubRegistry(tmp_path, project_name="First", project_description="d1")
    md1 = load_project_metadata(tmp_path)

    # Simulate restart: new HubRegistry pointed at same workspace, no name passed
    reg2 = HubRegistry(tmp_path)
    md2 = load_project_metadata(tmp_path)
    assert md2.id == md1.id
    assert md2.name == "First"          # preserved
    assert md2.description == "d1"      # preserved
    assert md2.created_at == md1.created_at


def test_hub_registry_passing_name_to_existing_project_does_not_clobber(tmp_path):
    HubRegistry(tmp_path, project_name="Original")
    HubRegistry(tmp_path, project_name="DIFFERENT NAME")
    md = load_project_metadata(tmp_path)
    assert md.name == "Original"


def test_touch_updates_last_active_at(tmp_path):
    reg = HubRegistry(tmp_path, project_name="X")
    md_before = load_project_metadata(tmp_path)
    time.sleep(0.01)
    reg.touch()
    md_after = load_project_metadata(tmp_path)
    assert md_after.last_active_at > md_before.last_active_at


def test_set_project_status_persists(tmp_path):
    reg = HubRegistry(tmp_path, project_name="X")
    reg.set_project_status("completed")
    md = load_project_metadata(tmp_path)
    assert md.status == "completed"


def test_set_project_status_rejects_invalid(tmp_path):
    reg = HubRegistry(tmp_path, project_name="X")
    with pytest.raises(ValueError):
        reg.set_project_status("totally_bogus")


def test_project_metadata_property_returns_current(tmp_path):
    reg = HubRegistry(tmp_path, project_name="X")
    assert reg.project_metadata.status == "active"
    reg.set_project_status("paused")
    assert reg.project_metadata.status == "paused"


def test_hub_registry_init_does_not_break_existing_hubs(tmp_path):
    # Sanity: post-Cutover 26 init must still leave hubs functional.
    reg = HubRegistry(tmp_path, project_name="X")
    assert reg.registryhub is not None
    assert reg.codehub is not None
    assert reg.workhub is not None
    assert reg.eventhub is not None
    assert reg.runhub is not None
