"""#558 (netflix r95/r103/r107, 2026-08-07) — VISUAL AVG FAST-RELEASE.

GROUND TRUTH: the visual gate's clean pass requires EVERY blocking screen ≥ the 0.65 bar
(all-pass). A run whose gating blocking_average (#542, BLOCKING screens only) is comfortably
≥ the bar (r107 = 0.7258) while a couple of screens lag (~0.50-0.60) is NOT a clean pass, so
it DEFERS — and because the per-source attempt counter resets on frontend source-churn the
fast escapes never fire, it grinds to the 3600s wall-clock escape (~40 wasted re-judgements,
~40-60 min), then RELEASES the SAME app anyway. FIX #558 adds a FAST path to that EXACT
release: a run whose blocking_average has cleared the bar for N consecutive judged rounds
(STABLE) with a complete blocking exam (coverage_ok) releases promptly. It reuses the same
per-milestone round tracking (like plateau_rounds) and the #521 sticky-release latch.

These tests lock:
  * fast-release FIRES when blocking_average ≥ min for N stable rounds AND coverage ok;
  * it does NOT fire when avg < min, when avg ≥ min for only 1 round, or coverage insufficient;
  * it reuses the same round tracking (avg_pass_rounds increments across churn, resets below min);
  * the args helper reads the gate's last_result / coverage precondition correctly;
  * the wall-clock / plateau / attempts escapes still release when the avg stays < min;
  * disabled via env (avg_release=False) → OLD behavior, BYTE-IDENTICAL;
  * the all-pass clean-pass fast-path is untouched (the block is entered only while NOT passed
    AND NOT released, exactly like #521).

Run from agent/:
  PYTHONPATH=. ../.venv/bin/python -m pytest tests/test_visual_avg_fast_release_558.py -q
"""
import asyncio
import sys
import types
from pathlib import Path

from env_generator.llm_generator.multi_agent.orchestrator import (
    _visual_release_decision, _visual_fast_release_args,
    VISUAL_AVG_RELEASE, VISUAL_AVG_RELEASE_ROUNDS,
    VISUAL_PLATEAU_ROUNDS, VISUAL_PLATEAU_MIN_S, VISUAL_DEFERRAL_ESCAPE_S,
    VISUAL_TOTAL_JUDGMENTS_CAP)
from env_generator.llm_generator.multi_agent.runtime.visual_fidelity import (
    VisualFidelityGate)

NOW = 1_000_000.0
MIN = 0.65


# ── (a) the pure decision function — fast-release conditions ────────────────────────────────

def _decide(**kw):
    """All-quiet baseline (nothing else can release): deferred 100s (below the 1500s plateau
    floor and the 3600s wall-clock), no attempts/judgments/plateau. Only fast-release can fire."""
    base = dict(deferred_since=NOW - 100.0, attempts=0, total_judgments=0, now=NOW,
                plateau_rounds=0, last_judgment_at=None,
                blocking_average=None, avg_min=None, avg_stable_rounds=0, coverage_ok=False)
    base.update(kw)
    return _visual_release_decision(**base)


def test_defaults_are_safe():
    assert VISUAL_AVG_RELEASE is True                 # default ON
    assert VISUAL_AVG_RELEASE_ROUNDS == 2             # needs 2 stable rounds


def test_fast_release_FIRES_when_avg_stable_and_coverage_ok():
    # the r107 case: avg 0.7258 ≥ 0.65 for 2 stable rounds, blocking exam complete
    d = _decide(blocking_average=0.7258, avg_min=MIN, avg_stable_rounds=2, coverage_ok=True)
    assert d == "fast_release", d


def test_fast_release_at_exact_threshold_and_exact_rounds():
    # ≥ is inclusive on BOTH the bar and the round count
    assert _decide(blocking_average=MIN, avg_min=MIN, avg_stable_rounds=2,
                   coverage_ok=True) == "fast_release"
    assert _decide(blocking_average=0.90, avg_min=MIN,
                   avg_stable_rounds=VISUAL_AVG_RELEASE_ROUNDS,
                   coverage_ok=True) == "fast_release"


def test_does_NOT_fire_when_avg_below_min():
    # avg below the bar → NOT a fast-release (and nothing else tripped → defer)
    assert _decide(blocking_average=0.60, avg_min=MIN, avg_stable_rounds=5,
                   coverage_ok=True) == "defer"
    # a whisker below still won't ship a below-threshold app
    assert _decide(blocking_average=0.649, avg_min=MIN, avg_stable_rounds=9,
                   coverage_ok=True) == "defer"


def test_does_NOT_fire_when_only_one_stable_round():
    # a single lucky pass must not trigger it (needs N=2)
    assert _decide(blocking_average=0.80, avg_min=MIN, avg_stable_rounds=1,
                   coverage_ok=True) == "defer"


def test_does_NOT_fire_when_coverage_insufficient():
    # avg ≥ min for many rounds but the blocking exam was NOT complete → do not release early
    assert _decide(blocking_average=0.80, avg_min=MIN, avg_stable_rounds=5,
                   coverage_ok=False) == "defer"


def test_disabled_via_env_flag_is_byte_identical():
    # avg_release=False → the fast-release branch is inert; the decision equals the OLD one
    # (no fast-release args) for every state that would otherwise fast-release AND for escapes.
    states = [
        dict(),                                                   # all-quiet
        dict(attempts=3),                                         # per-source cap escape
        dict(total_judgments=VISUAL_TOTAL_JUDGMENTS_CAP),         # judgment cap escape
        dict(deferred_since=NOW - (VISUAL_DEFERRAL_ESCAPE_S + 1)),  # wall-clock escape
    ]
    for extra in states:
        disabled = _decide(blocking_average=0.90, avg_min=MIN, avg_stable_rounds=9,
                           coverage_ok=True, avg_release=False, **extra)
        old_base = dict(deferred_since=NOW - 100.0, attempts=0, total_judgments=0, now=NOW,
                        plateau_rounds=0, last_judgment_at=None)
        old_base.update(extra)                       # the OLD signature: no fast-release args
        old = _visual_release_decision(**old_base)
        assert disabled == old, (extra, disabled, old)
        assert disabled != "fast_release"


def test_custom_round_threshold_env():
    # ENVGEN_VISUAL_AVG_RELEASE_ROUNDS=3 → 2 stable rounds is NOT enough, 3 is
    assert _decide(blocking_average=0.80, avg_min=MIN, avg_stable_rounds=2,
                   avg_release_rounds=3, coverage_ok=True) == "defer"
    assert _decide(blocking_average=0.80, avg_min=MIN, avg_stable_rounds=3,
                   avg_release_rounds=3, coverage_ok=True) == "fast_release"


# ── (b) fast-release pre-empts the wall-clock grind (the whole point) ───────────────────────

def test_fast_release_preempts_the_wallclock_escape():
    # when BOTH the wall-clock escape AND fast-release conditions hold, the DISTINCT
    # fast-release verdict wins (so the caller logs the fast-release line, not the escape).
    d = _decide(deferred_since=NOW - (VISUAL_DEFERRAL_ESCAPE_S + 1),
                blocking_average=0.75, avg_min=MIN, avg_stable_rounds=2, coverage_ok=True)
    assert d == "fast_release", d


def test_escapes_still_release_when_avg_stays_below_min():
    # the recurring wedge: avg is BELOW the bar, so fast-release never fires, but every
    # existing escape must STILL release (no deadlock) — unchanged from #519.
    lo = dict(blocking_average=0.50, avg_min=MIN, avg_stable_rounds=9, coverage_ok=True)
    assert _decide(attempts=3, **lo) == "release"                                   # per-source cap
    assert _decide(total_judgments=VISUAL_TOTAL_JUDGMENTS_CAP, **lo) == "release"   # judgment cap
    assert _decide(deferred_since=NOW - (VISUAL_DEFERRAL_ESCAPE_S + 1), **lo) == "release"  # wall-clock
    # soft plateau above the floor
    assert _decide(plateau_rounds=VISUAL_PLATEAU_ROUNDS,
                   deferred_since=NOW - (VISUAL_PLATEAU_MIN_S + 50.0), **lo) == "release"
    # and with a below-min avg, all-quiet still defers (lane keeps iterating)
    assert _decide(**lo) == "defer"


# ── (c) the args helper reads the gate's last judged result + coverage precondition ─────────

def _gate_with(last_result, avg_pass_rounds=0):
    g = VisualFidelityGate(None)
    g.last_result = last_result
    g.avg_pass_rounds = avg_pass_rounds
    return g


def test_args_helper_extracts_avg_min_rounds_and_coverage():
    g = _gate_with(
        {"blocking_average": 0.7258, "min_similarity": 0.65,
         "coverage": {"blocking_judged": 3, "unjudged": []}},
        avg_pass_rounds=2)
    args = _visual_fast_release_args(g)
    # #750 added `app_dead` to this dict, so both call sites get the veto for free by
    # splatting it. Exact-equality is kept deliberately — it is what caught the addition.
    # #1140 added `any_screen_at_bar` the same way #750 added `app_dead`: this dict is the
    # shared kwargs channel and both call sites splat it, so a new floor must arrive here or
    # the defer-check and the deliver block would disagree.
    assert args == {"blocking_average": 0.7258, "avg_min": 0.65,
                    "avg_stable_rounds": 2, "coverage_ok": True,
                    "app_dead": False, "any_screen_at_bar": True}, args


def test_args_helper_coverage_ok_requires_a_blocking_screen():
    # zero blocking screens judged → NOT a complete exam → coverage_ok False
    g = _gate_with({"blocking_average": 0.9, "min_similarity": 0.65,
                    "coverage": {"blocking_judged": 0, "unjudged": ["x"]}})
    assert _visual_fast_release_args(g)["coverage_ok"] is False


def test_args_helper_safe_when_no_last_result():
    g = VisualFidelityGate(None)
    assert _visual_fast_release_args(g) == {
        "blocking_average": None, "avg_min": None,
        "avg_stable_rounds": 0, "coverage_ok": False,
        "app_dead": False,      # #750: a fresh gate has never seen a blackout
        # #1140: no last_result => nothing judged => unknown, and unknown never floors.
        "any_screen_at_bar": True}


def test_end_to_end_gate_state_fast_releases():
    # the exact plumbing the deliver block uses: gate.last_result + gate.avg_pass_rounds →
    # _visual_fast_release_args → _visual_release_decision → fast_release.
    g = _gate_with(
        {"blocking_average": 0.7258, "min_similarity": 0.65,
         "coverage": {"blocking_judged": 4, "unjudged": []}},
        avg_pass_rounds=2)
    d = _visual_release_decision(
        NOW - 100.0, g.attempts, g.total_judgments, NOW,
        plateau_rounds=g.plateau_rounds, last_judgment_at=g.last_judgment_at,
        **_visual_fast_release_args(g))
    assert d == "fast_release", d
    # one stable round is not enough even with the same good average
    g.avg_pass_rounds = 1
    d1 = _visual_release_decision(
        NOW - 100.0, g.attempts, g.total_judgments, NOW,
        plateau_rounds=g.plateau_rounds, last_judgment_at=g.last_judgment_at,
        **_visual_fast_release_args(g))
    assert d1 == "defer", d1


# ── (d) gate field default + per-milestone reset (mirrors #521) ─────────────────────────────

def test_avg_pass_rounds_defaults_zero_and_resets_per_milestone():
    g = VisualFidelityGate(None)
    assert g.avg_pass_rounds == 0
    g.avg_pass_rounds = 4
    g.reset_for_milestone()
    assert g.avg_pass_rounds == 0


def test_clean_pass_and_sticky_short_circuit_the_block():
    # the all-pass clean-pass fast-path is UNTOUCHED: the deliver block is entered only while
    # NOT passed AND NOT released (identical guard to #521), so a clean pass never reaches the
    # fast-release/escape decision at all.
    def _enter_block(gate):
        return (not gate.passed) and (not getattr(gate, "released", False))
    g = VisualFidelityGate(None)
    assert _enter_block(g) is True
    g.passed = True                       # all-pass clean pass → block skipped entirely
    assert _enter_block(g) is False
    g.passed = False
    g.released = True                     # #521 sticky (incl. a prior fast-release) → skipped
    assert _enter_block(g) is False


# ── (e) maybe_run tracks the STABLE round count across source churn ─────────────────────────
# Isolation harness (mirrors test_visual_gate_determinism_542): exec the module under a synthetic
# package with only validation_runner stubbed, then monkeypatch run_visual_fidelity so we can feed
# a controlled blocking_average sequence WITHOUT booting docker or calling a real judge.

_SRC = (Path(__file__).resolve().parents[1] / "env_generator" / "llm_generator"
        / "multi_agent" / "runtime" / "visual_fidelity.py")


def _load_vf():
    pkg = types.ModuleType("vf558_pkg")
    pkg.__path__ = []
    vr = types.ModuleType("vf558_pkg.validation_runner")
    vr._service_host_port = lambda *a, **k: None
    sys.modules["vf558_pkg"] = pkg
    import env_generator.llm_generator.multi_agent.runtime.message_format as _mf1034
    sys.modules["vf558_pkg.message_format"] = _mf1034  # #1034: leaf helper, no deps
    sys.modules["vf558_pkg.validation_runner"] = vr
    mod = types.ModuleType("vf558_pkg.visual_fidelity")
    mod.__package__ = "vf558_pkg"
    exec(compile(_SRC.read_text(encoding="utf-8"), str(_SRC), "exec"), mod.__dict__)
    return mod


class _Log:
    def warning(self, *a, **k):
        pass

    def error(self, *a, **k):
        pass


class _Hub:
    def create_task(self, **kw):
        return {"id": "t1"}


class _Hubs:
    workhub = _Hub()


class _Bus:
    async def send(self, msg):
        return None


class _Orch:
    """Minimal orchestrator collaborator for VisualFidelityGate.maybe_run. Each call yields a
    FRESH source signature (simulating the r107 lane churn that resets the per-source attempt
    cap) so the gate re-judges every round; avg_pass_rounds must survive that churn."""
    def __init__(self, tmp):
        self._reference_images = [str(Path(tmp) / "ref.png")]
        Path(self._reference_images[0]).write_bytes(b"\x89PNG\r\n")
        self.output_dir = str(tmp)
        self.hubs = _Hubs()
        self.message_bus = _Bus()
        self._logger = _Log()
        self.llm = object()
        self._n = 0

    def _compute_app_source_signature(self):
        self._n += 1
        return f"sig-{self._n}"           # a NEW signature every round (churn)


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _result(avg):
    """A judged result that is NOT an all-pass (one blocking screen always lags), so passed
    stays False — the exact #558 shape — but carries the given gating blocking_average."""
    return {
        "passed": False,
        "summary": "test",
        "min_similarity": 0.65,
        "blocking_average": avg,
        "coverage": {"measured": 2, "judged": 2, "blocking_judged": 2, "unjudged": [],
                     "coverage": 1.0},
        "screens": [
            {"name": "good", "route": "/g", "similarity": 0.90, "passed": True, "advisory": False},
            {"name": "laggard", "route": "/l", "similarity": 0.55, "passed": False, "advisory": False},
        ],
    }


def test_maybe_run_tracks_stable_rounds_and_resets_below_min(tmp_path):
    mod = _load_vf()
    orch = _Orch(tmp_path)
    gate = mod.VisualFidelityGate(orch)

    seq = iter([0.72, 0.71, 0.50, 0.80, 0.90])   # ≥.65, ≥.65, <.65, ≥.65, ≥.65
    calls = {"n": 0}

    async def _fake_run(*a, **k):
        calls["n"] += 1
        return _result(next(seq))

    mod.run_visual_fidelity = _fake_run

    _run(gate.maybe_run()); assert gate.avg_pass_rounds == 1   # 0.72 ≥ min
    _run(gate.maybe_run()); assert gate.avg_pass_rounds == 2   # 0.71 ≥ min (2 stable across churn)
    _run(gate.maybe_run()); assert gate.avg_pass_rounds == 0   # 0.50 < min → reset
    _run(gate.maybe_run()); assert gate.avg_pass_rounds == 1   # 0.80 ≥ min
    _run(gate.maybe_run()); assert gate.avg_pass_rounds == 2   # 0.90 ≥ min
    assert gate.total_judgments == 5 and calls["n"] == 5
    assert gate.passed is False                                # never an all-pass (laggard 0.55)

    # and at 2 stable rounds the wired decision fast-releases (with the block's real inputs)
    from env_generator.llm_generator.multi_agent.orchestrator import (
        _visual_release_decision as _dec, _visual_fast_release_args as _fra)
    assert _dec(NOW - 100.0, gate.attempts, gate.total_judgments, NOW,
                plateau_rounds=gate.plateau_rounds, last_judgment_at=gate.last_judgment_at,
                **_fra(gate)) == "fast_release"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
