import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # agent/
SRC = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(SRC)):
    if p not in sys.path:
        sys.path.insert(0, p)

from multi_agent.agents.configurable_agent import get_agent_config  # noqa: E402
from multi_agent.runtime.reasoning_effort import normalize_effort  # noqa: E402


def _eff(agent_id):
    return normalize_effort(get_agent_config(agent_id).get("reasoning_effort"))


def test_profile_reasoning_effort_defaults():
    assert _eff("orchestrator") == "high"
    assert _eff("frontend") == "high"
    assert _eff("debugger") == "high"
    assert _eff("knowledge") == "low"
    # Round-8h Fix #M (2026-06-03): backend + verifier promoted from
    # default medium to explicit high after smoke #9-nonus / #9-decimus
    # caught both lazying out of kickoff revisions (tool-availability
    # hallucinations + under-coverage on predicate enumeration). Both
    # own reasoning-heavy contract-authoring + cross-team alignment
    # responsibilities; medium was undershooting.
    assert _eff("backend") == "high"
    assert _eff("verifier") == "high"
