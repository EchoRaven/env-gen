"""#1203g2 — a chain step recorded `ok=True` for a request to a path that does not exist.

`POST /api/videos/${vid}/like -> 401, expected [401, 403]`, recorded `kind=ok ok=True note=""`.
The `${vid}` never resolved, so the request went to a literal `/api/videos/${vid}/like`. An auth
middleware answers 401 before routing, so that 401 cannot distinguish "this endpoint requires
auth" from "the server 401s everything" -- the step verifies nothing about the real endpoint.

The VERDICT is deliberate and stays. `chain_executor`'s unresolved-placeholder fallback says so
in its own words: "A denial step must NEVER fall here -- the global last_id is the prober's own
most-recent id -> reading it -> 200 false leak; leave the literal (404s, tolerated by the denial
expectation)." Resolving it would trade a vacuous pass for a false leak, which is worse.

What was missing is any mark on the RESULT. Measured over every run directory: 21 such steps
across 10 runs, EVERY ONE with an empty note. 19 of the 21 are corroborated -- a sibling step on
the same canonical endpoint passed with a resolved path -- and the 2 that stand alone are both
`DELETE /api/v1/tenants/{}` on the framework's own control surface. So this adds a sentence, not
a blocker.

The 364 FAILING steps with a leftover placeholder are already explained ("skipped — depends on X
from a failed earlier step") and must stay untouched.
"""
import inspect

import pytest

from env_generator.llm_generator.multi_agent.runtime import chain_executor as ce
from env_generator.llm_generator.multi_agent.runtime.chain_executor import (
    _vacuous_on_placeholder_note_1203g2 as note)


def test_a_pass_on_an_unresolved_placeholder_is_marked():
    out = note("/api/videos/${vid}/like", True)
    assert "#1203g2" in out
    assert "never resolved" in out
    assert "verifies NOTHING about the real endpoint" in out


def test_the_mark_says_the_verdict_is_deliberate():
    """A reader must not go and 'fix' the fallback: the trade is documented and correct."""
    out = note("/api/videos/${vid}/like", True)
    assert "deliberate" in out
    assert "would read as a leak" in out


def test_a_resolved_path_is_not_marked():
    assert note("/api/videos/42/like", True) == ""
    assert note("/api/videos/173e2c17-44a3-4a25-bf52-ce1716447412/like", True) == ""


def test_a_failing_step_is_not_marked():
    """Those already carry their own explanation; a second sentence would be noise."""
    assert note("/api/videos/${vid}/like", False) == ""
    assert note("/api/transit-stops/${stop_id}/departures", False) == ""


@pytest.mark.parametrize("path,ok", [
    (None, True), ("", True), ("/x", None), ("/x", "yes"), ("/x", 1),
    ("/api/videos/{vid}/like", True),      # a BARE brace is not the `${...}` shape
])
def test_it_is_silent_on_anything_else(path, ok):
    assert note(path, ok) == ""


def test_it_never_raises():
    class _Bad:
        def __str__(self):
            raise ValueError("nope")
    assert note(_Bad(), True) == ""


# ---------------------------------------------------------------- wiring, over the AST

def test_the_recorder_appends_the_mark():
    """Structural: the note must be composed into the recorded entry, not merely defined.
    Anchored on the `entry = {` assignment, over the AST -- a helper nothing calls is the
    #1178 shape this codebase keeps finding."""
    import ast
    src = inspect.getsource(ce)
    tree = ast.parse(src)
    callers = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
               and isinstance(n.func, ast.Name)
               and n.func.id == "_vacuous_on_placeholder_note_1203g2"]
    assert len(callers) == 1, "exactly one call site"
    # and it must be assigned into `note`, which the entry dict reads
    assigns = [n for n in ast.walk(tree) if isinstance(n, ast.Assign)
               and any(isinstance(t, ast.Name) and t.id == "note" for t in n.targets)
               and any(c is callers[0] for c in ast.walk(n))]
    assert assigns, "the result must land in `note`"


def test_the_mark_is_appended_after_the_682_hint_not_instead_of_it():
    """#682's unknown-id hint and this mark are independent; replacing one with the other
    would silently drop an explanation the corpus relies on.

    Over the AST, on the ASSIGNMENTS. A first version compared `src.index(...)` of the two call
    texts -- and deleting the #682 line entirely left that test GREEN, because the same text
    appears elsewhere in the module and `index` found the earlier copy. A guard that cannot fail
    on the thing it names is the test, not the code, that needs fixing."""
    import ast
    tree = ast.parse(inspect.getsource(ce))

    def _assign_line(fn_name):
        for n in ast.walk(tree):
            if not (isinstance(n, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == "note" for t in n.targets)):
                continue
            if any(isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
                   and c.func.id == fn_name for c in ast.walk(n)):
                return n.lineno
        return None

    i = _assign_line("_unknown_id_hint_682")
    j = _assign_line("_vacuous_on_placeholder_note_1203g2")
    assert i is not None, "#682's hint is no longer composed into `note`"
    assert j is not None, "#1203g2's mark is no longer composed into `note`"
    assert i < j, (i, j)


# ------------------------------------------------------------- replay over the real corpus

def test_the_corpus_shape_this_describes_still_exists():
    """Non-vacuity against the artifacts: if no corpus step has this shape any more, the
    measurement in the docstring is stale and the ticket needs re-reading."""
    import glob
    import json
    import re
    from pathlib import Path
    root = Path(__file__).resolve().parents[2] / "generated"
    if not root.is_dir():
        pytest.skip("no generated/ corpus on disk")
    raw = re.compile(r"\$\{[^}]*\}")
    hits = 0
    for f in glob.glob(str(root / "*" / "shared" / "hubs" /
                          "registryhub_verification_chains.json")):
        try:
            d = json.loads(Path(f).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for k, rec in (d.items() if isinstance(d, dict) else []):
            if k == "_meta" or not isinstance(rec, dict):
                continue
            for s in ((rec.get("last_result") or {}).get("steps") or []):
                if not isinstance(s, dict) or s.get("status") is None:
                    continue
                if s.get("ok") is True and raw.search(str(s.get("path") or "")):
                    hits += 1
                    # and the helper would have marked every one of them
                    assert note(s.get("path"), s.get("ok")), s
    if hits == 0:
        pytest.skip("corpus no longer carries this shape")
    assert hits >= 10, hits        # measured: 21 across 10 runs
