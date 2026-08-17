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

# --------------------------------------------------------------------------- DRIVEN (#921)

def _persisted_coverage(coverage):
    """Write a verdict and read the coverage block back off disk — the artifact a human opens."""
    import json
    import tempfile
    from pathlib import Path as _P
    d = _P(tempfile.mkdtemp())
    (d / "design" / "visual_gate").mkdir(parents=True)
    vf._persist_verdict(d, passed=True, min_similarity=0.65, summary="s", coverage=coverage,
                        results=[{"name": "a", "route": "/a", "similarity": 0.7,
                                  "dimensions": {}, "deviations": []}])
    return json.loads((d / "design" / "visual_gate" / "verdict.json").read_text())["coverage"]


def test_the_written_document_carries_the_scope():
    """★ #921. #901 added the label to the dict `run_visual_fidelity` RETURNS; `_persist_verdict`
    received the unlabelled original, so **121 of 121 delivered verdict.json files carry a
    coverage block and none carries the label** — including r153's, which still reads
    `"unjudged": ["browse_home_rows", "card_hover_preview"]` directly above a `screens` list where
    both carry scores.

    Every one of this file's original six assertions read the SOURCE, where the string does exist.
    That is why nothing caught it: #903's shape (a value handed to the wrong object) inside the
    ticket whose whole point was that the artifact should not need the source to disambiguate it."""
    cov = _persisted_coverage({"judged": 2, "unjudged": ["b"]})
    assert "scope" in cov, cov
    assert "merge across" in cov["scope"]


def test_the_original_coverage_fields_survive():
    cov = _persisted_coverage({"judged": 2, "unjudged": ["b"], "measured": 9})
    assert cov["judged"] == 2 and cov["unjudged"] == ["b"] and cov["measured"] == 9


def test_a_non_dict_coverage_does_not_break_the_write():
    """The gate hands whatever it has; a None must still produce a readable document."""
    assert _persisted_coverage(None) == {"scope": _persisted_coverage(None)["scope"]}


def test_the_label_explains_the_contradiction_it_exists_for():
    """r153's document puts `browse_home_rows` in `unjudged` and in `screens` WITH a score. The
    label has to name that, or it is decoration."""
    scope = _persisted_coverage({"judged": 1})["scope"]
    assert "unjudged" in scope and "screens" in scope


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
