r"""#893: an enforcer for the judge's over-claiming that does not need vision.

#781 and #857 tell the judge not to report what it cannot point to in the reference. **Both are
prompt rules** — the "claim with no enforcer" shape this whole session has been mining, and I
fixed a prompt problem with a prompt.

A content-matching enforcer is not the answer either, and that is recorded as do-not-build: the
careful version reported 5 of 6 controls "present" by matching word tokens across a 300 KB
concatenation, including all three the judge had flagged.

★ **What can be checked without vision is self-consistency.** `code_state` (#621) stamps the tree
each capture scored, so two rounds at the same sha are the *same input*. A different `missing`
list, or a score moving ≥0.10, across them is the judge being non-deterministic — which is exactly
the over-claim signature: an element "missing" in one round and not the next, with no code in
between.

**Honest limit, stated in the code:** only **7 of 119** corpus verdicts carry a `code_state`, so
this cannot be validated against history. #621 is recent; every verdict from here carries one, so
its first real signal is run 152. It is **recorded in the verdict, not acted on** — a detector
whose precision is unmeasured must not gate anything.
"""
import inspect
import json
import pathlib

import pytest

from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf


def _src():
    return inspect.getsource(vf)


def _prose():
    """Whitespace-normalised source, for assertions about what a MESSAGE says.

    Log strings are split across lines by implicit concatenation, so any phrase that spans the
    break fails on formatting rather than on content — #887 hit this and so did this file. Tests
    about wording read this; tests about code structure read `_src()`.

    ★ It handles line WRAP, not literal boundaries: `"... a " "b ..."` normalises to `... a " "b`,
    with the quotes still in the middle. An assertion has to stay inside one literal."""
    return " ".join(inspect.getsource(vf).split())


def test_the_check_exists_and_is_keyed_on_the_tree():
    src = _src()
    assert "#893: the judge contradicting ITSELF" in src
    assert "_prior_code_state_893 == _head_sha" in src


def test_it_compares_missing_sets_and_scores():
    src = _src()
    i = src.index("#893: the judge contradicting ITSELF")
    block = src[i:src.index("_verdict = {", i)]
    assert 'get("missing")' in block
    assert "score_delta" in block and "0.10" in block


def test_it_records_rather_than_gates():
    """★ A detector whose precision is unmeasured must not block anything. It lands in the verdict
    as data and in the log as a warning."""
    src = _src()
    i = src.index("#893: the judge contradicting ITSELF")
    block = src[i:src.index("_verdict = {", i)]
    assert "raise" not in block
    assert "_LOG.warning" in block
    assert "judge_unstable_893" in src


def test_it_says_what_the_reader_should_do_with_it():
    """'Unstable' alone invites over-reading. The message has to say that an item appearing and
    vanishing with no code between rounds is noise, not a defect."""
    prose = _prose()
    assert "judge noise, not a defect" in prose
    # ★ asserted as two fragments: the phrase spans a STRING LITERAL boundary
    # (`... weigh \`missing\` " / "accordingly ...`), and collapsing whitespace does not remove
    # the `" "` between them. #887's normalisation handles line wrap; it cannot handle this, and
    # the honest fix is to assert what does not cross the seam.
    assert "weigh `missing`" in prose
    assert "accordingly (#893)" in prose


def test_the_honest_limit_is_recorded_at_the_site():
    """★ The measurement that says this cannot be validated yet belongs next to the code, not only
    in a note — otherwise the next reader treats a silent detector as a clean bill of health."""
    prose = _prose()
    assert "7 of 119 corpus verdicts carry a `code_state`" in prose
    assert "run 152" in prose


def test_the_stamp_it_depends_on_is_still_written():
    """Non-vacuity: without `code_state` on the verdict the whole check is inert."""
    src = _src()
    assert '"code_state": _head_sha' in src


def test_a_failure_in_the_check_cannot_break_the_verdict():
    src = _src()
    i = src.index("#893: the judge contradicting ITSELF")
    block = src[i:src.index("_verdict = {", i)]
    assert "except Exception" in block


@pytest.mark.skipif(not (pathlib.Path(__file__).resolve().parents[1] / "generated").is_dir(),
                    reason="corpus not present")
def test_the_corpus_coverage_claim_still_holds():
    """★ The number in the comment, re-derived (#880's rule). If `code_state` coverage grows past
    a handful, this check becomes validatable and the note should say so."""
    g = pathlib.Path(__file__).resolve().parents[1] / "generated"
    total = stamped = 0
    for r in sorted(g.glob("netflix-web-r*")):
        vg = r / "design/visual_gate"
        if not vg.is_dir():
            continue
        for f in vg.rglob("*.json"):
            try:
                j = json.loads(f.read_text())
            except Exception:
                continue
            total += 1
            if j.get("code_state"):
                stamped += 1
    assert total >= 100, total
    assert stamped <= 20, (
        f"{stamped} of {total} verdicts now carry a code_state — #893 may be validatable; "
        "re-derive its precision instead of leaving it recorded-only")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
