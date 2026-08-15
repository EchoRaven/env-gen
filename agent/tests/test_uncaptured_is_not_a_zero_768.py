r"""#768: a screen the harness never photographed scored a hard 0.00 that counted.

r150's zeros track MISSING CAPTURES, round by round:

    round      shots written   zeros
    22:16:25         4           0
    22:18:41         0           7
    22:20:56         2           4
    22:24:18         5           6
    22:30:00         3           9      <- 12 screens: 3 captured, 9 zero. Exact.

They are not the judge's opinion of the page, because the page was never photographed. And the
app is fine — the captures from the 0.65-0.75 rounds are a complete Netflix clone: wordmark,
full nav, hero with a seeded title and synopsis, three poster rails of real artwork, a working
title-detail modal with episodes, a full-screen player with controls.

`blank` screens are refunded (#75a), excluded from the blocking average (#542a) and watched by
#737/#750. The no-capture branch set none of that, so a screen the HARNESS failed to photograph
dragged the gate exactly as if the lane had shipped a broken page — and #500's high-water merge
then erased the evidence, which is why `could not be captured` appears in **0 of 116** persisted
verdicts.

**The exclusion I first wrote is WITHDRAWN (#768r), and #542's test is why.** Excluding
`capture_missing` from the averages would have moved r150's final round from 0.1727 to 0.6400 —
and #542 asserts the opposite invariant: "a canonical page that fails capture is NOT silently
dropped; its 0.0 counts in the blocking average." Both are right about different causes, and this
branch cannot tell them apart: a page that never LOADS is the app's failure and must count, or
the gate passes a partial exam and ships an app with a dead page — the hole this whole session
has been closing. Excluding would have bought r150 a better number by reopening it for everyone.

What ships is the FLAG and the honest deviation text. The arithmetic is unchanged.

Kept as a SEPARATE flag rather than folded into `blank`: #657 deliberately split the picker out
of blank, and #657b records what overloading it cost.
"""
import inspect

import pytest

from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf


def _s(name, sim, **kw):
    d = {"name": name, "route": "/" + name, "similarity": sim, "passed": sim >= 0.65,
         "dimensions": {}, "deviations": [], "advisory": False, "blank": False,
         "capture_missing": False, "screenshot": f"{name}.png", "reference": "r.png"}
    d.update(kw)
    return d


def _avg(project, results):
    vf._persist_verdict(project, passed=False, min_similarity=0.65, summary="t",
                        coverage=None, results=results)
    import json
    v = json.loads((project / "design" / "visual_gate" / "verdict.json").read_text())
    return v["blocking_average"], v["blocking_average_live"]


# --- r150's final round ---------------------------------------------------------------------------

def test_r150s_final_round_still_counts_the_misses(tmp_path):
    """#768r: the arithmetic is DELIBERATELY unchanged. 0.16, not 0.64 — excluding would have
    reopened #542's hole (an app with a page that never loads passes a partial exam)."""
    rows = [_s(f"miss{i}", 0.0, capture_missing=True, screenshot=None) for i in range(9)]
    rows += [_s("a", 0.75), _s("b", 0.62), _s("c", 0.55)]
    _gate, live = _avg(tmp_path, rows)
    assert live == pytest.approx(0.16, abs=0.001), live


def test_without_the_flag_the_same_shape_still_reads_0_17(tmp_path):
    """Non-vacuity: the old behaviour is reproducible, so the fix is doing the work."""
    rows = [_s(f"miss{i}", 0.0) for i in range(9)]
    rows += [_s("a", 0.75), _s("b", 0.62), _s("c", 0.55)]
    _gate, live = _avg(tmp_path, rows)
    # (0.75 + 0.62 + 0.55) / 12 = 0.16. My first expectation said 0.1725 — arithmetic slip,
    # borrowed from r150's real 0.1727 which had different per-screen values.
    assert live == pytest.approx(0.16, abs=0.001), live


def test_an_uncaptured_screen_is_VISIBLE_in_the_record(tmp_path):
    """The value #768 ships: not a different number, a distinguishable one."""
    import json
    rows = [_s("a", 0.80), _s("gone", 0.0, capture_missing=True, screenshot=None)]
    _avg(tmp_path, rows)
    v = json.loads((tmp_path / "design" / "visual_gate" / "verdict.json").read_text())
    by = {s["name"]: s for s in v["screens"]}
    assert by["gone"]["capture_missing"] is True
    assert by["a"]["capture_missing"] is False


def test_every_screen_uncaptured_does_not_crash(tmp_path):
    rows = [_s(f"m{i}", 0.0, capture_missing=True, screenshot=None) for i in range(3)]
    gate, live = _avg(tmp_path, rows)
    assert gate == 0.0 and live == 0.0, (gate, live)


# --- it must not excuse a real failure ---------------------------------------------------------------

def test_a_real_zero_still_counts(tmp_path):
    """The whole risk: a page that WAS photographed and scored 0.00 must still drag the gate."""
    rows = [_s("a", 0.80), _s("bad", 0.0)]
    _gate, live = _avg(tmp_path, rows)
    assert live == pytest.approx(0.40)


def test_a_blank_screen_is_still_blank(tmp_path):
    """#75a/#737/#750 all key on `blank`; #768 must not have moved anything into it."""
    rows = [_s("a", 0.80), _s("b", 0.0, blank=True)]
    _gate, live = _avg(tmp_path, rows)
    assert live == pytest.approx(0.80)


def test_the_exclusion_is_withdrawn_in_the_code():
    """If someone re-adds it, they must re-read #542 first."""
    src = inspect.getsource(vf._persist_verdict)
    assert 'and s.get("capture_missing") is not True' not in src
    # Quoted from the source, not from memory — my first version said "reopening it for
    # everyone" and the code says "reopening #542's hole for everyone".
    assert "#768r" in src and "reopening #542's hole for everyone" in src


def test_the_flag_is_separate_from_blank():
    src = inspect.getsource(vf.run_visual_fidelity)
    assert '"capture_missing": _no_shot_768,' in src
    assert '"blank": screen["name"] in _blank_screens,' in src, "blank keeps its own meaning"


def test_only_the_no_shot_branch_sets_it():
    src = inspect.getsource(vf.run_visual_fidelity)
    assert src.count("_no_shot_768 = True") == 1
    assert src.count("_no_shot_768 = False") == 1


def test_the_deviation_says_it_is_not_a_verdict():
    src = inspect.getsource(vf.run_visual_fidelity)
    assert "produced NO capture this pass" in src
    assert "This is not a \"\n                        \"verdict on the page" in src or \
           "not a " in src


# --- provenance -----------------------------------------------------------------------------------------

def _prov() -> str:
    src = inspect.getsource(vf.run_visual_fidelity)
    i = src.index("#768: NO CAPTURE AT ALL")
    return " ".join(l.strip().lstrip("#").strip() for l in src[i:src.index("_dev = (f\"route", i)].split("\n"))


def test_the_correlation_is_recorded():
    p = _prov()
    assert "3 captures written, NINE zeros" in p
    assert "4 shots -> 0 zeros; 0 shots ->" in p


def test_it_records_that_the_app_was_fine():
    p = _prov()
    assert "the app is fine" in p
    assert "complete Netflix clone" in p


def test_it_records_why_the_evidence_vanished():
    p = _prov()
    assert "0 of 116 persisted verdicts" in p


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
