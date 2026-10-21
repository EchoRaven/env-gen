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
