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

def _after(text: str, i: int, until: str = "\n\n") -> str:
    """From an anchor to the next semantic landmark (end of text if absent).

    A window sized in BYTES breaks whenever a comment above it grows; the ratchet in
    test_source_windows_do_not_grow_943 exists because that had already happened.
    """
    j = text.find(until, i)
    return text[i:j if j != -1 else len(text)]


def _block(text: str, i: int) -> str:
    """From the anchor's line to the end of its suite — the first later non-blank
    line indented no deeper than the anchor. This is what a `not in <block>` check
    actually means, and it is exactly what a byte window cannot express: widen it
    and the next sibling statement walks in.
    """
    ls = text.rfind("\n", 0, i) + 1
    rest = text[ls:]
    base = len(rest) - len(rest.lstrip())
    out = []
    for k, line in enumerate(rest.splitlines(keepends=True)):
        if k and line.strip() and (len(line) - len(line.lstrip())) <= base:
            break
        out.append(line)
    return "".join(out)


def test_the_live_average_is_recorded(src):
    assert '"blocking_average_live": _live_average' in src


def test_the_merged_best_is_still_the_headline_number(src):
    """Changing it would move the Part-A metric and every historical comparison with it."""
    assert '"blocking_average": _blocking_average' in src


def test_the_live_average_is_computed_from_THIS_capture_not_the_merge(src):
    i = src.index("_live_blocking = ")
    window = _block(src, i)
    assert "results or []" in window          # the incoming capture
    assert "merged" not in window


def test_the_live_average_applies_the_same_exclusions(src):
    """Advisory and blank screens are out of Part-A — the two numbers must be comparable."""
    i = src.index("_live_blocking = ")
    window = _after(src, i)
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
    window = _after(src, i)
    assert "best-of-captures merge" in window
    assert "worse than the recorded number" in window


def test_an_empty_capture_yields_None_not_a_fake_zero(src):
    """A zero would read as a catastrophic regression; None means 'not measured'."""
    i = src.index("_live_average = ")
    assert "if _live_blocking else None" in _after(src, i)


def test_the_gate_decision_is_untouched(src):
    """#618 reports; it must not newly fail a run on a capture artefact."""
    assert "_merged_passed" in src
    assert "passed" in src and "record_exceeds_live_by" in src
    i = src.index("record_exceeds_live_by")
    assert "_merged_passed" not in _after(src, i)


def test_the_measurements_are_recorded(src):
    flat = " ".join(src.replace("#", " ").split())
    assert "24 of 39 runs" in flat and "+0.44" in flat
    assert "19 improved" in flat and "10 ended WORSE" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
