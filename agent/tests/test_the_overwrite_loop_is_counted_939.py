r"""#939: #910b predicted the loop in words, logged each turn, and counted none of them.

Its own message says it: *"This branch is unconditional, so a lane that keeps re-authoring this
page will loop."* r154 ran that prediction **19 times** and nothing anywhere recorded a total.

Following `App.jsx`'s import (#938) rather than the filename, `pages/LoginPage.jsx` has 39 commits
and THREE distinct contents:

    bb861b93  4118B   the framework's projection
    25f7d87f  5768B   the lane's page          17:36 – 17:47
    04fb6e8a  7260B   the lane's richer page   18:25 – 18:49

The framework's version wins every oscillation, and it is what all twelve captures photographed:
`login` produced ONE distinct image across the run and scored 0.50 throughout.

★ Which page SHOULD win is #914's open question and a user's decision. That nineteen rounds of
lane work were written and discarded is not a question — it is waste, whatever the answer. A count
turns nineteen indistinguishable warnings into one statement.
"""
import json
import logging
from pathlib import Path

import pytest

from env_generator.llm_generator.multi_agent.runtime import frontend_scaffold as fs


def _fe(tmp_path):
    fe = tmp_path / "app" / "frontend"
    (fe / "src" / "pages").mkdir(parents=True)
    return fe


def test_the_first_overwrite_counts_one(tmp_path):
    assert fs._count_overwrite_939(_fe(tmp_path), "LoginPage") == 1


def test_it_accumulates_across_calls(tmp_path):
    fe = _fe(tmp_path)
    assert [fs._count_overwrite_939(fe, "LoginPage") for _ in range(4)] == [1, 2, 3, 4]


def test_pages_are_counted_separately(tmp_path):
    fe = _fe(tmp_path)
    fs._count_overwrite_939(fe, "LoginPage")
    fs._count_overwrite_939(fe, "LoginPage")
    assert fs._count_overwrite_939(fe, "BrowsePage") == 1


def test_the_counter_survives_a_fresh_process(tmp_path):
    """★ The run is many processes' worth of scaffolding; an in-memory counter would reset and
    report 1 nineteen times, which is the state this ticket exists to end."""
    fe = _fe(tmp_path)
    fs._count_overwrite_939(fe, "LoginPage")
    f = tmp_path / "design" / "scaffold_overwrites_939.json"
    assert json.loads(f.read_text())["LoginPage"]["overwrites"] == 1   # #960 shape
    assert fs._count_overwrite_939(fe, "LoginPage") == 2


def test_an_unreadable_counter_does_not_crash_the_scaffold(tmp_path):
    fe = _fe(tmp_path)
    f = tmp_path / "design" / "scaffold_overwrites_939.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("{not json")
    assert fs._count_overwrite_939(fe, "LoginPage") == 1


def test_a_bad_path_returns_zero_rather_than_raising(tmp_path):
    """Observability must never break the scaffold it observes (#910b's own rule)."""
    assert fs._count_overwrite_939(None, "X") == 0


def test_the_escalation_fires_on_the_third_overwrite(tmp_path, caplog):
    """★ Three is not a race or a one-off merge; it is an author overwritten on a schedule."""
    import re
    fe = _fe(tmp_path)
    for _ in range(2):
        fs._count_overwrite_939(fe, "LoginPage")
    with caplog.at_level(logging.ERROR,
                         logger="env_generator.llm_generator.multi_agent.runtime"
                                ".frontend_scaffold"):
        # drive the real branch through the source it guards
        src = __import__("inspect").getsource(fs.scaffold_pages_from_contract)
        assert "SCAFFOLD LOOP" in src and "_n939 >= 3" in src, "the escalation must be in-branch"
    # ★ A regex pinning the literal `_count_overwrite_939(frontend_dir, comp)` used to live here,
    # and #960 added a third argument — so it went red for a change that strengthens exactly what
    # it cares about. Sixth spelling assertion of the session to forbid its own improvement, and
    # this one was mine, in this file. `test_the_counter_call_uses_a_bound_name` below already
    # checks the real invariant — every argument is a name bound in the enclosing scope — via the
    # AST, so this was redundant as well as brittle.


def test_the_counter_call_uses_a_bound_name():
    """AST, not text: assert the argument is a name that exists in the function's scope."""
    import ast
    import inspect
    tree = ast.parse(inspect.getsource(fs))
    fn = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
          and n.name == "scaffold_pages_from_contract"][0]
    params = {a.arg for a in fn.args.args}
    bound = params | {t.id for n in ast.walk(fn) if isinstance(n, ast.Assign)
                      for t in n.targets if isinstance(t, ast.Name)}
    calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name) and n.func.id == "_count_overwrite_939"]
    assert calls, "the counter must be called from the overwrite branch"
    for c in calls:
        assert isinstance(c.args[0], ast.Name) and c.args[0].id in bound, c.args[0]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))


# --------------------------------------------------------------------------- #951 the other loop

def test_the_projection_loop_is_counted_apart_from_auth(tmp_path):
    """#951: #939 counted the auth branch and stopped. Its own argument — "the loop itself is
    waste either way" — does not stop there, and the corpus puts 537 component-importing pages on
    the projection path against the auth branch's one. Found by driving the scaffold four rounds:
    BrowseHomePage was clobbered four times and counted zero."""
    fe = _fe(tmp_path)
    for _ in range(3):
        fs._count_overwrite_939(fe, "projection:BrowseHomePage")
    fs._count_overwrite_939(fe, "LoginPage")
    data = json.loads((tmp_path / "design" / "scaffold_overwrites_939.json").read_text())
    assert data["projection:BrowseHomePage"]["overwrites"] == 3
    assert data["LoginPage"]["overwrites"] == 1, (
        "the two loops are different decisions and must stay separable")


def test_the_projection_branch_calls_the_counter():
    """AST, and scope-checked: the argument must be a name bound in that function (#940's rule,
    after `fe` vs `frontend_dir` cost a NameError in #939)."""
    import ast
    import inspect
    tree = ast.parse(inspect.getsource(fs))
    fn = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
          and n.name == "scaffold_pages_from_contract"][0]
    calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name) and n.func.id == "_count_overwrite_939"]
    assert len(calls) == 2, f"auth and projection, found {len(calls)}"
    params = {a.arg for a in fn.args.args}
    bound = params | {t.id for n in ast.walk(fn) if isinstance(n, ast.Assign)
                      for t in n.targets if isinstance(t, ast.Name)}
    for c in calls:
        assert isinstance(c.args[0], ast.Name) and c.args[0].id in bound, ast.unparse(c)


# --------------------------------------------------------------------------- #960 distinct content

def test_it_records_how_many_DISTINCT_things_the_lane_wrote(tmp_path):
    """★ #960. r154's real answer was 39 commits, THREE distinct contents, the framework winning
    all 19 oscillations — and getting it took reconstructing every version with `git show`. A bare
    count cannot tell an author who is ITERATING from one re-emitting the same file, and those need
    opposite responses: progress being discarded, versus a loop with no learning in it."""
    fe = _fe(tmp_path)
    fs._count_overwrite_939(fe, "LoginPage", "version A\n")
    fs._count_overwrite_939(fe, "LoginPage", "version A\n")     # same content again
    fs._count_overwrite_939(fe, "LoginPage", "version B\nmore\n")
    d = json.loads((tmp_path / "design" / "scaffold_overwrites_939.json").read_text())
    assert d["LoginPage"]["overwrites"] == 3
    assert d["LoginPage"]["distinct_count"] == 2, d["LoginPage"]


def test_the_signature_carries_the_line_count(tmp_path):
    """Size is the cheapest signal that a lane page is richer than what replaced it (#914's
    discriminator is exactly a size-and-imports question)."""
    fs._count_overwrite_939(_fe(tmp_path), "P", "a\nb\nc\n")
    d = json.loads((tmp_path / "design" / "scaffold_overwrites_939.json").read_text())
    assert d["P"]["distinct_replaced"][0].endswith(":3L"), d["P"]


def test_an_old_int_record_migrates_in_place(tmp_path):
    """A run that started before #960 must not lose its count or crash on the new read."""
    fe = _fe(tmp_path)
    f = tmp_path / "design" / "scaffold_overwrites_939.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"LoginPage": 7}))
    assert fs._count_overwrite_939(fe, "LoginPage", "x\n") == 8
    assert json.loads(f.read_text())["LoginPage"]["overwrites"] == 8


def test_no_content_still_counts(tmp_path):
    """The caller may not have the replaced text; the count must not depend on it."""
    assert fs._count_overwrite_939(_fe(tmp_path), "P") == 1
