"""#1203jt: the spend cap was skipped, silently, whenever anything near it raised.

The whole cap check lived inside one `try: ... except Exception: return`, so an exception in
the #1202hw advisory line, in either overshoot probe, or in `llm_usage()` skipped the CAP
COMPARISON for that call and logged nothing. Driven locally before the fix: make one
collaborator raise and the latch never closes -- 20 calls later the run has spent 6.8x its
cap with no line anywhere. This is the only thing between a loop and real money.

Consistent with the corpus, not proven by it: r155 ($351.08 against a $300 cap), r167
($283.61/$250), r161 ($364.97/$350) and r164 ($404.11/$400) all latched far past their cap
while carrying NO overshoot clause, i.e. `_shoot` was 1.0 and the latch should have closed on
the first call across the line. At r155's $0.057/call that is ~890 consecutive calls whose
check did not fire. r163 and r165 are NOT this: they say `delivery overshoot applied, x1.25`
and land on exactly 1.25x, which is the documented grace working.
"""
import importlib
import logging
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

PRICES = {"ENVGEN_PRICE_IN_PER_M": "5.5", "ENVGEN_PRICE_CACHED_PER_M": "0.55",
          "ENVGEN_PRICE_OUT_PER_M": "33", "ENVGEN_MAX_SPEND_USD": "10"}


@pytest.fixture()
def llm(monkeypatch):
    for k, v in PRICES.items():
        monkeypatch.setenv(k, v)
    m = importlib.import_module("utils.llm")
    for k, v in list(m._LLM_USAGE.items()):
        if isinstance(v, int):
            monkeypatch.setitem(m._LLM_USAGE, k, 0)
    monkeypatch.setitem(m._TERMINAL_LLM_ERROR, "reason", None)
    m._CAP_CHECK_WARNED_1203JT.clear()
    monkeypatch.setattr(m, "delivering_1183", lambda *a, **k: False, raising=False)
    monkeypatch.setattr(m, "converging_1202cz", lambda *a, **k: False, raising=False)
    return m


def _spend_until_latch(m, n=25, unc=500_000, out=20_000):
    """Returns (call index that latched or None, usd at the end)."""
    for i in range(n):
        m._record_usage_1163(unc, 0, out)
        if m._TERMINAL_LLM_ERROR["reason"]:
            return i + 1, m.llm_usage()["usd"]
    return None, m.llm_usage()["usd"]


def test_the_cap_latches_without_any_fault(llm):
    k, usd = _spend_until_latch(llm)
    assert k is not None, "the cap never closed on a clean path"
    assert usd < 15.0, usd                      # a $10 cap must not reach 1.5x


@pytest.mark.parametrize("victim", ["_warn_if_cap_cannot_finish_1202hw",
                                    "converging_1202cz",
                                    "delivering_1183"])
def test_a_raising_collaborator_no_longer_disarms_the_cap(llm, monkeypatch, victim):
    """Each of these sits in the same block as the cap comparison used to."""
    def boom(*a, **k):
        raise RuntimeError("boom")
    monkeypatch.setattr(llm, victim, boom, raising=False)
    k, usd = _spend_until_latch(llm)
    assert k is not None, (
        "%s raising disarmed the spend cap: 25 calls spent $%.2f against a $10 cap with no "
        "latch" % (victim, usd))
    assert usd < 15.0, (victim, usd)


def test_the_failure_is_announced_not_swallowed(llm, monkeypatch, caplog):
    def boom(*a, **k):
        raise RuntimeError("boom")
    monkeypatch.setattr(llm, "converging_1202cz", boom, raising=False)
    with caplog.at_level(logging.ERROR, logger="LLM.budget"):
        _spend_until_latch(llm)
    said = [r.getMessage() for r in caplog.records if "1203jt" in r.getMessage()]
    assert said, "the cap check failed and nothing was logged"
    assert len(said) == 1, "once per step, not once per call: %d lines" % len(said)


def test_the_announcement_says_the_cap_is_still_enforced_when_it_is(llm, caplog):
    """A sentence that claims more than the code does is the defect one level out.

    Losing the overshoot probe does NOT stop the comparison -- it only removes the grace --
    so the line must not tell an operator the cap is off.
    """
    with caplog.at_level(logging.ERROR, logger="LLM.budget"):
        llm._warn_cap_check_1203jt("computing the overshoot allowance",
                                   RuntimeError("x"), enforced=True)
    msg = [r.getMessage() for r in caplog.records if "1203jt" in r.getMessage()][0]
    assert "STILL enforced" in msg, msg
    assert "NOT enforced" not in msg, msg


def test_the_announcement_says_the_cap_is_off_when_it_is(llm, caplog):
    with caplog.at_level(logging.ERROR, logger="LLM.budget"):
        llm._warn_cap_check_1203jt("comparing spend against the cap",
                                   RuntimeError("x"), enforced=False)
    msg = [r.getMessage() for r in caplog.records if "1203jt" in r.getMessage()][0]
    assert "NOT enforced" in msg, msg
    assert "STILL enforced" not in msg, msg


def test_a_failed_overshoot_probe_falls_back_to_no_grace(llm, monkeypatch):
    """1.0 is the conservative side: stop at the operator's number, do not invent a grace."""
    monkeypatch.setattr(llm, "delivering_1183", lambda *a, **k: True, raising=False)
    monkeypatch.setattr(llm, "_overshoot_1183",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
                        raising=False)
    k, usd = _spend_until_latch(llm)
    assert k is not None, "the cap never closed"
    # Tight against the cap, not merely "below some ceiling": a $10 cap with NO grace latches
    # on the first call across $10. `usd < 15` also passes for an invented x1.25, which is how
    # a mutation that granted exactly that survived the first version of this test.
    assert usd < 11.0, "a grace was applied anyway: latched at $%.2f against a $10 cap" % usd
    reason = llm._TERMINAL_LLM_ERROR["reason"] or ""
    # Any multiplier clause at all, whatever it calls itself -- the format is " (<why>, xN.NN)"
    # and asserting on the WORDING let `_why = "invented"` through.
    assert "x1." not in reason and ", x" not in reason, (
        "a grace nobody could compute was granted and named: %s" % reason)


def test_the_designed_overshoot_still_applies(llm, monkeypatch):
    """#1183's grace is the behaviour this patch must not break."""
    monkeypatch.setattr(llm, "delivering_1183", lambda *a, **k: True, raising=False)
    monkeypatch.setattr(llm, "_overshoot_1183", lambda *a, **k: 1.25, raising=False)
    k, usd = _spend_until_latch(llm, n=40)
    assert k is not None, "the cap never closed"
    assert usd >= 12.5, "the x1.25 delivery grace was lost: stopped at $%.2f" % usd
    assert "x1.25" in (llm._TERMINAL_LLM_ERROR["reason"] or ""), llm._TERMINAL_LLM_ERROR["reason"]


def test_a_normal_latch_does_not_cry_about_a_gap(llm):
    """The tail of one call is not evidence that the check skipped anything."""
    _spend_until_latch(llm)
    reason = llm._TERMINAL_LLM_ERROR["reason"] or ""
    assert "threshold in force $10.00" in reason, reason
    assert "PAST the" not in reason, (
        "an ordinary latch, one call past the line, claimed the check had not been firing: %s"
        % reason)


def test_a_cap_that_arrives_late_names_the_gap_it_landed_past(llm, monkeypatch):
    """The shape that cost an hour of archaeology, now self-explaining.

    With no cap set the check returns early, so spend accumulates unenforced; the moment a cap
    appears the first call latches at whatever the total already is. The old reason said only
    "run spend $X reached cap $Y" and could not distinguish that from an expensive last call --
    which is exactly the ambiguity r155/r161/r164/r167 left behind.
    """
    monkeypatch.delenv("ENVGEN_MAX_SPEND_USD", raising=False)
    for _ in range(10):
        llm._record_usage_1163(500_000, 0, 20_000)
    assert not llm._TERMINAL_LLM_ERROR["reason"], "no cap was set, nothing should latch"
    before = llm.llm_usage()["usd"]
    assert before > 20.0, before

    monkeypatch.setenv("ENVGEN_MAX_SPEND_USD", "10")
    llm._record_usage_1163(500_000, 0, 20_000)
    reason = llm._TERMINAL_LLM_ERROR["reason"] or ""
    assert reason, "the cap appeared and nothing latched"
    assert "PAST the $10.00 threshold" in reason, reason
    assert "the check did not fire on every call before this one" in reason, reason
    assert "#1203jt" in reason, reason
