"""PRE-RELEASE BROWSER TEST-USER GATE (2026-06-30, user directive "test-user反馈问题 / 功能完备
/ 没有 mock frontend"): a non-functional UI must NOT ship as "delivered". The delivery flow now
drives a real browser through the running app and HOLDS the release when the app is objectively
UNUSABLE (login broken / blank pages / login wall), mirroring the squad+visual gates' bounded
defer→re-test→escape so it can NEVER deadlock.

This tests the two PURE primitives the orchestrator gate composes (orchestrator.py, the
`ENVGEN_TESTUSER_BROWSER_GATE` block) — the objective-unusable predicate and the bounded-
deferral escape — plus a faithful simulation of the gate's bookkeeping proving:
  * BLOCKS a genuinely-broken app,
  * UNBLOCKS the moment the fix lands (and a one-off flake auto-clears),
  * NEVER blocks on infra (walk could not run),
  * NEVER deadlocks (a persistently-broken app escapes after the attempt cap / wall-clock),
  * soft signals (visual mismatch / console error) stay ADVISORY (never block).
ENV-AGNOSTIC + LOCAL-ONLY (agent/tests/ gitignored)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.test_user_runner import browser_report_unusable  # noqa: E402
from multi_agent.runtime.test_user_squad import squad_release_decision  # noqa: E402


# ─────────────────────────── the objective-unusable predicate ───────────────────────────

def test_login_broken_is_unusable():
    assert browser_report_unusable({"ran": True, "auth_ok": False}) is True


def test_blank_pages_is_unusable():
    assert browser_report_unusable(
        {"ran": True, "auth_ok": True, "blank_pages": ["/inbox"]}) is True


def test_login_wall_is_unusable():
    assert browser_report_unusable(
        {"ran": True, "auth_ok": True, "auth_redirect_pages": ["/inbox"]}) is True


def test_hollow_frontend_is_unusable():
    assert browser_report_unusable(
        {"ran": True, "auth_ok": True, "hollow_frontend": True}) is True


def test_fully_usable_app_is_not_unusable():
    assert browser_report_unusable({
        "ran": True, "auth_ok": True, "blank_pages": [], "auth_redirect_pages": [],
        "hollow_frontend": False}) is False


def test_visual_mismatch_alone_is_advisory_not_unusable():
    # a soft visual deviation must NOT block delivery — it stays advisory (dispatched P0)
    assert browser_report_unusable({
        "ran": True, "auth_ok": True, "blank_pages": [], "auth_redirect_pages": [],
        "hollow_frontend": False, "visual_mismatches": ["/inbox: header off by 8px"]}) is False


def test_console_errors_alone_are_advisory_not_unusable():
    # a benign console warning must NOT block delivery — advisory only
    assert browser_report_unusable({
        "ran": True, "auth_ok": True, "blank_pages": [], "auth_redirect_pages": [],
        "hollow_frontend": False, "error_pages": ["/inbox: Warning: deprecated prop"]}) is False


def test_could_not_run_is_never_unusable():
    # infra failure (playwright absent / app unreachable) must NEVER block delivery
    assert browser_report_unusable({"ran": False, "auth_ok": False, "blank_pages": ["/x"]}) is False


def test_none_and_malformed_reports_are_safe():
    assert browser_report_unusable(None) is False
    assert browser_report_unusable({}) is False
    assert browser_report_unusable("garbage") is False
    assert browser_report_unusable([1, 2, 3]) is False


# ─────────────────── the bounded-deferral escape (deadlock-proof primitive) ───────────────

def test_escape_defers_then_releases_by_attempt_cap():
    # attempts checked BEFORE increment (matches the gate bookkeeping): 3 defers then escape
    t0 = 1000.0
    assert squad_release_decision(t0, 0, t0) == "defer"
    assert squad_release_decision(t0, 1, t0 + 10) == "defer"
    assert squad_release_decision(t0, 2, t0 + 20) == "defer"
    assert squad_release_decision(t0, 3, t0 + 30) == "release"   # attempt cap hit → never deadlock


def test_escape_releases_on_wall_clock_even_below_attempt_cap():
    t0 = 1000.0
    assert squad_release_decision(t0, 1, t0 + 901) == "release"  # 900s wall anchored to first defer


# ─────────── faithful simulation of the orchestrator gate loop (the real bookkeeping) ───────────

def _simulate_gate(cycles):
    """Mirror the orchestrator's ENVGEN_TESTUSER_BROWSER_GATE bookkeeping EXACTLY, using the
    same two pure primitives it calls. `cycles` is [(report, now)]; returns the per-cycle
    outcome so we can assert block/unblock/escape behaviour end-to-end."""
    deferred_since = None
    attempts = 0
    out = []
    for report, now in cycles:
        if browser_report_unusable(report):
            if deferred_since is None:
                deferred_since = now
            decision = squad_release_decision(deferred_since, attempts, now)
            attempts += 1
            out.append("DEFER(hold release)" if decision == "defer" else "ESCAPE(ship loudly)")
        elif isinstance(report, dict) and report.get("ran"):
            deferred_since = None     # usable → clear the per-episode budget
            attempts = 0
            out.append("PASS(cut release)")
        else:
            out.append("SKIP(infra, fall through)")
    return out


_BROKEN = {"ran": True, "auth_ok": False}                       # login broken
_USABLE = {"ran": True, "auth_ok": True, "blank_pages": [],
           "auth_redirect_pages": [], "hollow_frontend": False}
_CANT_RUN = {"ran": False, "summary": "playwright unavailable"}


def test_persistently_broken_app_escapes_never_deadlocks():
    # same broken report every 10s → 3 holds then escape-ship (delivery is NEVER permanently blocked)
    cycles = [(_BROKEN, 1000.0 + 10 * i) for i in range(4)]
    out = _simulate_gate(cycles)
    assert out == ["DEFER(hold release)", "DEFER(hold release)",
                   "DEFER(hold release)", "ESCAPE(ship loudly)"]


def test_broken_then_fixed_unblocks_immediately():
    out = _simulate_gate([(_BROKEN, 1000.0), (_USABLE, 1010.0)])
    assert out == ["DEFER(hold release)", "PASS(cut release)"]   # the fix lands → release cut


def test_one_off_flake_auto_clears_next_cycle():
    # a single flaky unusable read costs ONE deferred cycle, then the re-test passes
    out = _simulate_gate([(_BROKEN, 1000.0), (_USABLE, 1005.0), (_USABLE, 1010.0)])
    assert out == ["DEFER(hold release)", "PASS(cut release)", "PASS(cut release)"]


def test_infra_failure_never_blocks_delivery():
    # walk could not run every cycle → gate always falls through (no hold, no deadlock)
    out = _simulate_gate([(_CANT_RUN, 1000.0), (_CANT_RUN, 1010.0)])
    assert out == ["SKIP(infra, fall through)", "SKIP(infra, fall through)"]


def test_usable_app_cuts_release_first_try():
    out = _simulate_gate([(_USABLE, 1000.0)])
    assert out == ["PASS(cut release)"]


def test_visual_only_report_cuts_release_not_blocked():
    # objectively usable but visually imperfect → SHIP (visual stays advisory)
    vis = {"ran": True, "auth_ok": True, "blank_pages": [], "auth_redirect_pages": [],
           "hollow_frontend": False, "visual_mismatches": ["/inbox off"]}
    assert _simulate_gate([(vis, 1000.0)]) == ["PASS(cut release)"]


def test_budget_resets_between_episodes():
    # broken → fixed (reset) → broken again gets a FRESH 3-defer budget (not carried over)
    cycles = [(_BROKEN, 1000.0), (_USABLE, 1010.0),
              (_BROKEN, 1020.0), (_BROKEN, 1030.0), (_BROKEN, 1040.0), (_BROKEN, 1050.0)]
    out = _simulate_gate(cycles)
    assert out == ["DEFER(hold release)", "PASS(cut release)",
                   "DEFER(hold release)", "DEFER(hold release)",
                   "DEFER(hold release)", "ESCAPE(ship loudly)"]


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
