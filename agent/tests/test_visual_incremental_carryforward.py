"""visual-gate INCREMENTAL-PASS carry-forward — the phantom-0.00 is COSMETIC-ONLY.

GROUND TRUTH (run netflix-web-r97): the visual gate does incremental judging passes.
When a screen FAILS TO CAPTURE on a given pass (mid-rebuild render / auth-bounce), it
lands in that pass's in-memory results at similarity 0.00, and the one-line ``summary``
string persisted to design/visual_gate/verdict.json can therefore list e.g.
``browse_home(0.00)`` even though the SAME verdict.json's ``screens[browse_home].similarity``
still holds the real carried-forward score (0.72, passed:true). The summary self-heals on
the next FULL pass.

The load-bearing question was whether that phantom 0.00 feeds the RELEASE / delivery-defer
decision (which would make an incremental pass look like an avg crash → re-defer + re-judge
churn: the "attempt 1/3 on current source, N judged, re-judging now" grind). IT DOES NOT.
The decision paths all read the REAL, carried-forward per-screen score, never a phantom
zero-fill:

  * ``_visual_release_decision`` (the one function the delivery-defer path calls) takes NO
    per-screen / similarity / avg / summary argument at all — only scalar counters
    (deferred_since / attempts / total_judgments / plateau_rounds / last_judgment_at). A
    phantom 0.00 has no channel into it.
  * ``plateau_rounds`` is derived from ``VisualFidelityGate._best_by_screen``, a per-screen
    MAX-latch: a phantom 0.00 never lowers a screen's stored best and never counts as a
    (non-)improvement, so it can neither false-reset nor corrupt the plateau counter that
    feeds the escape.
  * ``_apply_sticky_pass`` (#129) latches a screen the round it clears the bar and never
    un-latches — a later phantom 0.00 cannot un-pass a screen or re-open the deferral.
  * ``_persist_verdict`` (#500 max-latch) carries each screen's real similarity forward in
    ``screens[]`` across an incremental phantom-0.00 pass — the diagnostic record the
    per-screen scores live in.

So the phantom 0.00 lives ONLY in the cosmetic ``summary`` string (which nothing gates on —
grep confirms verdict.json has zero readers and result["summary"] is used only for logging).
These tests LOCK that robustness so a future refactor can't accidentally wire the phantom
into the decision. NO production behavior is changed by adding them.

Run:
  PYTHONPATH=. ../.venv/bin/python -m pytest tests/test_visual_incremental_carryforward.py -q
"""
import asyncio
import inspect
import json
from pathlib import Path

from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as VF
from env_generator.llm_generator.multi_agent.runtime.visual_fidelity import (
    VisualFidelityGate, _apply_sticky_pass, _persist_verdict)
from env_generator.llm_generator.multi_agent.orchestrator import _visual_release_decision

MIN = 0.65


def _screen(name, sim, **kw):
    """A per-screen result dict shaped like run_visual_fidelity's output."""
    d = {"name": name, "route": "/" + name, "similarity": sim,
         "passed": sim >= MIN, "advisory": False, "empty_state": False,
         "blank": None, "dimensions": {}, "deviations": [], "fixes": [],
         "measured_deviations": [], "screenshot": None, "reference": None,
         "summary": ""}
    d.update(kw)
    return d


# ── 1. The delivery-defer decision cannot even SEE a per-screen score ──────────

def test_release_decision_takes_no_perscreen_score():
    # The one function the delivery-defer path (_visual_delivery_defer_active +
    # the deliver flow) calls. Its signature is the whole proof: no similarity /
    # avg / screen / summary parameter exists, so a phantom 0.00 has no channel in.
    params = set(inspect.signature(_visual_release_decision).parameters)
    for banned in ("similarity", "sim", "avg", "average", "score", "scores",
                   "screen", "screens", "summary"):
        assert banned not in params, (
            f"_visual_release_decision must not read a per-screen value; found {banned!r}")
    # it reads only scalar counters:
    assert {"deferred_since", "attempts", "total_judgments",
            "plateau_rounds", "last_judgment_at"} <= params


def test_release_decision_is_pure_in_its_scalars():
    # Same scalar state → same decision, regardless of anything a phantom pass could touch.
    now = 1_000_000.0
    kw = dict(deferred_since=now - 100.0, attempts=1, total_judgments=5,
              now=now, plateau_rounds=1, last_judgment_at=None)
    assert _visual_release_decision(**kw) == _visual_release_decision(**kw) == "defer"


# ── 2. Sticky pass (#129) never un-passes on a phantom-0.00 pass ───────────────

def test_sticky_pass_survives_a_phantom_zero_incremental_pass():
    latched: set = set()
    # pass 1 (full): browse_home clears the bar, my_list clears too → both latch
    assert _apply_sticky_pass(
        latched, [_screen("browse_home", 0.72), _screen("my_list", 0.70)]) is True
    assert latched == {"browse_home", "my_list"}
    # pass 2 (incremental): browse_home FAILED TO CAPTURE this pass → phantom 0.00.
    # The gate must stay satisfied — the phantom cannot re-open the deferral.
    assert _apply_sticky_pass(
        latched,
        [_screen("browse_home", 0.0, passed=False), _screen("my_list", 0.70)]) is True
    assert latched == {"browse_home", "my_list"}


# ── 3. Persisted per-screen record carries the REAL value forward, not 0.00 ────

def test_persisted_perscreen_carries_forward_real_value_not_zero(tmp_path):
    # pass 1 (full): real scores land
    _persist_verdict(tmp_path, passed=False, min_similarity=MIN,
                     summary="below 0.65: my_list(0.55)", coverage={},
                     results=[_screen("browse_home", 0.72), _screen("my_list", 0.55)])
    # pass 2 (incremental): browse_home failed to capture → 0.00 THIS pass; my_list re-judged
    _persist_verdict(tmp_path, passed=False, min_similarity=MIN,
                     summary="below 0.65: browse_home(0.00), my_list(0.55)", coverage={},
                     results=[_screen("browse_home", 0.0, passed=False),
                              _screen("my_list", 0.55)])
    data = json.loads((tmp_path / "design" / "visual_gate" / "verdict.json").read_text())
    by = {s["name"]: s for s in data["screens"]}
    # the decision-relevant per-screen record is the carried-forward REAL value, not the phantom
    assert by["browse_home"]["similarity"] == 0.72, by["browse_home"]
    assert by["my_list"]["similarity"] == 0.55


def test_summary_phantom_is_cosmetic_only_screens_hold_the_truth(tmp_path):
    # Reproduce the r97 symptom exactly: the persisted SUMMARY string names browse_home(0.00)
    # (latest-call verbatim, by design — see #500 test_merges_best_per_screen_not_overwrite_500)
    # while screens[browse_home].similarity carries the real 0.72. Lock that the DISCREPANCY is
    # confined to the cosmetic string; the structured per-screen record (what every decision
    # path reads) is correct.
    _persist_verdict(tmp_path, passed=True, min_similarity=MIN, summary="all screens ok",
                     coverage={}, results=[_screen("browse_home", 0.72)])
    _persist_verdict(tmp_path, passed=False, min_similarity=MIN,
                     summary="below 0.65: browse_home(0.00)", coverage={},
                     results=[_screen("browse_home", 0.0, passed=False)])
    data = json.loads((tmp_path / "design" / "visual_gate" / "verdict.json").read_text())
    by = {s["name"]: s for s in data["screens"]}
    assert "0.00" in data["summary"]                 # cosmetic phantom present in the string...
    assert by["browse_home"]["similarity"] == 0.72   # ...but the real per-screen record wins


# ── 4. A FULL pass is byte-identical to today (common case unchanged) ──────────

def test_full_pass_is_byte_identical(tmp_path):
    # Two FULL passes with all screens re-judged (monotonic, no capture failures) — the merged
    # screens[] equals what a single pass with the same scores writes. Nothing changes in the
    # common case; carry-forward only ever ADDS a prior value when a screen is missing/lower.
    full = [_screen("a", 0.70), _screen("b", 0.66), _screen("c", 0.68)]
    _persist_verdict(tmp_path, passed=True, min_similarity=MIN, summary="s1",
                     coverage={}, results=full)
    _persist_verdict(tmp_path, passed=True, min_similarity=MIN, summary="s2",
                     coverage={}, results=full)
    got = {s["name"]: s["similarity"]
           for s in json.loads(
               (tmp_path / "design" / "visual_gate" / "verdict.json").read_text())["screens"]}
    assert got == {"a": 0.70, "b": 0.66, "c": 0.68}


# ── 5. Plateau max-latch: driving the REAL gate proves churn-robustness ────────

class _Logger:
    def warning(self, *a, **k):
        pass

    def error(self, *a, **k):
        pass


class _WorkHub:
    def create_task(self, **k):
        return {"id": 1}


class _Hubs:
    workhub = _WorkHub()


class _Bus:
    async def send(self, msg):
        return None


class _Orch:
    def __init__(self, out):
        self._reference_images = [{"path": "ref.png"}]
        self.output_dir = out
        self.llm = object()
        self._logger = _Logger()
        self.hubs = _Hubs()
        self.message_bus = _Bus()
        self._sig = None

    def _compute_app_source_signature(self):
        return self._sig


def _drive(g, orch, monkeypatch, sig, screens, passed=False):
    """Run one real VisualFidelityGate.maybe_run pass with a mocked judge result."""
    orch._sig = sig

    async def _mock_run(project_dir, refs, llm, *, verdict_cache=None, **kwargs):
        # **kwargs tolerates run_visual_fidelity signature growth (e.g. #565's
        # milestone_owned_routes) so this mock stays valid as the real signature evolves.
        return {"passed": passed, "summary": "x", "screens": screens}

    monkeypatch.setattr(VF, "run_visual_fidelity", _mock_run)
    asyncio.run(g.maybe_run())


def test_plateau_maxlatch_robust_to_phantom_zero(tmp_path, monkeypatch):
    orch = _Orch(tmp_path)
    g = VisualFidelityGate(orch)
    g._frontend_wiring_blockers = lambda: []   # skip the wiring precondition (#417)

    # pass 1 (full): establish per-screen bests. my_list stays <MIN so the gate never passes.
    _drive(g, orch, monkeypatch, "s1",
           [_screen("browse_home", 0.72), _screen("my_list", 0.55)])
    assert g._best_by_screen == {"browse_home": 0.72, "my_list": 0.55}
    assert g.plateau_rounds == 0            # first real evidence is an improvement
    assert g.total_judgments == 1
    assert g.last_judgment_at is not None

    # pass 2 (INCREMENTAL): browse_home failed to capture → phantom 0.00 this pass.
    _drive(g, orch, monkeypatch, "s2",
           [_screen("browse_home", 0.0, passed=False), _screen("my_list", 0.55)])
    assert g._best_by_screen["browse_home"] == 0.72, "phantom 0.00 must NOT lower the carried best"
    assert g.plateau_rounds == 1, "phantom 0.00 must NOT false-reset plateau (no fake improvement)"

    # pass 3: browse_home recovers to the SAME value — not a real improvement, plateau advances.
    _drive(g, orch, monkeypatch, "s3",
           [_screen("browse_home", 0.72), _screen("my_list", 0.55)])
    assert g._best_by_screen["browse_home"] == 0.72
    assert g.plateau_rounds == 2, "recovery to the same score is not progress; escape stays on track"

    # pass 4: a GENUINE >epsilon improvement DOES re-arm the plateau (max-latch isn't blinded).
    _drive(g, orch, monkeypatch, "s4",
           [_screen("browse_home", 0.80), _screen("my_list", 0.55)])
    assert g._best_by_screen["browse_home"] == 0.80
    assert g.plateau_rounds == 0
    assert g.passed is False                # my_list never cleared MIN → gate correctly still open


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
