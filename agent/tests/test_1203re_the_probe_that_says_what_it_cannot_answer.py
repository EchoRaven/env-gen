"""#1203re — bake the triage into the detector, and make it say what it CANNOT answer.

`defect_shapes.py` reports a D1 candidate per `float(x.get(<field>) or 0)`. On 2026-10-21 all
26 were triaged by hand, and the two kinds needed DIFFERENT evidence:

    visual_fidelity.py:8172   cleared by its GUARD — the line above excludes advisory+blank
    visual_fidelity.py:5321   no guard; cleared only by DATA — 3667 screen records on disk,
                              zero missing `similarity`

A guard-only reading leaves 5321 open; a data-only reading never explains why 8172 is safe.
The second kind is measurable, so the detector now measures it instead of leaving it to
whoever runs the tool next.

NOT A NAME HEURISTIC. Guessing "fields called *_count are counts, so `or 0` is fine" is
brittle in the direction that hides defects. Absence is counted.

WHAT COUNTS AS ABSENT — SIBLINGS: within one array of record dicts, if at least one element
carries the field, the elements lacking it are exactly the cases `or 0` fires on. An array
where every element has it cannot fire.

AND THE CASE THE PROBE CANNOT ANSWER, which is why this file exists: a field nested as
`{"llm": {"usd": ...}}` has NO siblings. The first draft reported "field never seen" for it —
false, since `usd` is present in 76 of 102 run_budget.json records. Saying "never seen" when
the truth is "present but not comparable" is the silence-as-a-pass shape, so the probe now
distinguishes three answers and only one of them retires a candidate.
"""
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "defect_shapes.py"


def _probe(monkeypatch, tmp_path, tree):
    """Load the script's probe and run it against a synthetic corpus in tmp_path."""
    import ast as _ast
    src = SCRIPT.read_text(encoding="utf-8")
    # Extract the cache and the probe BY AST, not by string slicing. The first version sliced
    # from the cache assignment to the next `def d3(` -- which sits EARLIER in the file, so
    # the search found nothing, the slice ran to EOF, and the exec pulled in module-level code
    # needing `ROOT`. A slice is not a parse unit; the same mistake the #1203ra AST test made.
    _mod = _ast.parse(src)        # NOT `tree`: that name is this helper's corpus argument
    want = [n for n in _mod.body
            if (isinstance(n, _ast.FunctionDef) and n.name == "_field_absence_1203re")
            or (isinstance(n, _ast.Assign)
                and any(getattr(t, "id", "") == "_CORPUS_CACHE_1203RE" for t in n.targets))]
    assert len(want) == 2, "expected the cache and the probe, got %d" % len(want)
    ns = {"__name__": "probe", "os": __import__("os"), "json": json,
          "glob": __import__("glob")}
    exec(compile(_ast.Module(body=want, type_ignores=[]), "<probe>", "exec"), ns)
    fn = ns["_field_absence_1203re"]
    ns["_CORPUS_CACHE_1203RE"].clear()
    d = tmp_path / "generated" / "run1"
    d.mkdir(parents=True)
    (d / "a.json").write_text(json.dumps(tree), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return fn


def test_an_array_where_every_record_has_it_cannot_fire(monkeypatch, tmp_path):
    """★ The similarity class: 0 absent means the `or 0` fallback is unreachable."""
    fn = _probe(monkeypatch, tmp_path,
                {"screens": [{"similarity": 0.4}, {"similarity": 0.9}, {"similarity": 0.1}]})
    present, absent, _files, _any = fn("similarity")
    assert (present, absent) == (3, 0)


def test_a_record_missing_the_field_is_counted_as_absent(monkeypatch, tmp_path):
    """THE COUNTER-PROOF. A probe that always answered 0-absent would retire every
    candidate, which is worse than not probing at all."""
    fn = _probe(monkeypatch, tmp_path,
                {"screens": [{"similarity": 0.4}, {"name": "x"}, {"similarity": 0.1}]})
    present, absent, _files, _any = fn("similarity")
    assert (present, absent) == (2, 1)


def test_a_field_nested_in_a_dict_is_NOT_reported_as_never_seen(monkeypatch, tmp_path):
    """★ The bug this file is named for. `{"llm": {"usd": ...}}` has no siblings, so the
    sibling test cannot answer -- but the field IS there, and claiming otherwise would be a
    silence read as an answer."""
    fn = _probe(monkeypatch, tmp_path, {"llm": {"usd": 93.43}, "caps": {}})
    present, absent, _files, anywhere = fn("usd")
    assert (present, absent) == (0, 0), "no array, so the sibling test must stay empty"
    assert anywhere == 1, "but the field must be reported as SEEN"


def test_a_field_absent_everywhere_reports_zero_anywhere(monkeypatch, tmp_path):
    """The third answer: genuinely never in an artifact (a computed, in-memory field)."""
    fn = _probe(monkeypatch, tmp_path, {"screens": [{"name": "x"}], "caps": {}})
    present, absent, _files, anywhere = fn("avg_min")
    assert (present, absent, anywhere) == (0, 0, 0)


def test_the_three_answers_are_distinguishable(monkeypatch, tmp_path):
    """All three must be tellable apart from the return value alone, because the printed
    note branches on them and only `absent == 0 and present > 0` retires a candidate."""
    fn = _probe(monkeypatch, tmp_path,
                {"screens": [{"similarity": 1.0}], "llm": {"usd": 1.0}})
    sib = fn("similarity")      # comparable, cannot fire
    nested = fn("usd")          # present, not comparable
    missing = fn("nope")        # absent
    assert sib[0] > 0 and sib[1] == 0
    assert nested[0] == 0 and nested[3] > 0
    assert missing[0] == 0 and missing[3] == 0
    assert len({sib[:1] + sib[3:], nested[:1] + nested[3:], missing[:1] + missing[3:]}) == 3


# ================================================== #1203rf: the baseline that makes it a monitor
# All 39 candidates were triaged on 2026-10-21 and every one came back NOT a defect. That is
# useful work and it leaves the tool unusable for its actual job: every run reprints the same
# 39, so a genuinely NEW shape arrives invisible inside the noise. `--new-only` reports the
# delta against `scripts/defect_shapes_baseline.json`.
#
# The arithmetic is driven here, not re-implemented: a copy of it would agree with itself no
# matter what the tool did.
def _delta():
    import ast as _ast
    src = SCRIPT.read_text(encoding="utf-8")
    _mod = _ast.parse(src)
    want = [n for n in _mod.body
            if isinstance(n, _ast.FunctionDef) and n.name == "_baseline_delta_1203rf"]
    assert len(want) == 1, "the delta function is gone or renamed"
    ns = {}
    exec(compile(_ast.Module(body=want, type_ignores=[]), "<delta>", "exec"), ns)
    return ns["_baseline_delta_1203rf"]


def test_an_unchanged_tree_is_zero_news():
    new, gone = _delta()({"a|x": 2, "b|y": 1}, {"a|x": 2, "b|y": 1})
    assert (new, gone) == (0, {})


def test_a_second_hit_under_an_EXISTING_label_is_new():
    """★ Why the baseline counts rather than just listing keys. run_budget.py already holds
    two `usd` hits; a THIRD must register, and a key-only baseline would hide it."""
    new, _gone = _delta()({"run_budget.py|usd": 3}, {"run_budget.py|usd": 2})
    assert new == 1


def test_a_brand_new_label_is_new():
    new, _gone = _delta()({"a|x": 1, "new.py|zzz": 1}, {"a|x": 1})
    assert new == 1


def test_a_vanished_baseline_hit_is_reported_not_silently_dropped():
    """A hit disappearing is information too -- either a fix or detector drift. #1202jn's
    repair made D6 go quiet ON PURPOSE, so the tool must say which keys went away rather
    than quietly reporting 'nothing new'."""
    new, gone = _delta()({"a|x": 1}, {"a|x": 1, "b|y": 2})
    assert new == 0
    assert gone == {"b|y": 2}


def test_news_and_vanishing_are_counted_independently():
    """A run that both fixes one shape and introduces another must not net to zero."""
    new, gone = _delta()({"a|x": 1, "c|z": 1}, {"a|x": 1, "b|y": 1})
    assert new == 1 and gone == {"b|y": 1}


def test_the_shipped_baseline_matches_the_current_tree():
    """The baseline is only useful while it is true. If this fails, either a new candidate
    appeared (triage it) or one was fixed (regenerate the baseline and say which)."""
    import json as _json
    base = _json.loads((ROOT / "scripts" / "defect_shapes_baseline.json")
                        .read_text(encoding="utf-8"))
    counts = base.get("counts") or {}
    assert sum(counts.values()) == 39, (
        "the shipped baseline no longer totals the 39 triaged hits: %d" % sum(counts.values()))
    assert base.get("_triage_2026_10_21"), "the baseline must carry WHY each class was cleared"


def test_a_count_that_DROPS_but_stays_present_never_goes_negative():
    """★ Found by mutation RFA. Removing `max(0, ...)` survived every test above, because the
    vanished key in those cases was absent from `seen` entirely and so never entered the sum.
    The clamp only matters when a key's count FALLS while staying present -- two of three
    `usd` hits fixed, say. Without it that contributes -2 and masks a genuine new hit
    elsewhere, so the monitor reports 'nothing new' on exactly the run that has news."""
    new, gone = _delta()({"run_budget.py|usd": 1}, {"run_budget.py|usd": 3})
    assert new == 0, "a dropped count must not produce negative news"
    assert gone == {"run_budget.py|usd": 2}


def test_a_drop_in_one_key_cannot_cancel_news_in_another():
    """The same defect at the level that matters: one shape fixed, one introduced."""
    new, gone = _delta()({"a.py|x": 1, "b.py|y": 1}, {"a.py|x": 3})
    assert new == 1, "the new hit in b.py must survive the drop in a.py"
    assert gone == {"a.py|x": 2}


def _keyfn():
    import ast as _ast
    src = SCRIPT.read_text(encoding="utf-8")
    _mod = _ast.parse(src)
    want = [n for n in _mod.body
            if isinstance(n, _ast.FunctionDef) and n.name == "_baseline_key_1203rf"]
    assert len(want) == 1, "the key function is gone or renamed"
    ns = {"pathlib": __import__("pathlib")}
    exec(compile(_ast.Module(body=want, type_ignores=[]), "<key>", "exec"), ns)
    return ns["_baseline_key_1203rf"]


def test_the_key_includes_the_LABEL_not_just_the_file():
    """★ Found by mutation RFD. Every delta test above passes pre-made keys, so the key
    function itself was never driven. Keyed on filename alone, every hit in one file
    collapses into one bucket and a NEW shape in an already-flagged file never registers --
    and visual_fidelity.py alone holds ten."""
    k = _keyfn()
    assert k("a/b/visual_fidelity.py", "similarity") != k("a/b/visual_fidelity.py", "blank")
    assert "similarity" in k("x/visual_fidelity.py", "similarity")


def test_the_key_ignores_the_directory_so_a_move_is_not_news():
    """Keyed on the basename: moving a file must not make every hit in it look new."""
    k = _keyfn()
    assert k("old/dir/run_budget.py", "usd") == k("new/place/run_budget.py", "usd")


def test_the_key_is_insensitive_to_surrounding_whitespace():
    k = _keyfn()
    assert k("p/x.py", " usd ") == k("p/x.py", "usd")
