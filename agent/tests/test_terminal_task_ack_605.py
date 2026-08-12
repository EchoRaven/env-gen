r"""#605: a TERMINAL workhub_task action echoed back the work order the caller already holds.

Second finding on the cost axis, after #604. `workhub_task` returns 20.76 MB over 379 logged
calls at an average of **54k chars regardless of action**, and **11.91 MB (57%)** of that is
`complete`/`fail` handing a task record back to the lane that just executed it.

The records are not small: over the arc's 4736 stored tasks, `description` alone is **17.07 MB**
of ~22 MB total, with single descriptions up to **102,615 chars (~25k tokens)** — the visual
gate's remediation order inlines all ten screens' fixes (staged assets, layout geometry, measured
colour diffs, verification steps) into one task.

`claim` keeps the full record — that IS the work order being delivered. Only terminal actions are
trimmed, field-by-field above a threshold, so every small field a downstream reader might want
survives untouched, and an error result passes through verbatim.
"""
import inspect

import pytest

from env_generator.llm_generator.tools import hub_tools as ht


@pytest.fixture(scope="module")
def src():
    cls = next(c for n, c in vars(ht).items()
               if inspect.isclass(c) and getattr(c, "NAME", "") == "workhub_task")
    return inspect.getsource(cls)


# --- the shared eliding helper (#605/#606) ------------------------------------------------

ack = ht._elide_large_fields


def test_a_huge_description_is_elided_with_a_pointer_back():
    out = ack({"id": "T1", "status": "completed", "description": "x" * 97849},
              "unchanged by this call; re-read with workhub_get_task(task_id='T1')")
    assert out["status"] == "completed" and out["id"] == "T1"
    assert "97849 chars omitted" in out["description"]
    assert "workhub_get_task(task_id='T1')" in out["description"]


def test_every_small_field_survives_untouched():
    rec = {"id": "T1", "title": "fix the gate", "status": "completed",
           "assignee": "frontend", "priority": "P1", "completed_at": 123.4,
           "result": {"ok": True}, "evidence": {"files": ["a.jsx"]}}
    assert ack(dict(rec), "h") == rec


def test_a_field_exactly_at_the_limit_is_kept():
    body = "y" * ht._TERMINAL_ACK_FIELD_LIMIT
    assert ack({"id": "T1", "description": body}, "h")["description"] == body


def test_an_error_result_passes_through_verbatim():
    err = {"error": "Task not found", "description": "z" * 5000}
    assert ack(err, "h") == err


def test_a_non_mapping_is_returned_as_is():
    for v in (None, "oops", 7, ["a"]):
        assert ack(v, "h") is v


def test_an_unserializable_field_does_not_crash():
    assert "weird" in ack({"id": "T1", "weird": object()}, "h")


def test_the_nested_ack_delegates_to_the_shared_helper(src):
    assert "_elide_large_fields(" in src


# --- where it is applied, and where it must NOT be ---------------------------------------------

def test_the_three_terminal_actions_use_it(src):
    assert src.count("ToolResult(data=_ack(hub_result))") == 3
    for act in ("complete_task(", "fail_task(", "cancel_task("):
        i = src.index(act)
        assert "_ack(hub_result)" in src[i:i + 260], act


def test_CLAIM_still_returns_the_whole_record(src):
    """The work order must arrive intact — trimming it would break the lane."""
    i = src.index('if action == "claim":')
    window = src[i:src.index('if action == "claim_all"', i)]
    assert "ToolResult(data=hub_result)" in window
    assert "_ack(" not in window


def test_CREATE_is_untouched(src):
    i = src.index('if action == "create":')
    assert "_ack(" not in src[i:i + 400]


def test_the_code_truth_guard_still_precedes_completion(src):
    """#605 must not have disturbed the false-complete guard."""
    assert src.index("CODE-TRUTH GUARD") < src.index("complete_task(")
    assert "complete denied: impl task" in src


def test_the_measurement_that_justifies_it_is_recorded(src):
    assert "11.91 MB" in src and "102,615" in src


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
