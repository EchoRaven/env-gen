"""#1202vw: the fifth task-state transition, and the one where a blanket rule is wrong.

#679 trimmed four transitions — task_claimed, task_completed, task_failed, task_cancelled.
`bug_state_changed` is the same shape on the same store (a bug IS a task, `metadata.kind ==
"bug"`), re-emitting the whole record on every state change, and it was never covered.

Measured over the delivered corpus: 8311 notices, 17.1M chars, median 1928. Inside
`metadata`, `bug_artifacts` is 43.7%, `root_cause_hypothesis` 22.8%, `triage_history` 18.7%,
and every field the recipient needs in order to ACT — bug_state, severity, priority, source,
parent_bug_id, kind — is together 1.7%.

#679's keep-set cannot be reused, which is why this is a separate function: it does not keep
`metadata`, so the trimmed notice would omit `bug_state` — the new state, which is the entire
point of the message.

And the two big fields behave OPPOSITELY, so one blanket rule would be wrong either way:

    bug_artifacts          3127 of 3127 already delivered with the bug's `task_created` and
                           unchanged in the first notice; changed 0 times in 5238 later ones
    root_cause_hypothesis  3083 of 3127 first appear in the FIRST bug_state_changed — the
                           triage transition IS its first delivery — then change in 975 of
                           5238 later notices

So the rule is the only honest one: a field is omitted ONLY when this record's previous state
carried that exact value. What changed always travels.
"""
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.hubs.workhub import service as SVC   # noqa: E402

_N = SVC._bug_notice_1202vw
_CAP = SVC._BUG_NOTICE_CHARS_1202vw


def _bug(**md):
    meta = {"kind": "bug", "bug_state": "triaged", "severity": "P0", "priority": "P0",
            "source": "verifier", "parent_bug_id": "", "triage_history": [
                {"at": 1.0, "by": "debugger", "action": "triaged", "note": "first"}]}
    meta.update(md)
    return {"id": "task_bug_1", "title": "feed returns 500", "status": "in_progress",
            "assignee": "backend", "created_by": "verifier", "metadata": meta}


_BIG = "x" * (_CAP + 1)


def test_a_small_notice_passes_through_untouched():
    b = _bug()
    assert _N(b, b) == b


def test_the_new_state_always_survives():
    """The whole point of the message. #679's keep-set drops `metadata`, which is why it
    could not be reused here."""
    prior = _bug(bug_artifacts=_BIG, bug_state="open")
    cur = _bug(bug_artifacts=_BIG, bug_state="fix_in_progress")
    out = _N(cur, prior)
    md = out["metadata"]
    assert md["bug_state"] == "fix_in_progress"
    for k in ("severity", "priority", "source", "kind"):
        assert md[k] == cur["metadata"][k], f"{k} must survive — it is how the lane acts"
    assert out["id"] == cur["id"] and out["assignee"] == cur["assignee"]


def test_an_unchanged_field_is_omitted_with_a_pointer():
    """`bug_artifacts` changed 0 times in 5238 later notices — a pure re-send."""
    prior = _bug(bug_artifacts=_BIG)
    cur = _bug(bug_artifacts=_BIG, bug_state="fix_in_progress")
    out = _N(cur, prior)
    assert "bug_artifacts" not in out["metadata"]
    note = out["metadata"]["_body_omitted"]
    assert "bug_artifacts" in note and "workhub_get_task" in note and "task_bug_1" in note
    assert len(str(out)) < len(str(cur)) // 2


def test_a_changed_field_always_travels():
    """`root_cause_hypothesis` changes in 975 of 5238 later notices — the debugger's updated
    diagnosis. Dropping it on a rule would withhold it from the assignee (#274's wedge)."""
    prior = _bug(bug_artifacts=_BIG, root_cause_hypothesis="socket flake")
    cur = _bug(bug_artifacts=_BIG, root_cause_hypothesis="the column is never seeded",
               bug_state="fix_in_progress")
    out = _N(cur, prior)
    assert out["metadata"]["root_cause_hypothesis"] == "the column is never seeded"
    assert "bug_artifacts" not in out["metadata"]      # that one WAS unchanged


def test_a_newly_introduced_field_travels():
    """3083 of 3127 bugs see `root_cause_hypothesis` for the FIRST time in the first notice."""
    prior = _bug(bug_artifacts=_BIG)
    cur = _bug(bug_artifacts=_BIG, root_cause_hypothesis="found it", bug_state="triaged")
    out = _N(cur, prior)
    assert out["metadata"]["root_cause_hypothesis"] == "found it"


def test_the_latest_triage_note_survives_and_the_rest_points():
    hist = [{"at": float(i), "by": "d", "action": "a%d" % i, "note": "n%d" % i}
            for i in range(6)]
    prior = _bug(bug_artifacts=_BIG, triage_history=hist[:-1])
    cur = _bug(bug_artifacts=_BIG, triage_history=hist)
    out = _N(cur, prior)
    assert out["metadata"]["triage_history"] == hist[-1:], (
        "the note for THIS transition is the news; the earlier ones were already sent")
    assert "5 earlier entries" in out["metadata"]["_body_omitted"]


def test_the_source_record_is_not_mutated():
    """A trim that edited the record would make the pointer point at the same hole."""
    prior = _bug(bug_artifacts=_BIG)
    cur = _bug(bug_artifacts=_BIG, bug_state="closed")
    _N(cur, prior)
    assert cur["metadata"]["bug_artifacts"] == _BIG


def test_no_prior_state_means_nothing_is_assumed_delivered():
    """Without a previous state there is no evidence anything was delivered, so nothing is
    omitted — the strict direction."""
    cur = _bug(bug_artifacts=_BIG, bug_state="open")
    out = _N(cur, None)
    assert out["metadata"]["bug_artifacts"] == _BIG
    assert "_body_omitted" not in out["metadata"]


def test_odd_input_is_returned_untouched():
    assert _N(None, None) is None
    assert _N("not a dict", {}) == "not a dict"
    assert _N({"id": "x"}, {}) == {"id": "x"}


def test_the_emit_site_passes_the_previous_state():
    """AST (#943). The prior record is what makes "already delivered" a fact rather than a
    guess, so the emit must hand it over."""
    import ast
    import inspect

    fn = next(n for n in ast.walk(ast.parse(inspect.getsource(SVC)))
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
              and n.name == "update_bug_state")
    body = ast.unparse(fn)
    assert "_bug_notice_1202vw(updated, task)" in body, (
        "the notice must be built from BOTH the new and the previous record")


def test_the_679_keepset_is_not_reused_here():
    """A guard against the tempting one-line 'fix': #679's helper drops `metadata`, so wiring
    it into this emit would ship a state-change notice with no state."""
    trimmed = SVC._transition_payload_679(_bug(bug_artifacts=_BIG))
    assert "metadata" not in trimmed, (
        "if #679 ever starts keeping metadata, revisit whether this function is still needed")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
