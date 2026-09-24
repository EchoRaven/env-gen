r"""#1202dl: #36's compose lock serialized validations against each other, not against the gate.

`validation_runner.run_smoke_validation` takes an exclusive flock on
``<project>/docker/.smoke_validation.lock`` before it touches compose, and #36 wrote down
exactly why:

    two concurrent validations against the SAME compose project share container names +
    host ports, so they tear each other down → BOTH report docker_up FAIL ... and a
    perfectly deliverable app never validates in-run

#36-bis then made the un-acquired case DEFER rather than proceed, because "trading a hang
for a race is worse".

The visual gate is the other subsystem that mutates the same compose project — it runs
``compose up -d`` in `_compose_up` — and it takes no lock at all. `grep` over the repo finds
one holder of that lock file (validation_runner) and zero `flock` in visual_fidelity. So a
gate boot can land in the middle of a validation's ``down -v``/``up``, which is precisely the
race #36 exists to prevent, one participant short.

netflix-r44 shows the symptom: `Frontend unreachable on port 8007 during validation; Frontend
service stopped during critical UI-flow validation`, filed as a P0 22 times, alongside a
capture that died with `net::ERR_CONNECTION_RESET`. The framework's own corpus note beside it
reads "90 of 129 runs end this way" — the dominant end-state of the project.

Scope, deliberately narrow: the lock is held only across the compose call, not across the
whole capture session. Holding it through judging would block validations for minutes and
trade this race for starvation. A validation that tears the stack down mid-capture is still
possible and is already handled — that path sets `capture_unavailable` and refunds the
attempt, which #1202de now shares. This removes only the concurrent-MUTATION window, which is
the one that corrupts both sides.
"""
import fcntl
from pathlib import Path

import pytest

from env_generator.llm_generator.multi_agent.runtime.visual_fidelity import (
    _compose_lock_1202dl,
    _deferred_for_compose_lock_1202dl,
    _release_compose_lock_1202dl,
)

LOCK_REL = Path("docker") / ".smoke_validation.lock"


def test_the_lock_is_the_same_file_validation_runner_uses(tmp_path):
    """A second lock file would serialize nothing."""
    fh, ok = _compose_lock_1202dl(tmp_path, wait_sec=0)
    try:
        assert ok
        assert (tmp_path / LOCK_REL).is_file()
    finally:
        _release_compose_lock_1202dl(fh)


def test_it_is_acquired_when_free(tmp_path):
    fh, ok = _compose_lock_1202dl(tmp_path, wait_sec=0)
    _release_compose_lock_1202dl(fh)
    assert ok


def test_it_is_not_acquired_while_a_validation_holds_it(tmp_path):
    """The r44 window: a validation is mid down -v/up."""
    (tmp_path / "docker").mkdir(parents=True, exist_ok=True)
    holder = open(tmp_path / LOCK_REL, "w")
    fcntl.flock(holder.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        fh, ok = _compose_lock_1202dl(tmp_path, wait_sec=0)
        _release_compose_lock_1202dl(fh)
        assert not ok, "the gate would have booted compose during a validation"
    finally:
        fcntl.flock(holder.fileno(), fcntl.LOCK_UN)
        holder.close()


def test_releasing_lets_the_next_caller_in(tmp_path):
    fh, ok = _compose_lock_1202dl(tmp_path, wait_sec=0)
    assert ok
    _release_compose_lock_1202dl(fh)
    fh2, ok2 = _compose_lock_1202dl(tmp_path, wait_sec=0)
    _release_compose_lock_1202dl(fh2)
    assert ok2, "the lock was not released"


def test_deferral_is_not_a_verdict_about_the_app(tmp_path):
    """#36-bis's rule, expressed in the gate's own vocabulary.

    Reuses `capture_unavailable` — the channel #1202de established for 'not a judgment' —
    so the attempt is refunded instead of scoring an app that was never reachable.
    """
    r = _deferred_for_compose_lock_1202dl([])
    assert r["capture_unavailable"] is True
    assert r["passed"] is False
    assert r["screens"] == []
    assert "lock" in r["summary"].lower()


def test_release_tolerates_none(tmp_path):
    """The un-acquired path still calls release; it must not raise."""
    _release_compose_lock_1202dl(None)
