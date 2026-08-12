r"""#618: the record can be better than the code.

Following the self-healing question to its end. Reconstructing the score trajectory from the run
logs — the gate writes `Visual fidelity attempt N/3 FAILED — … (blocking avg X)` on every round,
372 such lines across 40 runs — gives two results.

**Agents do fix things, but a third of the time they end up worse.** Across the 29 runs with two
or more scored rounds: **19 improved, 10 ended WORSE, 0 unchanged**, mean delta **+0.044** over a
median of 13 rounds (r107 +0.34 over 19; r103 **−0.40** over 12).

**And the regressions are invisible on the record.** #500 merges the BEST per-screen score across
captures, so a lane that makes the frontend worse keeps its historical best. Comparing the
persisted `blocking_average` with the LAST live judgement: the record is better than the live
code in **24 of 39 runs**, mean +0.056, up to **+0.44** (r103: recorded 0.58, last live 0.14).

The merge is NOT changed — keeping the best is still the right defence against the transient
capture #500 was built for (env mid-rebuild → every page 0.00), and flipping it would newly fail
runs on a capture artefact. The live number is recorded alongside so the divergence stops being
invisible.
"""
import inspect

import pytest

from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf


@pytest.fixture(scope="module")
def src():
    s = inspect.getsource(vf._persist_verdict)
    return s[s.index("#618"):]


def test_the_live_average_is_recorded(src):
    assert '"blocking_average_live": _live_average' in src


def test_the_merged_best_is_still_the_headline_number(src):
    """Changing it would move the Part-A metric and every historical comparison with it."""
    assert '"blocking_average": _blocking_average' in src


def test_the_live_average_is_computed_from_THIS_capture_not_the_merge(src):
    i = src.index("_live_blocking = ")
    window = src[i:i + 300]
    assert "results or []" in window          # the incoming capture
    assert "merged" not in window


def test_the_live_average_applies_the_same_exclusions(src):
    """Advisory and blank screens are out of Part-A — the two numbers must be comparable."""
    i = src.index("_live_blocking = ")
    window = src[i:i + 300]
    assert 'not s.get("advisory")' in window and 's.get("blank") is not True' in window


def test_a_divergence_is_flagged_with_its_size(src):
    assert '"record_exceeds_live_by"' in src
    assert "_blocking_average - _live_average" in src


def test_the_flag_only_fires_when_the_record_is_HIGHER(src):
    i = src.index("record_exceeds_live_by")
    window = src[i - 200:i]
    assert "- _live_average > 0.01" in window


def test_the_note_says_which_number_is_the_delivered_one(src):
    i = src.index("record_exceeds_live_note")
    window = src[i:i + 400]
    assert "best-of-captures merge" in window
    assert "worse than the recorded number" in window


def test_an_empty_capture_yields_None_not_a_fake_zero(src):
    """A zero would read as a catastrophic regression; None means 'not measured'."""
    i = src.index("_live_average = ")
    assert "if _live_blocking else None" in src[i:i + 220]


def test_the_gate_decision_is_untouched(src):
    """#618 reports; it must not newly fail a run on a capture artefact."""
    assert "_merged_passed" in src
    assert "passed" in src and "record_exceeds_live_by" in src
    i = src.index("record_exceeds_live_by")
    assert "_merged_passed" not in src[i:i + 500]


def test_the_measurements_are_recorded(src):
    flat = " ".join(src.replace("#", " ").split())
    assert "24 of 39 runs" in flat and "+0.44" in flat
    assert "19 improved" in flat and "10 ended WORSE" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
