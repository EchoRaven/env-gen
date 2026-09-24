"""Seed ownership split (agent-only seed decision, 2026-06-29): the backend agent OWNS
the DATA file ``app/backend/seed_data.json`` (it must be able to write it), while the
framework owns the LOADER ``app/backend/seed_data.py`` (regenerated from the contract —
the agent must NOT clobber it). Mirrors custom_routes.py (lane) vs main.py (framework).
"""

import sys
import tempfile
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.path_routed_workspace import PathRoutedWorkspace  # noqa: E402
from multi_agent.agents.runtime.auto_commit import (  # noqa: E402
    _BACKEND_FRAMEWORK_OWNED, _BACKEND_LANE_OWNED)


def _ws():
    tmp = Path(tempfile.mkdtemp(prefix="seed_own_"))
    code = tmp / "worktrees/backend"
    code.mkdir(parents=True)
    return PathRoutedWorkspace(base_root=tmp, code_root=code)


def test_ownership_sets_classify_seed_files():
    # the LOADER is framework-owned; the DATA file is lane-owned
    assert "seed_data.py" in _BACKEND_FRAMEWORK_OWNED
    assert "seed_data.json" in _BACKEND_LANE_OWNED
    assert "seed_data.json" not in _BACKEND_FRAMEWORK_OWNED
    # the existing split is intact
    assert "main.py" in _BACKEND_FRAMEWORK_OWNED
    assert "custom_routes.py" in _BACKEND_LANE_OWNED


def test_backend_lane_may_write_seed_json():
    ws = _ws()
    assert ws.is_write_allowed("app/backend/seed_data.json", "backend") is True
    # sanity: the lane's other owned file is writable, the prefix is the lane's
    assert ws.is_write_allowed("app/backend/custom_routes.py", "backend") is True


def test_backend_lane_may_not_clobber_the_loader_or_other_framework_files():
    ws = _ws()
    assert ws.is_write_allowed("app/backend/seed_data.py", "backend") is False
    assert ws.is_write_allowed("app/backend/main.py", "backend") is False
    assert ws.is_write_allowed("app/backend/models.py", "backend") is False


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
