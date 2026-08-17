r"""#917: the divergence guard degraded as the situation worsened, and went quiet at its worst.

`_persist_verdict` writes `verdict.json` as #500's **best-ever-per-screen** merge, so the persisted
record never falls. #711 exists to say when that record has left the app behind, and #736 correctly
restricted the comparison to the screens THIS capture actually scored — both of #711's historical
firings were composition artefacts, not divergence.

★ But a TOTAL blackout empties that population. `_cmp736` is `[]`, `_g736` is `None`, and the guard
says nothing. Measured as a gradient against a planted prior of four screens at 0.80:

    blank 0/4 → warns (over 4 screens)      blank 2/4 → warns (over 2)
    blank 1/4 → warns (over 3)              blank 3/4 → warns (over 1)
    ★ blank 4/4 → SILENT, and verdict.json still reads passed=True

This is r148's fourth mechanism in the REPORTING path. The memory note it came from says it
outright — *"verdict.json is #500's high-water merge and ERASES the blackout; check live per-screen
scores, not the persisted record"* — and the run that shipped a dead SPA had exactly this: a record
that could not show the round that mattered.

An empty population is not "nothing to compare". It is "everything is gone", which is the loudest
reading available. Fifth appearance this session of an empty container answered as a fact (#902's
blank route as the site root, #907's empty cache as an empty tree, #908's empty `child_meta`,
#916's `None` route key).

Reports only — the release path reads the returned dict, not this file, and #737/#750 hold the
escape side.
"""
import io
import json
import logging
import pathlib
import tempfile

import pytest

from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf


def _round(n_blank: int, total: int = 4):
    """Drive the REAL `_persist_verdict` twice: a good round, then one with `n_blank` blanks."""
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setLevel(logging.WARNING)
    log = logging.getLogger(vf.__name__)
    log.addHandler(handler)
    log.setLevel(logging.WARNING)
    d = pathlib.Path(tempfile.mkdtemp())
    (d / "design" / "visual_gate").mkdir(parents=True)
    good = [{"name": f"s{i}", "route": f"/s{i}", "similarity": 0.80,
             "dimensions": {}, "deviations": []} for i in range(total)]
    vf._persist_verdict(d, passed=True, min_similarity=0.65, summary="good",
                        coverage={}, results=good)
    cur = []
    for i in range(total):
        if i < n_blank:
            cur.append({"name": f"s{i}", "route": f"/s{i}", "similarity": 0.0,
                        "dimensions": {}, "deviations": ["blank"], "blank": True})
        else:
            cur.append({"name": f"s{i}", "route": f"/s{i}", "similarity": 0.05,
                        "dimensions": {}, "deviations": ["broken"]})
    buf.truncate(0)
    buf.seek(0)
    try:
        vf._persist_verdict(d, passed=False, min_similarity=0.65, summary="bad",
                            coverage={}, results=cur)
    finally:
        log.removeHandler(handler)
    verdict = json.loads((d / "design" / "visual_gate" / "verdict.json").read_text())
    return buf.getvalue(), verdict


def test_a_total_blackout_is_announced():
    """★ The defect: 4 of 4 blank used to produce no line at all."""
    out, _ = _round(4)
    assert "TOTAL BLACKOUT" in out, out


def test_every_partial_blackout_still_uses_711():
    """Non-regression across the whole gradient — #917 must add the missing end, not replace
    #736's like-for-like comparison, whose restriction fixed two real false positives."""
    for n in (0, 1, 2, 3):
        out, _ = _round(n)
        assert "#711" in out, (n, out)
        assert "TOTAL BLACKOUT" not in out, (n, out)


def test_the_message_carries_what_the_record_still_claims():
    """The operator's question is "what does the file say, then?" — so the line answers it."""
    out, _ = _round(4)
    assert "4 screen(s)" in out
    assert "0.8000" in out
    assert "passed=True" in out


def test_the_record_really_does_still_pass():
    """★ The premise, asserted rather than assumed: #500's merge keeps every best-ever score, so
    the persisted verdict survives a round in which nothing rendered."""
    _, verdict = _round(4)
    assert verdict["passed"] is True
    assert [s["similarity"] for s in verdict["screens"]] == [0.8] * 4


def test_it_does_not_fire_when_there_is_no_prior():
    """A first round has nothing to overstate; the line would be noise on every clean run."""
    d = pathlib.Path(tempfile.mkdtemp())
    (d / "design" / "visual_gate").mkdir(parents=True)
    buf = io.StringIO()
    h = logging.StreamHandler(buf)
    log = logging.getLogger(vf.__name__)
    log.addHandler(h)
    try:
        vf._persist_verdict(d, passed=False, min_similarity=0.65, summary="first",
                            coverage={}, results=[{"name": "s", "route": "/s",
                                                   "similarity": 0.0, "dimensions": {},
                                                   "deviations": ["blank"], "blank": True}])
    finally:
        log.removeHandler(h)
    assert "TOTAL BLACKOUT" not in buf.getvalue()


def test_it_reports_and_changes_nothing():
    """Same disposition as #711/#736/#641: the release path reads the returned dict, and #737/#750
    hold the escape side. If this ever starts gating, that is a separate decision."""
    import inspect
    src = inspect.getsource(vf._persist_verdict)
    i = src.index("TOTAL BLACKOUT")
    block = src[i - 400:i + 900]
    assert "_LOG.error" in block
    assert "return" not in block.split("_LOG.error")[1][:400]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
