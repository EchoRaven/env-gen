"""Frontend reference-screenshot read tools must reach the edit_code surface.

frontend_agent.j2 mandates the lane "inspect them via view_image() and produce a
visual_reference_analysis section ... list_reference_images ONCE in Phase A, then
view_image() for every path — never guess the UI from memory" while authoring
src/pages/*.jsx. But view_image / list_reference_images live in the "file" tool
category (tools.py: _assemble_agent_tool_pool) and were NOT force-offered in
edit_code, so the per-step ranker (truncates to ~10 over ~150 tools) crowded them
out: youtube run #20 AND outlook run #1 both show the frontend lane calling
view_image ZERO times across the whole run (and pleading "I am missing ... view_image"
to the orchestrator). It never once saw the references it was told to match — every
projected page was a generic fallback. Same crowd-out class as _CONTRACT_READ.

Force-offer them in edit_code (the build stage); bundle-intersection means only lanes
that bundle them (frontend) ever see them. LOCAL-ONLY (agent/tests/ gitignored).
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.agents.base import EnvGenAgent  # noqa: E402

_REFERENCE_VIEW_TOOLS = ("view_image", "list_reference_images")


def test_reference_view_set_defined():
    rv = EnvGenAgent._REFERENCE_VIEW
    for t in _REFERENCE_VIEW_TOOLS:
        assert t in rv, f"{t} missing from _REFERENCE_VIEW"


@pytest.mark.parametrize("tool", _REFERENCE_VIEW_TOOLS)
def test_edit_code_offers_reference_view(tool):
    """edit_code is where the frontend authors pages; it MUST be able to look at
    the reference screenshots in the SAME step (view-then-author) instead of
    guessing the UI from memory."""
    always = EnvGenAgent.ACTION_STAGE_ALWAYS_INCLUDE["edit_code"]
    assert tool in always, (
        f"{tool} must be force-offered in edit_code so the frontend lane can "
        f"inspect the references it is told to match while building pages, "
        f"instead of pleading 'I am missing view_image' to the orchestrator."
    )


def test_reference_view_not_leaked_to_run_checks():
    # The view tools belong to the build stage, not validation — keep the surface tight.
    always = EnvGenAgent.ACTION_STAGE_ALWAYS_INCLUDE["run_checks"]
    for t in _REFERENCE_VIEW_TOOLS:
        assert t not in always


def test_write_tools_still_present_in_edit_code():
    # regression guard: the view additions must not displace the write tools.
    always = EnvGenAgent.ACTION_STAGE_ALWAYS_INCLUDE["edit_code"]
    for t in ("read", "write", "edit", "apply_patch"):
        assert t in always


if __name__ == "__main__":
    import pytest as _p
    raise SystemExit(_p.main([__file__, "-q"]))
