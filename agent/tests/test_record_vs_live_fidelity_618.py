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
import json
import pathlib
import tempfile

import pytest

from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf

def _figure_1203p9(which):
    """The #618 population figure, read from its SINGLE SOURCE.

    #1203p9: this test used to pin the literal "24 of 39 runs". That figure was quoted in seven
    places and went stale in five of them at once, which is the very rot #1202vs is about -- so
    the expectation is now read from the constant the framework emits, and refreshing the
    measurement can never again turn a correct claim into a red test.
    """
    import re as _re1203p9
    from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as _vf1203p9
    _c = (_vf1203p9._RECORD_BEATS_LIVE_1203P9 if which == "A"
          else _vf1203p9._BEST_ROUND_SHORTFALL_1203P9)
    return _re1203p9.search(r"\d+ of \d+ runs", _c).group(0)



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
    assert _figure_1203p9("A") in flat or "_RECORD_BEATS_LIVE_1203P9" in flat
    # the max gap moved with the figure: +0.44 over 39 runs, +0.66 over 79 (#1203p9)
    assert "+0.66" in flat or "+0.44" in flat
    assert "19 improved" in flat and "10 ended WORSE" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))


# --- #1203pg: the divergence is really recorded, driven ------------------------------------------
#
# Every assertion above quotes an expression out of the source. Two mutations left all of them
# verbatim and still changed what gets written:
#
#   * wrapping the `record_exceeds_live_by` assignment in `if False:` -- so the ONE signal that
#     the delivered number came from a best-of-captures merge rather than from this capture
#     vanishes from the verdict, which is #618's whole subject.
#   * averaging over ALL screens instead of the blocking ones, putting the advisory and blank
#     screens back into the number that gets compared against the record.
#
# `_persist_verdict` is a module-level keyword function that writes verdict.json, and #500's
# merge keeps the MAX per screen -- so a high round followed by a low one produces the
# divergence on disk.


def _persist(routes_scores, project=None, blob=b"PNGBYTES"):
    """Run `_persist_verdict` for one capture and return the verdict.json it wrote.

    `routes_scores` maps screen name -> (route, similarity, advisory). Each screen gets its own
    distinct png bytes so #713's identical-capture grouping stays out of the way.
    """
    d = pathlib.Path(project or tempfile.mkdtemp())
    vdir = d / "design" / "visual_gate"
    vdir.mkdir(parents=True, exist_ok=True)
    results = []
    for i, (name, (route, sim, advisory)) in enumerate(routes_scores.items()):
        (vdir / ("%s.png" % name)).write_bytes(blob + bytes([i]))
        row = {"name": name, "route": route, "similarity": sim, "dimensions": {}}
        if advisory:
            row["advisory"] = True
        results.append(row)
    vf._persist_verdict(d, passed=False, min_similarity=0.65, summary="s",
                        coverage={}, results=results)
    return json.loads((vdir / "verdict.json").read_text(encoding="utf-8")), d


def test_the_live_average_is_on_the_record():
    """Non-vacuity: #768r writes it, and the divergence tests below rest on it."""
    v, _ = _persist({"a": ("/a", 0.5, False)})
    assert v.get("blocking_average_live") == 0.5, v.get("blocking_average_live")


def test_advisory_screens_are_excluded_from_the_live_average():
    """The exclusions #618 quotes, driven.

    The advisory score is deliberately NON-ZERO. The first version used 0.0, and a mutation
    that summed over every screen while still dividing by the blocking count got the same
    answer from it -- (0.6 + 0.0) / 1 is 0.6, so the fixture's own numbers agreed with the
    expected result and the test could not see the change. Same trap as a fixture whose input
    ORDER already agrees with the ordering under test.
    """
    v, _ = _persist({"a": ("/a", 0.6, False), "o": ("/o", 0.4, True)})
    assert v["blocking_average_live"] == 0.6, (
        "the advisory screen is in the live average: %s" % v["blocking_average_live"])


def test_a_blank_screen_is_excluded_too():
    """The second half of the same pair of exclusions, with a non-zero score for the same
    reason: a 0.0 blank cannot distinguish "excluded" from "included"."""
    d = pathlib.Path(tempfile.mkdtemp())
    vdir = d / "design" / "visual_gate"
    vdir.mkdir(parents=True)
    for i, n in enumerate(("a", "z")):
        (vdir / ("%s.png" % n)).write_bytes(b"PNG" + bytes([i]))
    vf._persist_verdict(
        d, passed=False, min_similarity=0.65, summary="s", coverage={},
        results=[{"name": "a", "route": "/a", "similarity": 0.6, "dimensions": {}},
                 {"name": "z", "route": "/z", "similarity": 0.4, "blank": True,
                  "dimensions": {}}])
    v = json.loads((vdir / "verdict.json").read_text(encoding="utf-8"))
    assert v["blocking_average_live"] == 0.6, v["blocking_average_live"]


def test_a_lower_second_capture_records_the_divergence():
    """#500's merge keeps the MAX, so the delivered number can be better than the code."""
    _, d = _persist({"a": ("/a", 0.9, False)})
    v, _ = _persist({"a": ("/a", 0.3, False)}, project=d)
    assert v["blocking_average"] == 0.9, "the merge stopped keeping the best"
    assert v["blocking_average_live"] == 0.3, v["blocking_average_live"]
    assert "record_exceeds_live_by" in v, (
        "the record is 0.60 above this capture and the verdict says nothing about it")
    assert abs(v["record_exceeds_live_by"] - 0.6) < 0.001, v["record_exceeds_live_by"]


def test_the_note_says_which_number_was_delivered():
    _, d = _persist({"a": ("/a", 0.9, False)})
    v, _ = _persist({"a": ("/a", 0.3, False)}, project=d)
    note = v.get("record_exceeds_live_note") or ""
    assert "best-of-captures merge" in note, note
    assert "worse than the recorded number" in note, note


def test_an_improving_capture_records_no_divergence():
    """It fires only when the RECORD is higher — an app that got better is not a caveat."""
    _, d = _persist({"a": ("/a", 0.3, False)})
    v, _ = _persist({"a": ("/a", 0.9, False)}, project=d)
    assert "record_exceeds_live_by" not in v, v.get("record_exceeds_live_by")


def test_a_divergence_under_the_threshold_is_not_flagged():
    """0.01 is the floor, so judge jitter does not produce a caveat every round."""
    _, d = _persist({"a": ("/a", 0.900, False)})
    v, _ = _persist({"a": ("/a", 0.895, False)}, project=d)
    assert "record_exceeds_live_by" not in v, v.get("record_exceeds_live_by")
