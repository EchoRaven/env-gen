r"""#1203ji: the mutation harness reported a harness error as a surviving mutation.

Falsification by mutation is how every guard in this repo is verified, and until now the
harness was retyped by hand for each patch. It failed TWICE on 2026-10-14 and both times
the failure looked like a finding:

  * a `sed` whose quoting never matched applied NOTHING, and the harness printed
    `MISSED <- M4 the original relative-URL advice lost`. That read as "my test is too
    weak", so I went to tighten the test; the mutation CAUGHT the moment it was re-applied
    in python with a count assertion.
  * a mutation replacing `try:` with `if False:` left an orphan `except`, so pytest could
    not COLLECT the module — a syntax error in the mutant, printed as `MISSED`.

`verify_shipped_fixes.py` beside it already states the rule this breaks: a check that
cannot tell "looked and found nothing" from "never looked" reports a silence as a pass.
#826's header says the other half — "a check that lives in a habit is not a check".

So `scripts/mutate.py` has four verdicts and blurs none of them: CAUGHT, MISSED,
NOT APPLIED (the anchor did not appear exactly once) and BROKEN (the mutant does not
compile, or the module cannot be collected). The last two are harness errors and say
NOTHING about the test.

★ It also refuses a RED baseline: against a failing test file every mutation reads CAUGHT,
which is the same false comfort one level up — and that one I had never checked at all.
"""
import importlib.util
import os
import sys

import pytest

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TOOL = os.path.join(os.path.dirname(_AGENT), "scripts", "mutate.py")


def _load():
    spec = importlib.util.spec_from_file_location("_mutate_1203ji", _TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def tool():
    assert os.path.exists(_TOOL), "scripts/mutate.py is gone"
    return _load()


@pytest.fixture
def target(tmp_path):
    p = tmp_path / "subject.py"
    p.write_text("def f():\n    return 1\n", encoding="utf-8")
    return p


def _spec(target, mutations):
    return {"file": str(target), "test": "unused", "mutations": mutations}


def _run(tool, spec, results, monkeypatch, capsys):
    """`results` is consumed one per _run_test call; the first is the baseline."""
    seq = list(results)
    monkeypatch.setattr(tool, "_run_test", lambda _t: seq.pop(0))
    monkeypatch.setattr(sys, "argv", ["mutate.py", "-"])
    import io
    import json as _json
    monkeypatch.setattr(sys, "stdin", io.StringIO(_json.dumps(spec)))
    code = tool.main(["mutate.py", "-"])
    return code, capsys.readouterr().out


def test_an_anchor_that_matches_nothing_is_not_a_missed_mutation(tool, target,
                                                                monkeypatch, capsys):
    """★ THE TICKET, first half. Today's `sed` failure, exactly: the anchor is absent, so
    nothing was tested, and calling that MISSED sends a reader to tighten a test that is
    already fine."""
    code, out = _run(tool, _spec(target, [{"label": "ghost", "find": "not-in-the-file",
                                           "replace": "x"}]),
                     [(True, "baseline ok")], monkeypatch, capsys)
    assert "NOT APPLIED" in out, out
    assert "anchor appears 0 time(s)" in out, out
    assert "MISSED" not in out, "a harness error was reported as a surviving mutation"
    assert code != 0


def test_an_anchor_that_matches_twice_is_also_not_applied(tool, tmp_path,
                                                          monkeypatch, capsys):
    """An ambiguous anchor would mutate BOTH sites, so the result is not about the
    mutation the author described."""
    p = tmp_path / "twice.py"
    p.write_text("a = 1\nb = 1\n", encoding="utf-8")
    code, out = _run(tool, _spec(p, [{"label": "ambiguous", "find": "= 1", "replace": "= 2"}]),
                     [(True, "baseline ok")], monkeypatch, capsys)
    assert "NOT APPLIED" in out and "2 time(s)" in out, out
    assert code != 0


def test_a_mutant_that_does_not_compile_is_broken_not_missed(tool, target,
                                                             monkeypatch, capsys):
    """★ THE TICKET, second half. Today's `try:` -> `if False:` mutation, which left an
    orphan `except` and printed MISSED."""
    code, out = _run(tool, _spec(target, [{"label": "syntax", "find": "return 1",
                                           "replace": "return return"}]),
                     [(True, "baseline ok")], monkeypatch, capsys)
    assert "BROKEN" in out and "does not compile" in out, out
    assert "MISSED" not in out, out
    assert code != 0


def test_a_collection_failure_is_broken_too(tool, target, monkeypatch, capsys):
    """`_run_test` returns None when pytest could not collect; that is not evidence about
    the test either."""
    code, out = _run(tool, _spec(target, [{"label": "collect", "find": "return 1",
                                           "replace": "return 2"}]),
                     [(True, "baseline ok"), (None, "error during collection")],
                     monkeypatch, capsys)
    assert "BROKEN" in out and "collection failed" in out, out
    assert code != 0


def test_a_real_miss_is_still_reported_as_a_miss(tool, target, monkeypatch, capsys):
    """WITHOUT THIS THE TOOL IS USELESS: a mutant that compiles, runs and leaves the test
    GREEN is the finding the whole exercise exists for."""
    code, out = _run(tool, _spec(target, [{"label": "real gap", "find": "return 1",
                                           "replace": "return 2"}]),
                     [(True, "baseline ok"), (True, "1 passed")], monkeypatch, capsys)
    assert "MISSED" in out, out
    assert "NOT APPLIED" not in out and "BROKEN" not in out, out
    assert code != 0


def test_a_caught_mutation_exits_zero(tool, target, monkeypatch, capsys):
    code, out = _run(tool, _spec(target, [{"label": "good", "find": "return 1",
                                           "replace": "return 2"}]),
                     [(True, "baseline ok"), (False, "1 failed")], monkeypatch, capsys)
    assert "CAUGHT" in out and code == 0, (code, out)


def test_a_red_baseline_refuses_to_mutate(tool, target, monkeypatch, capsys):
    """★ The false comfort one level up, which I had never checked: against a red test file
    every mutation reads CAUGHT and the run looks perfect."""
    code, out = _run(tool, _spec(target, [{"label": "x", "find": "return 1",
                                           "replace": "return 2"}]),
                     [(False, "1 failed")], monkeypatch, capsys)
    assert "refusing to mutate" in out, out
    # ★ NOT `"CAUGHT" not in out`: the refusal SENTENCE contains the word ("every mutation
    # reads CAUGHT"), so that assertion was satisfied by my own prose and went red for the
    # wrong reason. The verdict table prints "  <VERDICT>  <label>", so pin that shape.
    assert "\n  CAUGHT" not in out, out
    assert code != 0


def test_the_target_is_restored_and_the_hash_is_checked(tool, target, monkeypatch, capsys):
    """A mutation harness that leaves the tree dirty poisons every later measurement — the
    reason each hand-rolled version carried a trap and a checksum line."""
    original = target.read_text(encoding="utf-8")
    code, out = _run(tool, _spec(target, [{"label": "a", "find": "return 1",
                                           "replace": "return 2"}]),
                     [(True, "ok"), (False, "1 failed")], monkeypatch, capsys)
    assert target.read_text(encoding="utf-8") == original
    assert "target restored" in out, out


def test_it_says_nothing_rather_than_passing_on_an_empty_mutation_list(tool, target,
                                                                      monkeypatch, capsys):
    """An empty list must not exit 0: "no mutations ran" is not "every mutation caught",
    which is the same silence-as-a-pass this tool exists to refuse."""
    code, out = _run(tool, _spec(target, []), [(True, "ok")], monkeypatch, capsys)
    assert code != 0, out


def test_the_second_mutation_sees_a_clean_file(tool, tmp_path, monkeypatch, capsys):
    """★ WHY THE PER-MUTATION RESTORE EXISTS, and the gap a one-mutation spec cannot show.

    Deleting the restore inside the loop left every test here green, because the outer
    `finally` still restores once at the end — so the FINAL state was right while mutation
    2 had been applied on top of mutation 1. Two mutations are the smallest spec that can
    tell the difference: with the restore gone, the second anchor is still present (its
    text is untouched by the first mutation) but the file also carries the first mutation,
    so what ran was never the mutation the author described. Found by mutating this
    harness with this harness (#1203ji's M6).
    """
    p = tmp_path / "two.py"
    p.write_text("A = 1\nB = 2\n", encoding="utf-8")
    seen = []

    def _fake(_t):
        seen.append(p.read_text(encoding="utf-8"))
        return (False, "1 failed") if len(seen) > 1 else (True, "ok")
    monkeypatch.setattr(tool, "_run_test", _fake)
    import io
    import json as _json
    spec = {"file": str(p), "test": "unused", "mutations": [
        {"label": "first", "find": "A = 1", "replace": "A = 9"},
        {"label": "second", "find": "B = 2", "replace": "B = 9"}]}
    monkeypatch.setattr(sys, "stdin", io.StringIO(_json.dumps(spec)))
    code = tool.main(["mutate.py", "-"])
    out = capsys.readouterr().out
    assert code == 0, out
    # seen[0] is the baseline, seen[1] the first mutant, seen[2] the second
    assert len(seen) == 3, seen
    assert seen[1] == "A = 9\nB = 2\n", seen[1]
    assert seen[2] == "A = 1\nB = 9\n", (
        "the second mutant also carried the first mutation, so neither result is about "
        "the mutation its label names: %r" % seen[2])
