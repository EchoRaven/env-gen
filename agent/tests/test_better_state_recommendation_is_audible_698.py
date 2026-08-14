r"""#698: #641 computed the right answer and told nobody.

#641 asks, at every visual-gate round, whether an EARLIER capture of this run scored better than
the one about to ship. r146 validated it end to end:

    rounds  r1 .5809  r2 .5809  r3 .5855  r4 .6027  r5 .6700 (live .6655)
            r6-r9 .6700, live .6409 — four rounds that never recovered r5's live score
    verdict "better_state_available": {"code_state": "5333c4b1ffe2...",
                                       "score": 0.6655, "delta": 0.0246}

Right round, right score, and a delta matching an independent recomputation to the digit. It
cleared the 0.02 margin by 0.0046, so it is a narrow call rather than a comfortable one.

And then it went nowhere. Grepping the tree for `better_state_available` and `better_state_note`
finds only the three lines that PRODUCE them; the sole reader of `verdict.json` is #500's
best-of merge, which takes per-screen similarities and never looks at these keys. So a correct
recommendation reached no agent, no gate, no log and no human — the same shape as #691's silent
skip and #696's invisible load failure. A detector whose output is not observable is
indistinguishable from one that never ran.

The fix is a WARNING and nothing else. The release-policy question — whether the bounded escape
should ship the BEST recorded round instead of the last — stays open ON PURPOSE: an earlier
commit can score better visually while being functionally worse, and that trade is not this
function's to make. What was not defensible was making the trade invisibly.
"""
import inspect
import logging

import pytest

from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf


def _block() -> str:
    src = inspect.getsource(vf)
    i = src.index("#698: SAY IT OUT LOUD")
    return src[i:src.index('_verdict["better_state_available"]', i)]


# --- it is emitted -------------------------------------------------------------------------------

def test_the_recommendation_is_logged():
    assert "_LOG.warning(" in _block()


def test_it_logs_before_writing_the_verdict():
    """The write is what nobody reads; the log must not depend on it."""
    src = inspect.getsource(vf)
    i = src.index("#698: SAY IT OUT LOUD")
    assert src.index("_LOG.warning(", i) < src.index('_verdict["better_state_available"]', i)


def test_it_carries_the_score_delta_and_commit():
    b = _block()
    assert '_better["score"]' in b
    assert '_better["delta"]' in b
    assert '_better["code_state"]' in b


def test_the_commit_is_abbreviated_not_dumped():
    assert '[:12]' in _block()


def test_it_says_what_ships_instead():
    assert "the bounded escape ships the LAST round" in _block()


def test_it_quotes_the_population_figure():
    """One run's recommendation is easy to dismiss; 24 of 39 is not."""
    assert "24 of 39 runs deliver worse than their own best" in _block()


# --- it cannot break the gate ---------------------------------------------------------------------

def test_the_logging_is_best_effort():
    b = _block()
    assert "try:" in b and "except Exception:" in b


def test_a_logging_failure_does_not_skip_the_verdict_write():
    """The except must swallow, not return — the verdict keys are still wanted."""
    b = _block()
    tail = b[b.index("except Exception:"):]
    assert "pass" in tail
    assert "return" not in tail


def test_the_module_logger_exists():
    assert isinstance(vf._LOG, logging.Logger)


# --- the computation is untouched -----------------------------------------------------------------

def test_the_margin_is_unchanged():
    sig = inspect.signature(vf.better_state_available_641)
    assert sig.parameters["margin"].default == 0.02


def test_it_still_ranks_on_the_live_score():
    """#641's own note: blocking_average is #500's best-of merge, not this capture."""
    doc = vf.best_recorded_round_641.__doc__ or ""
    assert "blocking_average_live" in doc


def test_the_verdict_keys_are_still_written():
    src = inspect.getsource(vf)
    assert '_verdict["better_state_available"] = _better' in src
    assert '_verdict["better_state_note"]' in src


# --- provenance -------------------------------------------------------------------------------------

def test_the_dead_artifact_measurement_is_recorded():
    flat = " ".join(_block().replace("#", " ").split())
    assert "which NOTHING reads" in flat
    assert "never looks at these keys" in flat


def test_the_r146_validation_is_recorded():
    flat = " ".join(_block().replace("#", " ").split())
    assert "r146 validated it end to end" in flat
    assert "delta 0.0246 against a 0.02 margin" in flat


def test_the_policy_question_is_recorded_as_deliberately_open():
    flat = " ".join(_block().replace("#", " ").split())
    assert "stays open on purpose" in flat
    assert "functionally worse" in flat


def test_it_names_the_sibling_findings():
    flat = " ".join(_block().replace("#", " ").split())
    assert "691" in flat and "696" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
