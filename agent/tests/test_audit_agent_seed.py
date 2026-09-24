"""The backend agent owns app/backend/seed_data.json but the prompt alone is a weak forcing
function: it may never author it (→ bland embedded _SEED fallback) or leave the framework
PLACEHOLDER titles (outlook seed1/seed2, 2026-06-29). audit_agent_seed detects both so the
framework can NUDGE the backend lane (soft — the fallback stays functional, never a hard
block).
"""

import json
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.backend_skeleton import audit_agent_seed  # noqa: E402


def _be(tmp_path, seed=None):
    be = tmp_path / "app" / "backend"
    be.mkdir(parents=True)
    if seed is not None:
        (be / "seed_data.json").write_text(json.dumps(seed), encoding="utf-8")
    return be


def test_absent_seed_flagged(tmp_path):
    res = audit_agent_seed(_be(tmp_path, seed=None))
    assert res["authored"] is False
    assert res["issues"] and "no app/backend/seed_data.json" in res["issues"][0]


def test_placeholder_seed_flagged(tmp_path):
    # the framework default titles the agent must NOT keep
    seed = {"messages": [{"subject": "Getting Started"}, {"subject": "Project Overview"}],
            "folders": [{"name": "Weekly Summary"}, {"name": "Team Update"}]}
    res = audit_agent_seed(_be(tmp_path, seed))
    assert res["authored"] is True
    assert set(res["placeholder_tables"]) == {"messages", "folders"}
    assert any("PLACEHOLDER" in i for i in res["issues"])


def test_realistic_seed_is_clean(tmp_path):
    seed = {"messages": [{"subject": "Re: Q3 budget review", "from_name": "Ava Chen"},
                         {"subject": "Your invoice #4021 is ready", "from_name": "Liam Patel"}],
            "folders": [{"name": "Inbox"}, {"name": "Archive"}]}
    res = audit_agent_seed(_be(tmp_path, seed))
    assert res["authored"] is True
    assert res["placeholder_tables"] == []
    assert res["issues"] == []


def test_minority_placeholder_not_flagged(tmp_path):
    # one placeholder among mostly-real rows shouldn't trip the table (>=half rule)
    seed = {"messages": [{"subject": "Re: lunch"}, {"subject": "Standup notes"},
                         {"subject": "Getting Started"}]}
    res = audit_agent_seed(_be(tmp_path, seed))
    assert res["placeholder_tables"] == []


def test_never_raises_on_garbage(tmp_path):
    be = tmp_path / "app" / "backend"
    be.mkdir(parents=True)
    (be / "seed_data.json").write_text("{not valid json", encoding="utf-8")
    res = audit_agent_seed(be)          # malformed → handled, not raised
    assert "authored" in res


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
