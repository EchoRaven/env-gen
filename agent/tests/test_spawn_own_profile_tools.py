"""A spawned agent with its OWN explicit profile (config_key) distinct from its parent must use
THAT profile's tool categories/bundles/vision — NOT inherit the parent's. Regression for the bug
where the orchestrator-spawned design_analyst inherited the orchestrator's categories (no
reference/vision) and silently lost ALL its measurement tools. LOCAL-ONLY (agent/tests/ gitignored).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _effective_categories(spawn_config_key, parent_key, parent_categories, profile_categories):
    """Mirror the gate in agent_spawn_service.spawn(): inherit the parent's categories UNLESS the
    spawn names its own distinct profile, in which case use that profile's own categories."""
    inherited = list(parent_categories) if parent_categories else None
    if spawn_config_key and spawn_config_key != parent_key:
        inherited = None
    return inherited or profile_categories


def test_own_profile_spawn_keeps_its_reference_vision_categories():
    from multi_agent.agents.configurable_agent import get_agent_config
    da = get_agent_config("design_analyst")
    orch_cats = ["file", "reasoning", "api", "browser", "verification"]   # orchestrator-ish, NO reference/vision
    cats = _effective_categories("design_analyst", "orchestrator", orch_cats, da["tool_categories"])
    assert "reference" in cats and "vision" in cats, cats   # its measurement tools survive


def test_same_type_helper_still_inherits():
    # a helper spawned with NO distinct profile (config_key == parent's type) inherits, as before
    cats = _effective_categories("orchestrator", "orchestrator", ["file", "reasoning"], ["file", "reasoning"])
    assert cats == ["file", "reasoning"]


def test_design_analyst_tool_pool_has_measurement_tools_under_its_own_categories():
    # the deciding assertion: with the design_analyst profile's OWN categories, the measurement
    # tools actually assemble (they were filtered out under the orchestrator's categories).
    import tempfile
    from multi_agent.agents.configurable_agent import get_agent_config
    from multi_agent.agents.runtime.tooling import create_tool_assembly_context
    from multi_agent.tools import assemble_tool_pool
    from workspace import Workspace

    da = get_agent_config("design_analyst")

    class _LLM:
        async def chat(self, *a, **k):
            return None

    ws = Workspace(tempfile.mkdtemp())

    def names(cats):
        ctx = create_tool_assembly_context(
            agent_type="design_analyst", agent_id="da1", workspace=ws,
            include_vision=True, llm_client=_LLM(), allowed_tool_categories=cats,
            tool_profile_id="design_analyst", tool_bundle_ids=da.get("tool_bundles", []))
        return {getattr(t, "NAME", getattr(t, "name", "?")) for t in assemble_tool_pool(ctx)}

    MEAS = {"sample_color", "crop_reference", "measure_layout", "decompose_reference",
            "extract_palette", "zoom_compare"}
    # under the orchestrator's categories (no reference/vision) → measurement tools are LOST
    orch = names(["file", "reasoning", "api", "browser", "verification"])
    assert not (MEAS & orch), f"unexpectedly present under orchestrator cats: {MEAS & orch}"
    # under its OWN profile categories → all present
    own = names(da["tool_categories"])
    assert MEAS <= own, f"missing under own cats: {MEAS - own}"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
