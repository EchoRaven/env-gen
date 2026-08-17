r"""#901: `screens` and `coverage` describe different sets and the document did not say so.

Found by reading r153's delivered output rather than my own diff — the first thing this session
mined from a *successful* run.

    verdict.screens      12 entries, incl. browse_home_rows 0.40 and card_hover_preview 0.30
    coverage.unjudged    lists both of those as never judged
    rounds.jsonl         the last round judged 10 screens; those two were not among them

`screens` is **#500's merge** (this round plus anything a prior round scored). `coverage` is
computed from **this round's `results`**. So a screen can carry a score in the same file that
calls it unjudged.

★ **Both halves are individually correct.** `visual_gate_verdict(results=results, …)` evaluates
the current round on purpose, and #351 marks this coverage block reporting-only, so nothing is
mis-gated. **The defect is in the document.** It contradicts itself, and it misled me into filing
a gate defect that does not exist — I claimed a merged blocking screen would fail the gate before
checking that `coverage` does not gate at all. The artifact a human opens should not need the
source to disambiguate it.

Fixed by labelling the scope where it is written, and by changing the gate's own wording from
*"never judged"* to *"not judged in this round"*, which is what it means.
"""
import inspect

import pytest

from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf


def test_the_persisted_coverage_carries_its_scope():
    src = inspect.getsource(vf)
    assert '"scope": "this round' in src
    assert "#500's merge across" in src or "merge across" in src


def test_the_gate_no_longer_says_never():
    """★ 'never judged' is false for a screen judged in round 3 and not re-captured in round 8.
    The rule is about THIS round; the wording now says so."""
    src = inspect.getsource(vf)
    assert "were never judged" not in src
    assert "were not judged in this round" in src


def test_the_coverage_block_is_still_the_real_dict():
    """The scope label must be additive — dropping the measured/judged/unjudged keys would trade
    a wording bug for a data loss."""
    src = inspect.getsource(vf)
    assert "**(_coverage if isinstance(_coverage, dict) else {})" in src


def test_coverage_still_does_not_gate():
    """#351's property, re-pinned: this block reports. If it ever starts gating, the merged/round
    distinction stops being cosmetic and #901 must be revisited."""
    src = inspect.getsource(vf)
    assert "visual_gate_verdict(results=results" in src, "the gate reads results, not merged"


def test_the_gate_and_the_merge_read_different_sets_on_purpose():
    """★ Non-vacuity for the whole finding: if these ever converge, the document stops
    contradicting itself and this ticket is obsolete rather than wrong."""
    src = inspect.getsource(vf)
    gate = src.index("visual_gate_verdict(results=results")
    merge = src.index("#500: merge with the prior persisted verdict")
    assert gate < merge, "the gate must still run before the merge for this to be the shape"


def test_r153_shows_the_contradiction_it_fixes():
    """The observation, pinned against the artifact so the claim can be re-checked."""
    import json
    import pathlib
    vg = (pathlib.Path(__file__).resolve().parents[1]
          / "generated/netflix-web-r153/design/visual_gate")
    if not (vg / "verdict.json").is_file():
        pytest.skip("r153 corpus not present")
    v = json.loads((vg / "verdict.json").read_text())
    scored = {str(s.get("name")): s.get("similarity") for s in (v.get("screens") or [])}
    unjudged = set((v.get("coverage") or {}).get("unjudged") or [])
    both = sorted(set(scored) & unjudged)
    assert both == ["browse_home_rows", "card_hover_preview"], both
    assert all(scored[n] is not None for n in both), "they really do carry scores"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
