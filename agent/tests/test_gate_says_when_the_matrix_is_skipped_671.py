r"""#671: the delivery gate's runtime-validation matrix has never run, and never said so.

    task_suite_exists = (output_dir / "tasks" / "tasks.yaml").exists()
    ...
    if task_suite_exists:
        if not api_smoke_pass: failed_checks.append("validation_api_smoke_missing")
        if not ui_smoke_pass:  failed_checks.append(...)

`tasks/tasks.yaml` has NEVER existed:

    0 of 144 runs have tasks/tasks.yaml
    `tasks.yaml` appears nowhere in any run tree; `action_space.yaml` likewise
    the gate logged `task_suite=False` 41 times and `task_suite=True` zero times

So the requirement "at least one API smoke pass and one UI smoke pass before delivery" has not
been evaluated once — and the report gave no sign of it. `task_suite_exists: False` sat in the
payload as a fact, not as a caveat on the verdict.

The evidence those checks want IS present in most runs. Read through `get_validation_results`'
normalisation (#193/#236: 'success' -> 'passed', `evidence.check` lifted into `metadata.check`,
kind derived from `validation:<kind>` names):

    api_smoke passes in  90 of 144 runs
    ui_smoke  passes in 116 of 144 runs

so 54 runs delivered with no API smoke pass and 28 with no UI smoke pass, unasked.

(Measuring the RAW `codehub_checks.json` store instead of going through that normaliser reports
0 of 144 for both — the records carry `status: "success"` and the kind under `evidence`, not
`metadata`. That reading was an artifact of skipping the normaliser and is retracted; #193
exists precisely to absorb it.)

ENFORCING the matrix is a real gate-tightening — 54 runs would gain a new failed check — so it
is recorded in EXPERIMENTS_PENDING rather than switched on blind. What is safe now is to stop
the skip being silent: an unchecked matrix must not read like a passed one.
"""
import inspect

import pytest

from env_generator.llm_generator.multi_agent.runtime import delivery_gate as dg


def _block():
    src = inspect.getsource(dg)
    i = src.index("#671: SAY SO WHEN THE MATRIX IS SKIPPED")
    return src[i:src.index("if task_suite_exists:", i)]


# --- the skip is now visible ----------------------------------------------------------------

def test_a_reason_is_computed_when_the_suite_is_absent():
    body = _block()
    assert 'matrix_skipped_reason = "" if task_suite_exists else (' in body


def test_the_reason_names_the_missing_file():
    assert "no tasks/tasks.yaml" in _block()


def test_the_reason_says_the_requirements_were_not_evaluated():
    body = _block()
    assert "were NOT evaluated" in body


def test_it_marks_the_smoke_flags_as_reported_not_enforced():
    """The two booleans stay in the payload; the caveat stops them reading as a verdict."""
    assert "REPORTED, not enforced" in _block()


def test_the_reason_is_empty_when_the_suite_exists():
    body = _block()
    assert '"" if task_suite_exists' in body


# --- it reaches the report ---------------------------------------------------------------------

def test_it_is_surfaced_beside_task_suite_exists():
    """Both keys must live in the SAME dict literal.

    ★ Was `src[i:src.index("}", i)]` — a slice to the first closing brace after the anchor. #921
    hit exactly that shape in `test_verdict_key_semantics_720`: a nested dict literal moved the
    first `}` earlier, the slice truncated, and the test reported a key as missing that was
    present. Read the literal through the AST instead: a test that locates code by counting
    characters fails on formatting and passes on defects."""
    import ast
    tree = ast.parse(inspect.getsource(dg))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        keys = {k.value for k in node.keys
                if isinstance(k, ast.Constant) and isinstance(k.value, str)}
        if "task_suite_exists" in keys:
            assert "matrix_skipped_reason" in keys, sorted(keys)
            return
    raise AssertionError("no dict literal carrying `task_suite_exists` found")


# --- it must not change the verdict -----------------------------------------------------------

def test_nothing_was_added_to_failed_checks():
    """A visibility change must not block a delivery that used to pass."""
    body = _block()
    assert "failed_checks" not in body


def test_the_matrix_itself_is_untouched():
    """The enforcement still runs exactly when a task suite exists — no more, no less."""
    src = inspect.getsource(dg)
    i = src.index("#671: SAY SO WHEN THE MATRIX IS SKIPPED")
    tail = src[i:src.index("failed_validation_top", i)] if "failed_validation_top" in src[i:] else src[i:]
    assert "if task_suite_exists:" in tail
    assert "validation_api_smoke_missing" in src


def test_the_gate_still_reads_the_same_file():
    src = inspect.getsource(dg)
    assert 'task_suite_exists = (output_dir / "tasks" / "tasks.yaml").exists()' in src


# --- provenance -------------------------------------------------------------------------------

def test_the_measurement_is_recorded():
    flat = " ".join(_block().replace("#", " ").split())
    assert "0 of 144 runs have it" in flat
    assert "api_smoke passes in 90 of 144" in flat and "ui_smoke in 116 of 144" in flat


def test_the_retracted_raw_store_reading_is_recorded():
    """The next reader will measure the raw store and get 0/144; the trap must be written down."""
    flat = " ".join(_block().replace("#", " ").split())
    assert "an artifact of skipping the normaliser, not a finding" in flat


def test_the_decision_not_to_enforce_is_recorded():
    flat = " ".join(_block().replace("#", " ").split())
    assert "EXPERIMENTS_PENDING" in flat
    assert "rather than switched on blind" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
