r"""#1202hw: a cap below the cost of finishing buys a truncated run, not a cheap one.

The spend guard is correct and does what it says. What nothing said was that the number
it enforces was, on six consecutive runs, far under what reaching a verdict costs.
Measured on this corpus (2026-09-08), each spending within a dollar of its cap:

    r99  cap $90  -> $90.62      r102 cap $60  -> $60.71
    r100 cap $70  -> $70.88      r103 cap $45  -> $45.61
    r101 cap $150 -> $150.32     r106 cap $80  -> $80.54

All six stopped at tick 5-12 of 200 for $498.67 together and no verdict. The 22 runs
that reached `status=finished` cost a MEDIAN of $355.

It warns and never refuses: a deliberate $50 smoke test is legitimate.
"""
from __future__ import annotations

import logging

import pytest

import utils.llm as L


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    """Each test gets an unlatched warner and a known threshold."""
    monkeypatch.setitem(L._CAP_WARNED_1202HW, "done", False)
    monkeypatch.delenv("ENVGEN_TYPICAL_FINISH_USD", raising=False)
    yield


def _warn_records(caplog, cap):
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="LLM.budget"):
        L._warn_if_cap_cannot_finish_1202hw(cap)
    return [r for r in caplog.records if "#1202hw" in r.getMessage()]


def test_a_cap_below_the_median_warns(caplog):
    assert _warn_records(caplog, 80.0), "the r106 cap must be called out"


def test_every_cap_the_six_runs_used_warns(caplog):
    for cap in (90.0, 70.0, 150.0, 60.0, 45.0, 80.0):
        L._CAP_WARNED_1202HW["done"] = False
        assert _warn_records(caplog, cap), f"${cap} should have warned"


def test_an_adequate_cap_is_silent(caplog):
    assert not _warn_records(caplog, 600.0)


def test_the_median_itself_is_not_below_itself(caplog):
    assert not _warn_records(caplog, L._TYPICAL_FINISH_USD_1202HW)


def test_no_cap_is_silent(caplog):
    """Unset/zero means unlimited — nothing to warn about."""
    for cap in (0.0, 0, None):
        L._CAP_WARNED_1202HW["done"] = False
        assert not _warn_records(caplog, cap)


def test_it_warns_once_not_every_call(caplog):
    """This runs per LLM call; a per-call warning would bury the log it appears in."""
    assert _warn_records(caplog, 50.0)
    for _ in range(5):
        assert not _warn_records(caplog, 50.0)


def test_the_threshold_is_retunable(caplog, monkeypatch):
    monkeypatch.setenv("ENVGEN_TYPICAL_FINISH_USD", "40")
    assert not _warn_records(caplog, 80.0), "80 is above a retuned 40"


def test_a_junk_threshold_falls_back_to_the_measured_one(caplog, monkeypatch):
    monkeypatch.setenv("ENVGEN_TYPICAL_FINISH_USD", "not-a-number")
    assert _warn_records(caplog, 80.0)


def test_a_zero_threshold_disables_it(caplog, monkeypatch):
    monkeypatch.setenv("ENVGEN_TYPICAL_FINISH_USD", "0")
    assert not _warn_records(caplog, 80.0)


def test_it_never_raises(caplog):
    for junk in ("x", [], {}, object()):
        L._CAP_WARNED_1202HW["done"] = False
        L._warn_if_cap_cannot_finish_1202hw(junk)   # must not raise


def test_the_message_names_the_knob_and_says_it_is_not_a_refusal(caplog):
    msg = _warn_records(caplog, 80.0)[0].getMessage()
    assert "ENVGEN_MAX_SPEND_USD" in msg
    assert "not a refusal" in msg
    assert "ENVGEN_TYPICAL_FINISH_USD" in msg


def test_it_is_actually_wired_into_the_guard():
    """Reachability: a helper nothing calls is the defect it was written to fix."""
    import ast, inspect
    src = inspect.getsource(L._record_usage_1163)
    names = {n.func.id for n in ast.walk(ast.parse(src.lstrip()))
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "_warn_if_cap_cannot_finish_1202hw" in names


def test_the_warning_does_not_gate_the_cap_itself(monkeypatch):
    """It must not be able to stop the guard from latching -- asserted by MAKING IT FAIL.

    #1203jt rewrote this. It used to compare two `src.index(...)` offsets inside
    `_record_usage_1163` and require the advisory to appear before
    `if cap > 0 and not _TERMINAL_LLM_ERROR["reason"]:`. That is a source-order proxy for a
    behavioural claim, and it broke on a restructure that serves the claim STRICTLY BETTER:
    the enforcement branch became an early return, so the literal vanished and the test went
    red while the property it names got stronger. Worse, the old shape was green for the whole
    period in which the advisory COULD stop the latch -- it sat before the branch and inside
    the same `try`, so raising from it skipped the enforcement entirely.

    So this now does the only thing that settles it: make the advisory raise, and require the
    latch to close anyway.
    """
    monkeypatch.setenv("ENVGEN_MAX_SPEND_USD", "10")
    monkeypatch.setenv("ENVGEN_PRICE_IN_PER_M", "5.5")
    monkeypatch.setenv("ENVGEN_PRICE_CACHED_PER_M", "0.55")
    monkeypatch.setenv("ENVGEN_PRICE_OUT_PER_M", "33")
    for k, v in list(L._LLM_USAGE.items()):
        if isinstance(v, int):
            monkeypatch.setitem(L._LLM_USAGE, k, 0)
    monkeypatch.setitem(L._TERMINAL_LLM_ERROR, "reason", None)
    L._CAP_CHECK_WARNED_1203JT.clear()
    monkeypatch.setattr(L, "delivering_1183", lambda *a, **k: False, raising=False)
    monkeypatch.setattr(L, "converging_1202cz", lambda *a, **k: False, raising=False)

    def boom(*a, **k):
        raise RuntimeError("the advisory is advisory")
    monkeypatch.setattr(L, "_warn_if_cap_cannot_finish_1202hw", boom, raising=False)

    for _ in range(25):
        L._record_usage_1163(500_000, 0, 20_000)
        if L._TERMINAL_LLM_ERROR["reason"]:
            break
    assert L._TERMINAL_LLM_ERROR["reason"], (
        "the #1202hw advisory raising stopped the spend cap from latching; $%.2f spent against "
        "a $10 cap" % L.llm_usage()["usd"])
    assert L.llm_usage()["usd"] < 11.0, L.llm_usage()["usd"]
