r"""#737: a blackout cannot improve, so it manufactures the plateau that authorises the escape.

#75a refunds a wholesale blank capture, bounded by `_TRANSIENT_REFUND_CAP` so a genuinely blank
app cannot defer forever. That bound is right. What happens PAST the cap was not: the refund
branch stops returning, `capture_transient` is still True, and every screen arrives at 0.00. A
0.00 never beats its best-so-far, so `_improved` is False BY CONSTRUCTION and `plateau_rounds`
climbs once per blackout round. #138's escape then reads that as "the scores have flatlined".

r148, end to end, from its own log:

    11:13:19  10 of 12 screens blank -> refunded (transient 1/3)
    11:14:49  same 10 blank          -> refunded (transient 2/3)
    11:18:16  same 10 blank          -> refunded (transient 3/3)     cap exhausted
    ...five more blackout rounds, each incrementing plateau_rounds...
    11:36:46  deferral RELEASED (escape ... PLATEAU 5 no-improvement rounds - #138 early escape)
    11:36:47  FINAL DELIVERY: gate clear -> cut release v1.0.0

The app was genuinely broken, not the capture. The verifier independently filed
`TypeError: (void 0) is not a function` at 11:22:16, and FOUR P0 tasks were still open at the
cut — "All authenticated UI routes crash: '(void 0) is not a function' - empty #root", "SPA
crashes on ALL routes", "Frontend runtime crash on 12/14 pages", and "P0 REMEDIATION: ..."
whose description reads "DELIVERY IS BLOCKED BY THIS ONE BUG". The blackout was the truest
signal in the run and it was consumed as evidence of stability.

Corpus: 8 of 116 runs with a verdict.json end with blank>=2 or half their screens at 0.00.
r148 is NOT among them — #500's high-water merge had already erased its blackout from the
persisted record — so 7% is a floor, not an estimate.

Deliberately narrow. A blackout round neither increments nor resets the plateau, because it
carries no information either way. `total_judgments` and `last_judgment_at` still advance (a
blank capture still costs a vision call) and the wall-clock and total-judgment escapes still
bound the run: this removes a false accelerant, it does not add a way to hang.
"""
import asyncio
import inspect

import pytest

from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as VF
from env_generator.llm_generator.multi_agent.runtime.visual_fidelity import (
    VisualFidelityGate, _TRANSIENT_REFUND_CAP)


def _screen(name, sim, passed=None):
    return {"name": name, "route": "/" + name, "similarity": sim,
            "passed": (sim >= 0.65) if passed is None else passed,
            "dimensions": {}, "deviations": [], "advisory": False}


class _Logger:
    def __init__(self):
        self.lines = []

    def warning(self, msg, *a, **k):
        try:
            self.lines.append(str(msg) % a if a else str(msg))
        except Exception:
            self.lines.append(str(msg))

    def error(self, *a, **k):
        pass

    def info(self, *a, **k):
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


def _gate(tmp_path):
    orch = _Orch(tmp_path)
    g = VisualFidelityGate(orch)
    g._frontend_wiring_blockers = lambda: []      # skip the #417 wiring precondition
    return g, orch


def _drive(g, orch, monkeypatch, sig, screens, *, transient=False):
    orch._sig = sig

    async def _mock_run(project_dir, refs, llm, *, verdict_cache=None, **kwargs):
        return {"passed": False, "summary": "x", "screens": screens,
                "capture_transient": transient}

    monkeypatch.setattr(VF, "run_visual_fidelity", _mock_run)
    asyncio.run(g.maybe_run())


_LIVE = [_screen("browse_home", 0.72), _screen("my_list", 0.55)]
_BLACK = [_screen("browse_home", 0.0, passed=False), _screen("my_list", 0.0, passed=False)]


# --- the r148 sequence ------------------------------------------------------------------------

def test_r148s_sequence_no_longer_manufactures_a_plateau(tmp_path, monkeypatch):
    """Three refunded blackouts, then five more past the cap. Plateau used to reach 5."""
    g, orch = _gate(tmp_path)
    _drive(g, orch, monkeypatch, "s0", _LIVE)
    assert g.plateau_rounds == 0
    for i in range(_TRANSIENT_REFUND_CAP + 5):
        _drive(g, orch, monkeypatch, f"b{i}", _BLACK, transient=True)
    assert g.plateau_rounds == 0, (
        f"a blackout must not advance the escape counter (got {g.plateau_rounds})")


def test_the_old_behaviour_is_reproducible_in_this_harness(tmp_path, monkeypatch):
    """Non-vacuity: the fix must not pass by the harness never reaching the counter. The ONLY
    difference between the old code and the new one is the `capture_transient` branch, so
    driving the identical blackout screens with the flag OFF reproduces exactly what r148 did —
    five rounds of all-zero screens, plateau 5, which is the number in its escape line."""
    g, orch = _gate(tmp_path)
    _drive(g, orch, monkeypatch, "s0", _LIVE)
    for i in range(5):
        _drive(g, orch, monkeypatch, f"b{i}", _BLACK, transient=False)
    assert g.plateau_rounds == 5


def test_the_refund_cap_itself_is_unchanged(tmp_path, monkeypatch):
    """#75a's bound must still stop refunding — this fix is downstream of it, not a new refund."""
    g, orch = _gate(tmp_path)
    for i in range(_TRANSIENT_REFUND_CAP + 3):
        _drive(g, orch, monkeypatch, f"b{i}", _BLACK, transient=True)
    assert g.transient_refunds == _TRANSIENT_REFUND_CAP


def test_a_post_cap_blackout_is_still_judged(tmp_path, monkeypatch):
    """It must still reach remediation. Only the escape counter is held."""
    g, orch = _gate(tmp_path)
    for i in range(_TRANSIENT_REFUND_CAP + 2):
        _drive(g, orch, monkeypatch, f"b{i}", _BLACK, transient=True)
    assert g.total_judgments >= 2, "past the cap the round must be judged, not skipped"
    assert g.last_judgment_at is not None


def test_the_held_round_says_so(tmp_path, monkeypatch):
    g, orch = _gate(tmp_path)
    for i in range(_TRANSIENT_REFUND_CAP + 1):
        _drive(g, orch, monkeypatch, f"b{i}", _BLACK, transient=True)
    assert any("#737 blackout round does NOT count toward the plateau" in l
               for l in orch._logger.lines), orch._logger.lines[-3:]


# --- the plateau still works for everything else (the negative controls) -----------------------

def test_a_real_flatline_still_advances_the_plateau(tmp_path, monkeypatch):
    """The whole point of #138. A capture that RENDERS and does not improve must still count."""
    g, orch = _gate(tmp_path)
    _drive(g, orch, monkeypatch, "s0", _LIVE)
    for i in range(4):
        _drive(g, orch, monkeypatch, f"s{i+1}", _LIVE)
    assert g.plateau_rounds == 4


def test_a_genuine_improvement_still_rearms_it(tmp_path, monkeypatch):
    g, orch = _gate(tmp_path)
    _drive(g, orch, monkeypatch, "s0", _LIVE)
    _drive(g, orch, monkeypatch, "s1", _LIVE)
    assert g.plateau_rounds == 1
    _drive(g, orch, monkeypatch, "s2",
           [_screen("browse_home", 0.85), _screen("my_list", 0.55)])
    assert g.plateau_rounds == 0


def test_a_partial_blank_still_counts(tmp_path, monkeypatch):
    """#75a sets capture_transient=False for a partial blank — it carries real sibling
    verdicts, so it IS evidence and must be treated exactly as before."""
    g, orch = _gate(tmp_path)
    _drive(g, orch, monkeypatch, "s0", _LIVE)
    _drive(g, orch, monkeypatch, "s1",
           [_screen("browse_home", 0.0, passed=False), _screen("my_list", 0.55)],
           transient=False)
    assert g.plateau_rounds == 1


def test_a_blackout_does_not_reset_an_accumulated_plateau(tmp_path, monkeypatch):
    """It carries no information in EITHER direction — a run that really has flatlined must
    not have its escape reset by a capture glitch."""
    g, orch = _gate(tmp_path)
    _drive(g, orch, monkeypatch, "s0", _LIVE)
    for i in range(3):
        _drive(g, orch, monkeypatch, f"s{i+1}", _LIVE)
    assert g.plateau_rounds == 3
    _drive(g, orch, monkeypatch, "bx", _BLACK, transient=True)
    assert g.plateau_rounds == 3


def test_the_carried_bests_are_not_polluted_by_a_blackout(tmp_path, monkeypatch):
    g, orch = _gate(tmp_path)
    _drive(g, orch, monkeypatch, "s0", _LIVE)
    for i in range(_TRANSIENT_REFUND_CAP + 1):
        _drive(g, orch, monkeypatch, f"b{i}", _BLACK, transient=True)
    assert g._best_by_screen["browse_home"] == 0.72


# --- provenance -----------------------------------------------------------------------------

def _block() -> str:
    src = inspect.getsource(VisualFidelityGate.maybe_run)
    i = src.index("#737: A BLACKOUT CANNOT IMPROVE")
    return src[i:src.index("self.plateau_rounds = 0 if _improved", i)]


def test_the_mechanism_is_recorded():
    b = " ".join(_block().replace("#", " ").split())
    assert "_improved` is False by" in b and "construction" in b
    assert "climbs once per blackout round" in b


def test_the_r148_timeline_is_recorded():
    b = " ".join(_block().replace("#", " ").split())
    assert "11:18:16" in b and "cap exhausted" in b
    assert "PLATEAU 5 no-improvement rounds" in b
    assert "cut release v1.0.0" in b


def test_the_evidence_the_app_was_really_broken_is_recorded():
    """Without this the fix reads as 'silence a flaky capture', which is the opposite."""
    b = " ".join(_block().replace("#", " ").split())
    assert "(void 0) is not a function" in b
    assert "DELIVERY IS BLOCKED BY THIS ONE BUG" in b


def test_the_corpus_floor_is_recorded_as_a_floor():
    b = " ".join(_block().replace("#", " ").split())
    assert "8 of 116 runs" in b
    assert "a floor, not an estimate" in b


def test_it_records_that_it_cannot_hang_the_run():
    b = " ".join(_block().replace("#", " ").split())
    assert "removes a false accelerant, it does not add a way to hang" in b


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
