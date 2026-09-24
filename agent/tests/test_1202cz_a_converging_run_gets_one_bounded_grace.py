"""#1202cz — a ceiling that kills a converging run loses everything it already bought.

#1183 makes this argument for a run whose delivery gate has PASSED and grants 25%. The
same loss happens one step earlier, and the ledger shows how often:

    delivered   r38 $237 plateau 1   r40 $284 plateau 1
    wedged      r37 $372 plateau 5           (correctly stopped — it WAS stuck)
    killed      r39 $414 plateau 0   r41 $401 plateau 0   r42 $379 plateau 0

Every run that delivered had plateau >= 1; every run that reached the ceiling with
nothing to show had plateau 0 — the visual gate's OWN signal that the last round still
moved the score. Three runs, ~$1,195, zero delivered, each stopped while the gate said it
was still improving. r41 died at a 0.74 median, the best any run has reached.

The grace therefore keys on evidence the gate already computes, never on optimism, and
r37 is the case that must keep stopping.
"""
import os
from pathlib import Path

import pytest

from utils import llm as llm_mod
from utils.llm import (
    converging_1202cz,
    note_convergence_1202cz,
    _converging_overshoot_1202cz,
    _overshoot_1183,
)


@pytest.fixture(autouse=True)
def _clean():
    before = dict(llm_mod._CONVERGING_1202CZ)
    usage = dict(llm_mod._LLM_USAGE)
    term = dict(llm_mod._TERMINAL_LLM_ERROR)
    yield
    llm_mod._CONVERGING_1202CZ.update(before)
    llm_mod._LLM_USAGE.update(usage)
    llm_mod._TERMINAL_LLM_ERROR.update(term)


@pytest.mark.parametrize("plateau,first,latest,expected,why", [
    (0, 0.43, 0.62, True, "r39/r41/r42: still moving and ahead of round one"),
    (1, 0.43, 0.62, False, "r38/r40's shape — the gate says it has stopped moving"),
    (5, 0.30, 0.42, False, "r37 was genuinely wedged and must keep stopping"),
    (0, 0.62, 0.43, False, "moving, but backwards"),
    (0, None, 0.60, False, "no round-one score to compare against"),
    (None, 0.40, 0.60, False, "no plateau signal at all"),
])
def test_the_predicate_demands_both_signals(plateau, first, latest, expected, why):
    note_convergence_1202cz(plateau, first, latest)
    assert converging_1202cz() is expected, why


def test_the_grace_never_exceeds_the_delivery_grace():
    """#1183's claim is stronger — its remaining work is the bounded release itself.
    A converging run's is 'more rounds', which is not bounded, so it gets less."""
    assert 1.0 < _converging_overshoot_1202cz() <= _overshoot_1183()


def test_a_converging_run_is_not_killed_at_the_bare_cap(monkeypatch):
    """The whole point, exercised through the real ceiling: r41 stopped at $401 of a $400
    cap with the gate reporting plateau 0 and a rising score."""
    monkeypatch.setenv("ENVGEN_MAX_SPEND_USD", "400")
    monkeypatch.setenv("ENVGEN_PRICE_IN_PER_M", "5.50")
    monkeypatch.setenv("ENVGEN_PRICE_CACHED_PER_M", "0.55")
    monkeypatch.setenv("ENVGEN_PRICE_OUT_PER_M", "33.0")
    llm_mod._TERMINAL_LLM_ERROR["reason"] = None
    llm_mod._LLM_USAGE.update({"calls": 0, "prompt": 0, "cached": 0, "completion": 0,
                               "cache_unreported": 0})
    note_convergence_1202cz(0, 0.43, 0.62)

    # ~$412 of uncached input: past the bare cap, inside the 15% grace.
    llm_mod._record_usage_1163(75_000_000, 0, 0)
    assert llm_mod.llm_usage()["usd"] > 400
    assert llm_mod._TERMINAL_LLM_ERROR["reason"] is None, "killed while still converging"


def test_a_plateaued_run_still_stops_at_the_cap(monkeypatch):
    """r37 spent $372 with plateau 5. The grace must not become a blanket raise."""
    monkeypatch.setenv("ENVGEN_MAX_SPEND_USD", "400")
    monkeypatch.setenv("ENVGEN_PRICE_IN_PER_M", "5.50")
    monkeypatch.setenv("ENVGEN_PRICE_CACHED_PER_M", "0.55")
    monkeypatch.setenv("ENVGEN_PRICE_OUT_PER_M", "33.0")
    llm_mod._TERMINAL_LLM_ERROR["reason"] = None
    llm_mod._LLM_USAGE.update({"calls": 0, "prompt": 0, "cached": 0, "completion": 0,
                               "cache_unreported": 0})
    note_convergence_1202cz(5, 0.30, 0.42)

    llm_mod._record_usage_1163(75_000_000, 0, 0)
    assert llm_mod._TERMINAL_LLM_ERROR["reason"], "a wedged run must still be stopped"
    assert "BudgetExceeded" in llm_mod._TERMINAL_LLM_ERROR["reason"]


def test_the_abort_reason_names_the_grace_it_spent(monkeypatch):
    """A run that spends the grace and still fails has to say so, or the next reader
    reconstructs the cap from the number and gets it wrong."""
    monkeypatch.setenv("ENVGEN_MAX_SPEND_USD", "400")
    monkeypatch.setenv("ENVGEN_PRICE_IN_PER_M", "5.50")
    monkeypatch.setenv("ENVGEN_PRICE_CACHED_PER_M", "0.55")
    monkeypatch.setenv("ENVGEN_PRICE_OUT_PER_M", "33.0")
    llm_mod._TERMINAL_LLM_ERROR["reason"] = None
    llm_mod._LLM_USAGE.update({"calls": 0, "prompt": 0, "cached": 0, "completion": 0,
                               "cache_unreported": 0})
    note_convergence_1202cz(0, 0.43, 0.62)

    llm_mod._record_usage_1163(100_000_000, 0, 0)   # ~$550, past even the grace
    reason = llm_mod._TERMINAL_LLM_ERROR["reason"]
    assert reason and "overshoot" in reason
    assert "plateau 0" in reason


def test_the_signal_is_recorded_where_plateau_is_decided():
    """A guard fed from a second derivation is how #1011 ended up with no callers. This
    is anchored on the plateau assignment itself, so the two cannot drift apart."""
    src = Path("env_generator/llm_generator/multi_agent/runtime/"
               "visual_fidelity.py").read_text()
    i = src.index("self.plateau_rounds = 0 if _improved else self.plateau_rounds + 1")
    after = src[i:src.index("FIX #558", i)]
    assert "note_convergence_1202cz" in after
    assert "result.get('blocking_average_live')" in after
