"""#1202nu: a visual pass latched in one milestone does not carry into the next one.

`VisualFidelityGate.passed` was cleared only when the app-source signature changed, and
`reset_for_milestone` reset the deferral clock and counters but not the pass latch or the per-source
judging budget. tiktok-r125: M3 passed at 10:06; at M3's delivery (10:59:42) the gate state was
written under the M4 key with passed=True and total_judgments=0; framework delivery only defers
while `not _vf_gate.passed`, so the FINAL milestone — the only one visual blocking applies to — cut
v1.3.0 at 11:57:52 with zero visual judgments.
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.visual_fidelity import VisualFidelityGate  # noqa: E402

M3 = "milestone:3:M3-live-discover@1.2.0"
M4 = "milestone:4:M4-account-utility-surfaces@1.3.0"


def _gate(tmp_path):
    orch = SimpleNamespace(output_dir=str(tmp_path), _logger=SimpleNamespace(
        warning=lambda *a, **k: None, info=lambda *a, **k: None, debug=lambda *a, **k: None))
    return VisualFidelityGate(orch)


def _passed_m3(tmp_path):
    g = _gate(tmp_path)
    g.reset_for_milestone(M3)
    g.passed, g.attempts, g.sig, g.last_judged_sig = True, 1, "sigA", "sigA"
    return g


def test_r125_advancing_to_the_next_milestone_clears_the_pass(tmp_path):
    g = _passed_m3(tmp_path)
    g.reset_for_milestone(M4)
    assert g.passed is False and g.attempts == 0
    assert g.sig is None and g.last_judged_sig is None
    state = json.loads((tmp_path / "design" / "visual_gate" / g._STATE_FILE_1202CE).read_text())
    assert state["_milestone_key_1202ce"] == M4 and state["passed"] is False


def test_re_entering_the_same_milestone_keeps_its_pass(tmp_path):
    g = _passed_m3(tmp_path)
    g.reset_for_milestone(M3)
    assert g.passed is True and g.attempts == 1


def test_a_resume_into_a_milestone_restores_its_own_saved_pass(tmp_path):
    g = _passed_m3(tmp_path)
    g._save_state_1202ce()
    fresh = _gate(tmp_path)
    fresh.reset_for_milestone(M3)
    assert fresh.passed is True
