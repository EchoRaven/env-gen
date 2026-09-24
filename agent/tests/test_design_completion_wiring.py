"""FIX #80 wiring — the orchestrator runs the deterministic completion pass on the ACCEPTED
design_system (agent or fallback path) before folding it into the requirements, so the doc's
crop/color/asset floor holds regardless of which path produced it. LOCAL-ONLY.
"""

import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def test_compile_reference_materials_runs_completion_on_accepted_ds():
    from multi_agent.orchestrator import Orchestrator
    src = inspect.getsource(Orchestrator._compile_reference_materials)
    assert "complete_design_system" in src
    # ordering: completion runs after acceptance, before the requirements fold
    accept = src.index("load_valid_design_system(dsp)")
    complete = src.index("complete_design_system(")
    fold = src.index("design_system_summary_for_requirements(ds)")
    assert accept < complete < fold
