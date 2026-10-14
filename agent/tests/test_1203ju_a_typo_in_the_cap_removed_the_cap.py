"""#1203ju: an unreadable money setting meant "unset", and for the cap that means NO CAP.

`_price_env_1163` returned 0.0 for "not set" and for "set to something I cannot parse" alike,
and a 0 cap means unlimited. So a plausible operator typo silently removed the only guard
between a loop and real money, with no line in any log. Measured against a $10 cap, 20 calls
of $3.41 each:

    "650"   -> 650.0  enforced        "$650"       -> 0.0  NEVER latches
    " 650 " -> 650.0  enforced        "650.00 USD" -> 0.0  NEVER latches
    "650."  -> 650.0  enforced        "650,00"     -> 0.0  NEVER latches

The same collapse hits the PRICES, where it is just as bad in a quieter way: an unparseable
rate makes `priced` False, so the cap cannot fire at all AND run_budget.json reports $0.00 for
a run that spent money.

Underscores are rejected rather than parsed: `float("6_50")` is 650.0 because Python allows
digit grouping in literals, so "6_50" meant as six-fifty becomes a cap a hundred times larger,
in the dangerous direction.
"""
import importlib
import logging
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import utils.llm as L  # noqa: E402

PRICES = {"ENVGEN_PRICE_IN_PER_M": "5.5", "ENVGEN_PRICE_CACHED_PER_M": "0.55",
          "ENVGEN_PRICE_OUT_PER_M": "33"}


@pytest.fixture()
def fresh(monkeypatch):
    for k, v in PRICES.items():
        monkeypatch.setenv(k, v)
    for k, v in list(L._LLM_USAGE.items()):
        if isinstance(v, int):
            monkeypatch.setitem(L._LLM_USAGE, k, 0)
    monkeypatch.setitem(L._TERMINAL_LLM_ERROR, "reason", None)
    L._CAP_CHECK_WARNED_1203JT.clear()
    L._MONEY_ENV_BAD_1203JU.clear()
    monkeypatch.setattr(L, "delivering_1183", lambda *a, **k: False, raising=False)
    monkeypatch.setattr(L, "converging_1202cz", lambda *a, **k: False, raising=False)
    return L


def _spend(m, n=20):
    for _ in range(n):
        m._record_usage_1163(500_000, 0, 20_000)
        if m._TERMINAL_LLM_ERROR["reason"]:
            break
    return m._TERMINAL_LLM_ERROR["reason"] or ""


@pytest.mark.parametrize("raw", ["650", " 650 ", "650.", "650.50", "0.5"])
def test_a_plain_amount_still_parses(fresh, raw):
    # read it through the env, the way every caller does
    os.environ["ENVGEN_MAX_SPEND_USD"] = raw
    try:
        value, got_raw, ok = fresh._money_env_1203ju("ENVGEN_MAX_SPEND_USD")
    finally:
        os.environ.pop("ENVGEN_MAX_SPEND_USD", None)
    assert ok is True, (raw, got_raw)
    assert value == float(raw.strip()), (raw, value)


@pytest.mark.parametrize("raw", ["$650", "650.00 USD", "650,00", "6_50", "six hundred", "650$"])
def test_a_money_value_it_cannot_read_is_not_silently_zero(fresh, monkeypatch, raw):
    monkeypatch.setenv("ENVGEN_MAX_SPEND_USD", raw)
    value, got_raw, ok = fresh._money_env_1203ju("ENVGEN_MAX_SPEND_USD")
    assert ok is False, "%r parsed as %r; a bad value must be distinguishable from unset" % (
        raw, value)
    assert got_raw == raw.strip()


@pytest.mark.parametrize("raw", ["", "   "])
def test_unset_stays_unset_and_stays_legitimate(fresh, monkeypatch, raw):
    """"No cap" and "price it later" are both in use; only a BAD value is an error."""
    monkeypatch.setenv("ENVGEN_MAX_SPEND_USD", raw)
    value, _raw, ok = fresh._money_env_1203ju("ENVGEN_MAX_SPEND_USD")
    assert (value, ok) == (0.0, True)
    assert _spend(fresh) == "", "an unset cap must not stop the run"


def test_a_zero_cap_is_a_parse_not_an_error(fresh, monkeypatch):
    monkeypatch.setenv("ENVGEN_MAX_SPEND_USD", "0")
    value, _raw, ok = fresh._money_env_1203ju("ENVGEN_MAX_SPEND_USD")
    assert (value, ok) == (0.0, True)
    assert _spend(fresh) == "", "a deliberate 0 means no cap, not a refusal"


@pytest.mark.parametrize("raw", ["$650", "650,00", "6_50"])
def test_an_unreadable_cap_refuses_instead_of_running_uncapped(fresh, monkeypatch, raw):
    """The behaviour change: a cap that cannot be enforced must not become no cap."""
    monkeypatch.setenv("ENVGEN_MAX_SPEND_USD", raw)
    reason = _spend(fresh)
    assert "refusing to run UNCAPPED" in reason, (
        "cap %r left the run unbounded; spent $%.2f with no latch"
        % (raw, fresh.llm_usage()["usd"]))
    assert raw in reason, "the refusal must quote what was actually set: %s" % reason


@pytest.mark.parametrize("raw", ["$650", "650,00"])
def test_the_refusal_is_classified_as_our_own_cap_not_the_provider(fresh, monkeypatch, raw):
    """#1180: the ledger must not send the next reader to check the API key."""
    monkeypatch.setenv("ENVGEN_MAX_SPEND_USD", raw)
    reason = _spend(fresh)
    assert reason.lstrip().startswith("[BudgetExceeded]"), reason
    assert "ENVGEN_MAX_SPEND_USD" in reason, reason
    # Named, not discovered by prefix: a `dir()` scan that matches nothing asserts nothing,
    # and a vacuous loop here would pass for a refusal the ledger blames on the provider.
    assert L.terminal_stop_is_own_budget_1202hv(reason) is True, reason


def test_the_bad_value_is_announced_once_per_variable(fresh, monkeypatch, caplog):
    monkeypatch.setenv("ENVGEN_MAX_SPEND_USD", "$650")
    with caplog.at_level(logging.ERROR, logger="LLM.budget"):
        _spend(fresh)
        _spend(fresh)
    said = [r.getMessage() for r in caplog.records if "1203ju" in r.getMessage()]
    assert len(said) == 1, "once per variable, not once per call: %d" % len(said)
    assert "$650" in said[0] and "NO SPEND CAP" in said[0], said[0]


def test_a_bad_price_is_announced_and_names_what_it_costs(fresh, monkeypatch, caplog):
    """An unparseable rate silently makes the whole ledger read $0.00."""
    monkeypatch.setenv("ENVGEN_PRICE_IN_PER_M", "5.5 per million")
    with caplog.at_level(logging.ERROR, logger="LLM.budget"):
        assert fresh._price_env_1163("ENVGEN_PRICE_IN_PER_M") == 0.0
    said = [r.getMessage() for r in caplog.records if "1203ju" in r.getMessage()]
    assert said, "a bad price was swallowed"
    assert "ENVGEN_PRICE_IN_PER_M" in said[0] and "$0.00" in said[0], said[0]
