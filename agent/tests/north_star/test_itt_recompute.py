"""Pilot ITT + asymmetry-gate recompute tests (B-8 / §5.1 backstop).

Pins the data-shape contract for compute_itt_delta() and the JSONL sink so
the spec freeze can't lock in an unproducible measurement apparatus.

Run: cd agent && /home/haibotong/miniconda3/envs/dt/bin/python -m pytest \
       tests/north_star/test_itt_recompute.py --confcutdir=tests/north_star -v
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_THIS = Path(__file__).resolve()
_NORTH_STAR_DIR = _THIS.parent
if str(_NORTH_STAR_DIR) not in sys.path:
    sys.path.insert(0, str(_NORTH_STAR_DIR))

from classifier import (  # noqa: E402
    Verdict,
    FailureContext,
    classify,
    synthesize_pass_verdict,
    append_to_sink,
    read_sink,
    compute_itt_delta,
    ASYMMETRY_REL_X,
    ASYMMETRY_ABS_PP,
)


SPEC_SECTION_2_FIELDS = {
    "run_id",
    "spec_id",
    "arm",
    "phase_reached",
    "outcome",
    "verdict",
    "matched_signature",
    "raw_evidence",
    "negative_guard_evidence",
    "retry_count",
    "classifier_spec_sha",
}


def _write(sink: Path, arm: str, outcome: str, verdict: str = "functional",
           matched_signature: str = None):
    """Append one Verdict to the JSONL sink with the given outcome/verdict."""
    if outcome == "pass":
        v = synthesize_pass_verdict(
            run_id=f"r-{arm}-{os.urandom(4).hex()}",
            spec_id="simple_blog",
            arm=arm,
        )
    else:
        v = Verdict(
            verdict=verdict,
            run_id=f"r-{arm}-{os.urandom(4).hex()}",
            spec_id="simple_blog",
            arm=arm,
            phase_reached="app_build",
            outcome="fail",
            matched_signature=matched_signature,
            raw_evidence="synthetic",
            negative_guard_evidence="synthetic",
        )
    append_to_sink(v, sink)


# ---------------------------------------------------------------------------
# Schema-shape coverage (V31 in the D4 design)
# ---------------------------------------------------------------------------


def test_verdict_to_dict_matches_spec_section_2_schema():
    v = Verdict(
        verdict="env",
        run_id="x",
        spec_id="simple_blog",
        arm="ab_new",
        phase_reached="app_build",
        outcome="fail",
        matched_signature="env.oom",
        raw_evidence="e",
        negative_guard_evidence="g",
    )
    assert set(v.to_dict().keys()) == SPEC_SECTION_2_FIELDS


def test_classify_populates_section_2_fields_from_failure_context():
    ctx = FailureContext(
        run_id="rid-2",
        spec_id="simple_blog",
        arm="ab_new",
        phase_reached="app_build",
        outcome="fail",
        build_stderr="completely unmatched",
    )
    v = classify(ctx)
    d = v.to_dict()
    assert d["run_id"] == "rid-2"
    assert d["spec_id"] == "simple_blog"
    assert d["arm"] == "ab_new"
    assert d["phase_reached"] == "app_build"
    assert d["outcome"] == "fail"


# ---------------------------------------------------------------------------
# Sink round-trip (V33 in the D4 design)
# ---------------------------------------------------------------------------


def test_sink_roundtrip_one_line_per_verdict(tmp_path):
    sink = tmp_path / "v.jsonl"
    v = Verdict(
        verdict="functional",
        run_id="r1",
        spec_id="simple_blog",
        arm="ab_new",
        phase_reached="app_build",
        outcome="fail",
    )
    append_to_sink(v, sink)
    append_to_sink(v, sink)
    rows = list(read_sink(sink))
    assert len(rows) == 2
    assert all(set(r.keys()) == SPEC_SECTION_2_FIELDS for r in rows)


def test_sink_round_trip_pass_and_fail_mix(tmp_path):
    sink = tmp_path / "v.jsonl"
    _write(sink, "ab_old", "pass")
    _write(sink, "ab_old", "fail", "functional")
    _write(sink, "ab_new", "fail", "env", matched_signature="env.oom")
    rows = list(read_sink(sink))
    assert len(rows) == 3
    outcomes = [r["outcome"] for r in rows]
    assert outcomes.count("pass") == 1
    assert outcomes.count("fail") == 2


# ---------------------------------------------------------------------------
# §5.1 ITT + asymmetry-gate behaviour
# ---------------------------------------------------------------------------


def test_itt_no_advantage_neither_arm(tmp_path):
    """V32 control: identical pass-rates on both arms → delta = 0, not blocked."""
    sink = tmp_path / "v.jsonl"
    for _ in range(10):
        _write(sink, "ab_old", "pass")
    for _ in range(10):
        _write(sink, "ab_new", "pass")
    r = compute_itt_delta(sink, "ab_old", "ab_new")
    assert r["as_classified"]["delta_pp"] == 0.0
    assert r["itt"]["delta_pp"] == 0.0
    assert not r["blocked"]


def test_itt_advantage_survives_when_no_exclusions(tmp_path):
    """ab_old: 5/10 = 50%; ab_new: 8/10 = 80%; ZERO env exclusions either arm.
    As-classified and ITT agree (no exclusions to count against either)."""
    sink = tmp_path / "v.jsonl"
    for _ in range(5):
        _write(sink, "ab_old", "pass")
    for _ in range(5):
        _write(sink, "ab_old", "fail", "functional")
    for _ in range(8):
        _write(sink, "ab_new", "pass")
    for _ in range(2):
        _write(sink, "ab_new", "fail", "functional")
    r = compute_itt_delta(sink, "ab_old", "ab_new")
    assert r["as_classified"]["delta_pp"] == pytest.approx(30.0)
    assert r["itt"]["delta_pp"] == pytest.approx(30.0)
    assert not r["blocked"]


def test_itt_advantage_does_not_survive_blocked_by_asymmetry(tmp_path):
    """V29 (D4) decisive backstop:
      ab_old:  5 pass + 5 functional fail = 50% as-classified AND ITT
      ab_new:  5 pass + 1 functional fail + 4 env-excluded
        as-classified: 5/(10-4) = 83.3% — looks like ~33pp win
        ITT (count exclusions as fails): 5/10 = 50% — advantage evaporates
        asymmetry: 40pp exclusion gap → BLOCKED
    The new arm cannot manufacture a win the ITT recompute does not show."""
    sink = tmp_path / "v.jsonl"
    for _ in range(5):
        _write(sink, "ab_old", "pass")
    for _ in range(5):
        _write(sink, "ab_old", "fail", "functional")
    for _ in range(5):
        _write(sink, "ab_new", "pass")
    for _ in range(1):
        _write(sink, "ab_new", "fail", "functional")
    for _ in range(4):
        _write(sink, "ab_new", "fail", "env", matched_signature="env.oom")
    r = compute_itt_delta(sink, "ab_old", "ab_new")
    assert r["as_classified"]["delta_pp"] > 25.0
    assert r["itt"]["delta_pp"] == pytest.approx(0.0, abs=0.01)
    assert r["asymmetry"]["triggered"]
    assert r["blocked"]


def test_itt_asymmetry_trigger_blocks_on_small_gap(tmp_path):
    """V30 (D4) asymmetry-gate quantitative threshold:
      ab_old: 10 pass, 0 env → 0% exclusion
      ab_new: 9 pass, 1 env → 10% exclusion
      Δ = 10pp absolute (> 5pp), ratio = inf → blocked."""
    sink = tmp_path / "v.jsonl"
    for _ in range(10):
        _write(sink, "ab_old", "pass")
    for _ in range(9):
        _write(sink, "ab_new", "pass")
    _write(sink, "ab_new", "fail", "env", matched_signature="env.port_conflict")
    r = compute_itt_delta(sink, "ab_old", "ab_new")
    assert r["asymmetry"]["pp"] == pytest.approx(10.0)
    assert r["asymmetry"]["ratio"] == float("inf")
    assert r["asymmetry"]["triggered"]
    assert r["blocked"]


def test_itt_per_arm_counts_uncertain_counts_as_functional(tmp_path):
    """§5.0: an `uncertain` row counts as a functional failure for the rate
    AND is reported separately in the per_arm counts dict."""
    sink = tmp_path / "v.jsonl"
    for _ in range(5):
        _write(sink, "ab_old", "pass")
    _write(sink, "ab_old", "fail", "uncertain")
    counts = compute_itt_delta(sink, "ab_old", "ab_new")["per_arm"]["ab_old"]
    assert counts["uncertain"] == 1
    assert counts["functional_failures"] == 1  # uncertain folded in
    assert counts["env_excluded"] == 0
    assert counts["passes"] == 5
    assert counts["total_runs"] == 6


def test_itt_thresholds_match_spec_constants():
    """Constants the spec freezes (§5.1 numeric thresholds)."""
    assert ASYMMETRY_REL_X == 2.0
    assert ASYMMETRY_ABS_PP == 5.0


def test_compute_itt_delta_handles_empty_arms_gracefully(tmp_path):
    """No data for an arm → rates are 0.0 (no ZeroDivision), not blocked."""
    sink = tmp_path / "v.jsonl"
    # populate only ab_old
    for _ in range(3):
        _write(sink, "ab_old", "pass")
    r = compute_itt_delta(sink, "ab_old", "ab_new")
    assert r["per_arm"]["ab_new"]["total_runs"] == 0
    assert r["as_classified"]["ab_new"] == 0.0
    assert r["itt"]["ab_new"] == 0.0
    # asymmetry: 0 vs 0 → ratio 1.0, pp 0 → not triggered.
    assert not r["blocked"]
