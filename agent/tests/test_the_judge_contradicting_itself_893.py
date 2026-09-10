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
    """★ What this detector's SILENCE means belongs next to the code, not only in a note —
    otherwise the next reader treats a silent detector as a clean bill of health.

    #1202jp: the limit that was recorded here has since been measured, and the assertions moved
    with it. The invariant is unchanged — the site must still answer "does silence mean
    anything?" — but it now answers with numbers instead of a deferral to run 152.
    """
    prose = _prose()
    assert "7 of 119 corpus verdicts carried a `code_state`" in prose, (
        "the original limit must stay legible: it is why the measurement was needed")
    # asserted as fragments that do not cross a line break: `_prose()` keeps the leading `#`
    # of each comment line, so any phrase spanning the wrap picks up a `# ` in the middle.
    assert "83 (screen, code_state)" in prose, (
        "the measured answer — scores do not drift at an unchanged tree — belongs at the site")
    assert "the spread is 0.000" in prose
    assert "#142's verdict cache" in prose, (
        "and WHY they agree, or a reader concludes the judge is deterministic in general")


def test_the_stamp_it_depends_on_is_still_written():
    """Non-vacuity: without `code_state` on the verdict the whole check is inert."""
    src = _src()
    assert '"code_state": _head_sha' in src


def test_a_failure_in_the_check_cannot_break_the_verdict():
    src = _src()
    i = src.index("#893: the judge contradicting ITSELF")
    block = src[i:src.index("_verdict = {", i)]
    assert "except Exception" in block


@pytest.mark.skipif(not (pathlib.Path(__file__).resolve().parents[2] / "generated").is_dir(),
                    reason="corpus not present")
def test_the_corpus_coverage_claim_still_holds():
    """★ The number in the comment, re-derived (#880's rule). If `code_state` coverage grows past
    a handful, this check becomes validatable and the note should say so."""
    g = pathlib.Path(__file__).resolve().parents[2] / "generated"
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
    if total == 0:
        pytest.skip("the netflix run corpus this claim is measured over is not in "
                    "this checkout — 0 is absence, not a coverage regression")
    assert total >= 100, total
    # #1018: the tripwire measured the wrong quantity. It counted verdicts CARRYING a
    # code_state and fired at 21, but #893 detects non-determinism by comparing two verdicts
    # at the SAME sha — so validation needs REPEATS, not stamps. Measured across the corpus:
    # 21 stamped verdicts, 21 distinct code_states, **zero appearing twice**. No sha has ever
    # been judged more than once, so #893 stays unvalidatable however many stamps accumulate.
    #
    # Counting repeats instead makes the tripwire fire when validation is genuinely possible.
    _by_state: Dict[str, int] = {}
    for r in sorted(g.glob("netflix-web-r*")):
        vg = r / "design/visual_gate"
        if not vg.is_dir():
            continue
        for f in vg.rglob("*.json"):
            try:
                j = json.loads(f.read_text())
            except Exception:
                continue
            _cs = j.get("code_state")
            if _cs:
                _by_state[str(_cs)] = _by_state.get(str(_cs), 0) + 1
    _repeats = sum(1 for _n in _by_state.values() if _n >= 2)
    assert _repeats == 0, (
        f"{_repeats} code_state(s) now appear on 2+ verdicts ({stamped} stamped of {total}) — "
        "#893 is finally validatable: compare the paired verdicts' missing lists and scores "
        "and derive its precision instead of leaving it recorded-only")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))


# --- #900: the finding must outlive the round that made it --------------------------------------

def test_the_finding_is_carried_into_the_append_only_record():
    """★ #893 wrote `judge_unstable_893` only into verdict.json, which `_persist_verdict`
    OVERWRITES every round — so a detection could be erased by the very next round. That is
    #500's evidence-erasure shape, in the detector built to expose the judge's inconsistency.

    r153 makes the cost concrete: **12 rounds ran and exactly one verdict.json survives.** Any
    instability found in rounds 1–11 would be unrecoverable. `rounds.jsonl` is appended one line
    per round and retains what verdict.json loses.

    ★ Asserted by DRIVING the writer, not by reading its source. This test used to require the
    literal `row["judge_unstable_893"]`, which #932 broke by carrying all eight findings in one
    loop instead of one hand-written line each — the generalisation of #900's own reasoning. A
    spelling assertion cannot tell that apart from the finding being dropped (#782, and the third
    time this session: #926 and #621's block locator were the others)."""
    import json as _json
    import tempfile
    from pathlib import Path as _P
    from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as _vf
    _v = _P(tempfile.mkdtemp()) / "design" / "visual_gate"
    _v.mkdir(parents=True)
    _finding = [{"screen": "title_detail", "appeared": ["nav"], "vanished": [],
                 "score_delta": 0.6}]
    _vf._append_round_record_640(_v, {"code_state": "abc", "judge_unstable_893": _finding}, [])
    _vf._append_round_record_640(_v, {"code_state": "def"}, [])          # a clean later round
    _rows = [_json.loads(x) for x in (_v / "rounds.jsonl").read_text().splitlines() if x.strip()]
    assert _rows[0]["judge_unstable_893"] == _finding
    assert "judge_unstable_893" not in _rows[1], "a clean round adds no empty key"
    assert len(_rows) == 2, "and it must not have erased the round that found it"


def test_it_is_still_written_to_the_verdict_too():
    """Both, not either: verdict.json is what a human opens first."""
    assert 'judge_unstable_893"] = _unstable_893' in _src()


def test_the_append_only_record_is_the_one_that_retains_history():
    """Non-vacuity for the premise, from r153: verdict.json is overwritten, rounds.jsonl is not."""
    src = _src()
    assert 'open(Path(vdir) / "rounds.jsonl", "a"' in src, "must be append mode"
    assert '"code_state": _head_sha' in src, "each round must carry the sha #893 keys on"


def test_r153_proved_the_comparison_is_reachable():
    """★ The question this check existed to answer, settled with real data rather than argued.

    r153: 12 rounds, 11 distinct code_states, and `41b11425e7` spanning TWO — so #893 had a real
    opportunity and stayed silent because both rounds scored **identically** (merged 0.6771, live
    0.627, delta 0.0000). A correct negative, not an inert detector — and incidentally the first
    evidence this session that the judge is DETERMINISTIC at an unchanged tree."""
    import json
    import pathlib as _p
    rj = (_p.Path(__file__).resolve().parents[1]
          / "generated/netflix-web-r153/design/visual_gate/rounds.jsonl")
    if not rj.is_file():
        pytest.skip("r153 corpus not present")
    rows = [json.loads(l) for l in rj.read_text().splitlines() if l.strip()]
    assert len(rows) >= 10, len(rows)
    same = [r for r in rows if str(r.get("code_state", "")).startswith("41b11425e7")]
    assert len(same) == 2, same
    a, b = same
    assert a.get("blocking_average_live") == b.get("blocking_average_live")
    assert a.get("blocking_average") == b.get("blocking_average")
