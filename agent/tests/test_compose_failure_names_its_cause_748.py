r"""#748: the reason the app would not boot was captured and withheld.

Found by generalising #747: sweep every hub store for a field agents/the framework WRITE that no
code reads. Over the 148-run corpus, keys written ≥80 times whose name never appears as a string
literal anywhere in the tree — three candidates, and this is the one that matters:

    runhub_runs.compose_stderr                216 records, ALL 216 non-empty
    codehub_checks.evidence.http_status       133
    workhub_tasks.evidence.contract_test_...   95

`compose_stderr` has exactly one writer (this call site) and zero readers. It holds the actual
cause of a boot failure —
``CRITICAL:podman_compose:missing files: ['generated/…/docker/docker-compose.yml']`` — while the
EVENT that everything downstream reacts to carried the bare label ``compose_up_failed``. So the
orchestrator and the lanes were told the app would not boot and not why, with the answer sitting
in a field beside them.

Same shape as #677 (1778 bare "Connection refused" with the diagnosis one layer down), #690 and
#740: the diagnosis exists at the moment of failure and is kept from the party that must act on
it. The store write is unchanged; the cause is now logged and carried in the event payload.
"""
import inspect

import pytest

from env_generator.llm_generator.multi_agent.runtime.hubs.runhub import service as svc


def _block() -> str:
    src = inspect.getsource(svc)
    i = src.index("#748: THE REASON WAS CAPTURED AND WITHHELD")
    return src[i:src.index("# Stage 2: healthcheck", i)]


def _prose() -> str:
    """The block with implicit string-concatenation SEAMS removed, then whitespace collapsed.

    `" ".join(lines)` is not enough and it failed here: a message split as `"…so every "` /
    `"check after this…"` keeps its quote characters, so the joined text reads `every " "check`
    and an assertion on the sentence fails on punctuation that is not in the message. Third time
    this trap has appeared in this suite; the seam has to be closed before matching, not after.
    """
    import re
    return " ".join(re.sub(r'"\s*\n\s*"', "", _block()).split())


# --- the cause travels with the failure ---------------------------------------------------------

def test_the_event_carries_the_stderr_not_just_the_label():
    b = _block()
    assert '"reason": "compose_up_failed"' in b, "the original label must survive"
    assert '"compose_stderr": _stderr748[:500]' in b
    assert '"returncode": up_result.returncode' in b


def test_the_failure_is_logged():
    b = _block()
    assert "_logger.warning(" in b
    assert "compose up FAILED for run" in b


def test_the_log_says_what_the_failure_invalidates():
    """A boot failure is not one bad check — everything measured afterwards is meaningless."""
    assert "every check after this is measuring nothing" in _prose()


def test_an_empty_stderr_still_says_something_useful():
    """compose can fail with no stderr at all; a blank cause is the case that reads as 'no
    information' and is exactly when a hint is worth most."""
    b = _prose()
    assert "(compose produced no stderr" in b
    assert "check the compose file exists and the daemon is reachable)" in b


def test_the_store_write_is_unchanged():
    b = _block()
    assert 'self.update_run_status(run_id, "aborted", agent="runhub",' in b
    assert "compose_stderr=_stderr748[:500]" in b


def test_the_payload_and_the_record_agree_on_the_truncation():
    """Two 500s that could drift apart silently — a reader comparing them must not see a
    difference that is only a slice length."""
    b = _block()
    assert b.count("[:500]") == 2


def test_it_returns_immediately_as_before():
    b = _block()
    assert "return self.get_run(run_id)" in b


def test_nothing_new_can_raise():
    """A diagnostic must never convert a handled boot failure into a crash."""
    b = _block()
    stmts = [l.strip() for l in b.split("\n")
             if l.strip() and not l.strip().startswith("#")]
    assert not [l for l in stmts if l.startswith("raise ")]
    assert "_stderr748 = (up_result.stderr or \"\").strip()" in b, "None stderr is handled"


# --- provenance -----------------------------------------------------------------------------------

def test_the_measurement_is_recorded():
    b = " ".join(_block().replace("#", " ").split())
    assert "216 records in the corpus carry it" in b
    assert "all 216 are non-empty" in b


def test_the_one_writer_zero_readers_finding_is_recorded():
    b = " ".join(_block().replace("#", " ").split())
    assert "read NOWHERE" in b
    assert "one writer, zero readers" in b


def test_the_shared_shape_is_named():
    b = " ".join(_block().replace("#", " ").split())
    assert "677" in b and "740" in b
    assert "kept from the party that has to act on it" in b


def test_the_real_cause_string_is_quoted():
    """The finding is specific; a future reader should not have to re-derive what was hidden."""
    b = " ".join(_block().replace("#", " ").split())
    assert "podman_compose:missing files" in b


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
