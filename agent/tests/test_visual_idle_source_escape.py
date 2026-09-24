"""FIX #145 — idle-source escape for the visual window.

run-68 M4 live: the last real judgment was at 13:59:37, the release came at
14:21:45 via the 3615s anchor — 22 minutes of ZERO new judgments. The gate
judges on source change; when the frontend stops producing changes the
plateau counter (#138) freezes below its cap and only the 3600s anchor can
release. But a frozen source is the STRONGEST plateau evidence there is: no
change → no new evidence → the scores are what they are. New escape: after
the plateau deferral floor, if no real judgment has happened for
ENVGEN_VISUAL_IDLE_S (default 600s), release (recorded below-threshold).
"""
import sys
from pathlib import Path
from types import SimpleNamespace

AGENT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT))

from env_generator.llm_generator.multi_agent.orchestrator import (
    _visual_release_decision, VISUAL_PLATEAU_MIN_S)
from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf

T0 = 1_000_000.0


def test_idle_source_escapes_after_floor():
    # deferred 1600s (past floor), last judgment 700s ago, plateau below cap
    assert _visual_release_decision(
        T0, attempts=1, total_judgments=8, now=T0 + 1600,
        plateau_rounds=2, last_judgment_at=T0 + 900,
        idle_s=600) == "release"


def test_active_source_keeps_deferring():
    # judgments still flowing (last one 60s ago) → no idle escape
    assert _visual_release_decision(
        T0, attempts=1, total_judgments=8, now=T0 + 1600,
        plateau_rounds=2, last_judgment_at=T0 + 1540,
        idle_s=600) == "defer"


def test_idle_before_floor_keeps_deferring():
    # idle 700s but total deferral below the plateau floor → defer
    now = T0 + VISUAL_PLATEAU_MIN_S - 100
    assert _visual_release_decision(
        T0, attempts=1, total_judgments=8, now=now,
        plateau_rounds=0, last_judgment_at=now - 700,
        idle_s=600) == "defer"


def test_no_judgment_timestamp_never_idle_escapes():
    # never judged (auth refunds etc.) → idle escape must not fire
    assert _visual_release_decision(
        T0, attempts=1, total_judgments=0, now=T0 + 1600,
        plateau_rounds=0, last_judgment_at=None,
        idle_s=600) == "defer"


def test_idle_escape_disabled_by_zero():
    assert _visual_release_decision(
        T0, attempts=1, total_judgments=8, now=T0 + 1600,
        plateau_rounds=2, last_judgment_at=T0 + 900,
        idle_s=0) == "defer"


def test_gate_tracks_last_judgment_at():
    g = vf.VisualFidelityGate(SimpleNamespace())
    assert g.last_judgment_at is None
    g.last_judgment_at = 123.0
    g.reset_for_milestone()
    assert g.last_judgment_at is None, "reset_for_milestone must clear the stamp"
