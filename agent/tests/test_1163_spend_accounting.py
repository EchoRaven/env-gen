"""#1163: the framework had a spend cap and no spend.

`terminal_llm_error()` can abort a run when the PROVIDER says the money ran
out, but nothing counted what a run costs. The number existed only afterwards,
by grepping `prompt_tokens=` out of a log — which is how a 2.4x spread between
two DELIVERING runs stayed invisible: r13 delivered on 6362 calls and 379M
prompt tokens, r14 on 2626 and 177M. Also invisible: 91-92% of input tokens are
CACHE HITS, so protecting that rate is worth far more than shaving rounds.

Prices are configuration, not knowledge — this module must not carry a guess at
a model's rate. Unset means tokens are still counted and cost reads 0.0 with
`priced` False, which is honest rather than wrong.
"""
import importlib
import os
from pathlib import Path

import pytest

import utils.llm as L


@pytest.fixture(autouse=True)
def clean():
    for k in ("ENVGEN_PRICE_IN_PER_M", "ENVGEN_PRICE_CACHED_PER_M",
              "ENVGEN_PRICE_OUT_PER_M", "ENVGEN_MAX_SPEND_USD"):
        os.environ.pop(k, None)
    L._LLM_USAGE.update(calls=0, prompt=0, cached=0, completion=0, cache_unreported=0)
    L._TERMINAL_LLM_ERROR["reason"] = None
    yield
    for k in ("ENVGEN_PRICE_IN_PER_M", "ENVGEN_PRICE_CACHED_PER_M",
              "ENVGEN_PRICE_OUT_PER_M", "ENVGEN_MAX_SPEND_USD"):
        os.environ.pop(k, None)
    L._LLM_USAGE.update(calls=0, prompt=0, cached=0, completion=0, cache_unreported=0)
    L._TERMINAL_LLM_ERROR["reason"] = None


# r13's real totals, summed from its log
R13 = (379156878, 348341504, 1924451)


def test_unpriced_counts_tokens_and_says_so():
    L._record_usage_1163(*R13)
    u = L.llm_usage()
    assert u["calls"] == 1
    assert u["uncached"] == 30815374 and u["cached"] == 348341504
    assert u["priced"] is False and u["usd"] == 0.0


def test_priced_reproduces_the_hand_calculation():
    os.environ.update(ENVGEN_PRICE_IN_PER_M="1.25",
                      ENVGEN_PRICE_CACHED_PER_M="0.125",
                      ENVGEN_PRICE_OUT_PER_M="10")
    L._record_usage_1163(*R13)
    assert round(L.llm_usage()["usd"], 2) == 101.31


def test_an_unreported_cache_field_is_not_counted_as_zero():
    """#1026 reports "n/a" when the provider omits it. Counting that as 0 would
    silently understate the hit rate, so count the omission instead."""
    L._record_usage_1163(1000, "n/a", 10)
    u = L.llm_usage()
    assert u["cached"] == 0 and u["cache_unreported"] == 1


def test_a_budget_cap_reuses_the_terminal_latch():
    """One abort mechanism, and it is the one verified on live runs (#1159 classifies,
    #1161 stops the lanes, #326 ends the run; r17 took 2h50m -> 272s)."""
    os.environ.update(ENVGEN_PRICE_IN_PER_M="1.25", ENVGEN_PRICE_CACHED_PER_M="0.125",
                      ENVGEN_PRICE_OUT_PER_M="10", ENVGEN_MAX_SPEND_USD="50")
    assert L.terminal_llm_error() is None
    L._record_usage_1163(*R13)
    r = L.terminal_llm_error() or ""
    assert "BudgetExceeded" in r and "$50.00" in r


def test_no_cap_never_latches():
    os.environ.update(ENVGEN_PRICE_IN_PER_M="1.25")
    L._record_usage_1163(*R13)
    assert L.terminal_llm_error() is None


def test_accounting_never_raises_on_junk():
    L._record_usage_1163(None, None, None)
    L._record_usage_1163("x", object(), [])
    assert L.llm_usage()["calls"] >= 1


def test_it_is_recorded_at_every_response_site():
    src = Path(L.__file__).read_text(encoding="utf-8")
    calls = src.count("_record_usage_1163(prompt_tokens, cached_tokens, "
                      "completion_tokens)")     # the def line must not count
    assert calls == src.count("[LLM Response] latency=") == 2, calls


def test_the_run_record_carries_it():
    from env_generator.llm_generator.multi_agent.runtime import run_budget
    src = Path(run_budget.__file__).read_text(encoding="utf-8")
    assert "llm_usage" in src and '"llm"' in src
