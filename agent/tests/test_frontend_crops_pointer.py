"""FIX #87 — the frontend prompt must point lanes at the per-component PHYSICAL CROPS.

FIX #80 guarantees design/crops/<screen>__<component>.png exists for every component (98-113
per run, live), and design_system.json components[].crop carries each path — but NOTHING in
any lane prompt referenced them: the tool ritual pointed only at component_specs JSON numbers
and whole-screen references. A cropped close-up is the manual's §2 core loop (crop → view →
build); un-referenced crops are dead weight. LOCAL-ONLY (agent/tests/ gitignored).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

_J2 = LLM / "multi_agent" / "prompts" / "v3" / "frontend_agent.j2"


def test_frontend_prompt_points_at_precut_component_crops():
    src = _J2.read_text(encoding="utf-8")
    assert "design/crops/" in src
    # the pointer must tie the crop to the component build loop (view before build),
    # not just name the directory
    lowered = src.lower()
    idx = lowered.index("design/crops/")
    window = lowered[max(0, idx - 600):idx + 600]
    assert "view_image" in window
    assert "crop" in window
