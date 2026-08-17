"""#492 — DELIVER-TAIL CONVERGENCE WEDGE (netflix r64, 2026-08-04). With crash/build
blockers fixed, the delivery gate reached 15→2 failed checks then CHURNED and never
converged: api_smoke PASSED and recorded build:* truth (run_23e001c30a @20:26), but the
by-construction backend skeleton REGENERATED 13× (20:35→20:47) on each app-source/contract
change, and every regen re-invalidated build:* freshness. FIX #120's deterministic
refresher (maybe_refresh_stale_build_checklist) was flat-capped at 3/milestone and was
EXHAUSTED at 20:37:32 (log: "refresh 1/3, 2/3, 3/3") — so once spent, the churn kept
regenerating the skeleton but nothing could re-record fresh build:* truth →
verification_checklist_not_ready stayed permanently red → no delivery (delivery then
relied on the LLM verifier, which never complied).

FIX (#492, SETTLE-THEN-RECORD): beyond the flat 3-cap, ALSO grant a refresh when the
backend BUILD STATE genuinely CHANGED since the last refresh (backend_source_signature
differs from the stored orch._checklist_refresh_last_sig), up to a HIGHER hard cap (10).
Each skeleton regen is a NEW build that legitimately needs one fresh api_smoke recording.
NO LIVELOCK: a STATIC stuck state (sig unchanged) still caps at the flat 3, and a
PERPETUAL churn is bounded by the hard cap → the existing no-convergence abort still fires.

These tests drive the refresh DECISION with a lightweight stub orch and a monkeypatched
backend_source_signature, so they are fully hermetic (no filesystem / docker)."""
import types

import env_generator.llm_generator.multi_agent.runtime.framework_validation as fv

_FAILED = ["verification_checklist_not_ready"]
_FLAT = fv._CHECKLIST_REFRESH_FLAT_CAP    # 3
_HARD = fv._CHECKLIST_REFRESH_HARD_CAP    # 10


def _orch(logger=None):
    """A lightweight stub with exactly the attributes the function reads/writes."""
    return types.SimpleNamespace(
        _current_milestone_version="1.0.0",
        _framework_validation_attempts=99,
        _checklist_refresh_last_sig=None,
        output_dir="/tmp/fg492-hermetic",   # never touched (sig fn is monkeypatched)
        _logger=logger or types.SimpleNamespace(
            warning=lambda *a, **k: None, debug=lambda *a, **k: None),
    )


def _stub_sig(monkeypatch, holder):
    """Route backend_source_signature to a mutable holder so a test can flip the
    'build state' without any real filesystem."""
    monkeypatch.setattr(fv, "backend_source_signature", lambda _app_root: holder["sig"])


# ── (a) not in failed_checks → False, no-op ─────────────────────────────────────
def test_not_in_failed_checks_is_noop(monkeypatch):
    _stub_sig(monkeypatch, {"sig": "A"})
    orch = _orch()
    assert fv.maybe_refresh_stale_build_checklist(orch, ["something_else"]) is False
    # returned before touching any state
    assert orch._framework_validation_attempts == 99
    assert getattr(orch, "_checklist_refresh_by_ms", "UNSET") == "UNSET"
    # empty / None failed sets are also a clean no-op
    assert fv.maybe_refresh_stale_build_checklist(orch, None) is False
    assert fv.maybe_refresh_stale_build_checklist(orch, []) is False


# ── (b) first 3 calls with SAME sig → True (flat budget) ────────────────────────
def test_flat_budget_three_same_sig(monkeypatch):
    _stub_sig(monkeypatch, {"sig": "A"})
    orch = _orch()
    for i in range(_FLAT):
        orch._framework_validation_attempts = 7
        assert fv.maybe_refresh_stale_build_checklist(orch, _FAILED) is True, i
        # every grant re-arms api_smoke
        assert orch._framework_validation_attempts == 0
    assert orch._checklist_refresh_by_ms["1.0.0"] == _FLAT


# ── (c) 4th call SAME sig → False (flat cap, no change) ─────────────────────────
def test_fourth_call_same_sig_denied(monkeypatch):
    _stub_sig(monkeypatch, {"sig": "A"})
    orch = _orch()
    for _ in range(_FLAT):
        assert fv.maybe_refresh_stale_build_checklist(orch, _FAILED) is True
    orch._framework_validation_attempts = 42
    assert fv.maybe_refresh_stale_build_checklist(orch, _FAILED) is False
    # a denial must NOT touch the attempt counter or the budget
    assert orch._framework_validation_attempts == 42
    assert orch._checklist_refresh_by_ms["1.0.0"] == _FLAT


# ── (d) 4th call with CHANGED sig → True (settle-then-record) ───────────────────
def test_fourth_call_changed_sig_granted(monkeypatch):
    holder = {"sig": "A"}
    _stub_sig(monkeypatch, holder)
    orch = _orch()
    for _ in range(_FLAT):
        assert fv.maybe_refresh_stale_build_checklist(orch, _FAILED) is True
    # #501: cur_sig is now the COMBINED backend|frontend signature ("A|None" here, since the
    # hermetic dir has no frontend/src → frontend_source_signature returns None).
    assert str(orch._checklist_refresh_last_sig).startswith("A")
    holder["sig"] = "B"   # a skeleton regen → new build state
    orch._framework_validation_attempts = 9
    assert fv.maybe_refresh_stale_build_checklist(orch, _FAILED) is True
    assert orch._framework_validation_attempts == 0
    assert orch._checklist_refresh_by_ms["1.0.0"] == _FLAT + 1
    assert str(orch._checklist_refresh_last_sig).startswith("B")


# ── (e) keeps granting on each new distinct sig up to the hard cap, then False ──
def test_settle_bounded_by_hard_cap_no_livelock(monkeypatch):
    holder = {"sig": "A"}
    _stub_sig(monkeypatch, holder)
    orch = _orch()
    # flat budget (3 grants) on sig A
    for _ in range(_FLAT):
        assert fv.maybe_refresh_stale_build_checklist(orch, _FAILED) is True
    granted = _FLAT
    # a distinct sig every call (a perpetual legitimate churn)
    for s in "BCDEFGHIJKLMN":
        holder["sig"] = s
        res = fv.maybe_refresh_stale_build_checklist(orch, _FAILED)
        if granted < _HARD:
            assert res is True, (s, granted)
            granted += 1
        else:
            # hard cap reached — a brand-new distinct sig is now DENIED (no livelock)
            assert res is False, (s, granted)
    assert orch._checklist_refresh_by_ms["1.0.0"] == _HARD
    # once more, still denied even with a fresh sig
    holder["sig"] = "Z"
    assert fv.maybe_refresh_stale_build_checklist(orch, _FAILED) is False
    assert orch._checklist_refresh_by_ms["1.0.0"] == _HARD


# ── (f) never raises — bad logger, sig fn that throws, bare orch ────────────────
def test_never_raises_on_bad_logger_and_sig(monkeypatch):
    def _boom(_app_root):
        raise RuntimeError("sig boom")
    monkeypatch.setattr(fv, "backend_source_signature", _boom)

    class _BadLogger:
        def warning(self, *a, **k):
            raise RuntimeError("log boom")
        def debug(self, *a, **k):
            raise RuntimeError("log boom")

    orch = _orch(logger=_BadLogger())
    # sig fn raises → cur_sig None, but the flat path still grants; logger raises →
    # swallowed by the inner try/except. Must return True without propagating.
    assert fv.maybe_refresh_stale_build_checklist(orch, _FAILED) is True
    assert orch._framework_validation_attempts == 0


def test_never_raises_on_bare_orch():
    # a truly bare object: getattr defaults must cover every read; missing _logger
    # (attribute error inside the inner try) must be swallowed.
    orch = types.SimpleNamespace()
    assert fv.maybe_refresh_stale_build_checklist(orch, _FAILED) is True  # flat grant
    assert orch._framework_validation_attempts == 0
    assert orch._checklist_refresh_by_ms[""] == 1   # ms defaults to ""


# ── sig None never advances past the flat cap (defensive; no livelock on faults) ─
def test_sig_none_never_settles(monkeypatch):
    _stub_sig(monkeypatch, {"sig": None})   # backend dir missing / fault → None
    orch = _orch()
    for _ in range(_FLAT):
        assert fv.maybe_refresh_stale_build_checklist(orch, _FAILED) is True
    # flat exhausted and sig is uncomputable → no settle grant ever
    assert fv.maybe_refresh_stale_build_checklist(orch, _FAILED) is False
    assert orch._checklist_refresh_by_ms["1.0.0"] == _FLAT


# ── #501 (netflix r70): a FRONTEND-only source change also grants a settle-refresh ──
def _stub_both(monkeypatch, be_holder, fe_holder):
    monkeypatch.setattr(fv, "backend_source_signature", lambda _a: be_holder["sig"])
    monkeypatch.setattr(fv, "frontend_source_signature", lambda _a: fe_holder["sig"])


def test_frontend_only_change_grants_settle_501(monkeypatch):
    # r70's EXACT wedge: build:frontend stale (frontend changed) while the BACKEND source is
    # stable. Pre-#501, cur_sig keyed on backend alone → unchanged → flat budget exhausted →
    # permanent verification_checklist_not_ready. #501 keys on backend|frontend, so the frontend
    # change re-arms the settle-refresh.
    be = {"sig": "BE"}
    fe = {"sig": "FE1"}
    _stub_both(monkeypatch, be, fe)
    orch = _orch()
    for _ in range(_FLAT):
        assert fv.maybe_refresh_stale_build_checklist(orch, _FAILED) is True
    fe["sig"] = "FE2"                       # a frontend-only fix (backend BE unchanged)
    orch._framework_validation_attempts = 5
    assert fv.maybe_refresh_stale_build_checklist(orch, _FAILED) is True
    assert orch._framework_validation_attempts == 0
    assert orch._checklist_refresh_by_ms["1.0.0"] == _FLAT + 1


def test_both_static_still_flat_capped_501(monkeypatch):
    # neither lane changes → still capped at the flat 3 (no livelock, unchanged from #492)
    _stub_both(monkeypatch, {"sig": "BE"}, {"sig": "FE"})
    orch = _orch()
    for _ in range(_FLAT):
        assert fv.maybe_refresh_stale_build_checklist(orch, _FAILED) is True
    assert fv.maybe_refresh_stale_build_checklist(orch, _FAILED) is False


def test_frontend_source_signature_fn_501(tmp_path):
    root = tmp_path / "app"
    src = root / "frontend" / "src" / "pages"
    src.mkdir(parents=True)
    (src / "Home.jsx").write_text("export default function H(){return null}")
    s1 = fv.frontend_source_signature(root)
    assert s1 is not None
    assert fv.frontend_source_signature(root) == s1          # stable when unchanged
    (src / "Home.jsx").write_text("export default function H(){return <div/>}")
    assert fv.frontend_source_signature(root) != s1          # changes on a frontend edit
    assert fv.frontend_source_signature(tmp_path / "nope") is None   # missing → None


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
