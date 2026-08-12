r"""#592: a ladder substitution must be attributed to the capture that failed.

#188 explains a failure when a variable stayed LITERAL. It is silent in the worse case — where
the placeholder ladder DID produce a value. r130's `my_list_add_and_readback`, from the artifact:

    [2] GET  /api/titles   save {titleId: items.0.id}  -> 200 ok, note "save FAILED
                                                          (response lacks the path)"
    [3] POST /api/my-list  {"title_id": "${titleId}"}  -> 404 "referenced resource not found"

The catalog was empty (r130's #566x reset), so `items.0.id` captured nothing, the ladder filled
`${titleId}` with an unrelated id, and the 404 named the FOREIGN KEY. Step [2] is recorded
ok=True, so the gate, the dispatcher and the lane all chase a foreign-key bug two steps from the
real cause. #566x removed ONE producer of the empty collection; the misattribution survives
every other producer (a renamed envelope key, a filtered-out row, an owner-scoped read).

Annotation only, NOT reclassification — the #587 precedent. The step still fails; it just says
whose fault it is.
"""
import inspect

import pytest

from env_generator.llm_generator.multi_agent.runtime import chain_executor as ce


@pytest.fixture()
def src():
    return inspect.getsource(ce.execute_chain)


def test_the_authored_vars_are_read_from_the_STEP_not_the_substituted_request(src):
    """`_unres_vars` is computed after substitution, so a filled var is invisible there —
    the authored set has to come off the raw step."""
    assert '_authored_vars = set(re.findall(r"\\$\\{(\\w+)\\}", str(step.get("path") or "")))' in src
    assert 'json.dumps(step.get("body"))' in src


def test_it_reports_only_vars_that_were_filled_AND_trace_to_a_failed_save(src):
    i = src.index("_ladder_filled = sorted(")
    window = src[i:i + 200]
    assert "_authored_vars - _unres_vars" in window      # filled, not still-literal
    assert "save_failed_by_var.get(v)" in window         # and the save actually failed


def test_a_var_a_later_step_really_captured_is_not_annotated(src):
    """Self-review catch: `save_failed_by_var` is never cleared, so an entry survives a
    LATER step capturing the same var successfully. The ladder writes only into the outgoing
    request, never into `variables` — so presence there proves a real capture."""
    i = src.index("_ladder_filled = sorted(")
    assert "v not in variables" in src[i:i + 200]


def test_a_var_that_is_still_literal_stays_with_188(src):
    """Subtracting `_unres_vars` keeps the two messages from doubling up."""
    i = src.index("_ladder_filled = sorted(")
    assert "_authored_vars - _unres_vars" in src[i:i + 200]
    assert 'note = "unresolved " + "; ".join(_hints)' in src


def test_the_note_names_the_upstream_step_and_redirects_the_reader(src):
    i = src.index("if _ladder_filled:")
    window = src[i:i + 700]
    assert "SUBSTITUTED" in window
    assert "save_failed_by_var[_v]" in window            # the step that failed to capture
    assert "UNRELATED id" in window
    assert "fix that capture, not this endpoint" in window


def test_the_substitution_is_machine_readable_in_the_record(src):
    assert 'autofilled.append(f"ladder-filled-after-failed-save:{_lv}")' in src


def test_it_annotates_rather_than_reclassifies(src):
    """Guard the deliberate choice: `kind` must not be touched by this path (#587)."""
    i = src.index("if _ladder_filled:")
    window = src[i:i + 700]
    assert "kind" not in window, window


def test_the_note_only_fires_on_a_failing_step(src):
    """`note` is only built under `if not ok:` — a passing step must stay unannotated."""
    i = src.index("if _ladder_filled:")
    head = src.rindex("if not ok:", 0, i)
    between = src[head:i]
    assert "recorded.append" not in between      # still inside the same not-ok block


def test_the_r130_shape_is_documented_where_it_lives(src):
    assert "#592" in src
    assert "my-list" in src and "items.0.id" in src


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
