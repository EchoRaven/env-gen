r"""#790: a delivery check that ERRORS must not read as a delivery check that PASSED.

The silent-degradation class (#737 / #769 / #770 / #788 / #789) was swept for systematically:
every `except` in `runtime/` whose handler body is `pass` / `continue` / a bare default. 583 of
them — far too many to touch, and most are legitimately best-effort parsing. The subset that
matters is the one where **the swallowed default is the answer that lets the run proceed**, and
it concentrates in the highest-stakes file:

    unresolved_bug_tasks_743             -> {}    = no unresolved bugs
    incomplete_required_tasks            -> []    = nothing incomplete
    _uncovered_business_endpoints        -> []    = every business endpoint covered
    _chain_touches_business              -> True  = this chain covers business
    business_chain_blockers              -> {}    = no chain blockers
    noncanonical_business_response_keys  -> []    = every response key canonical
    _declared_critical_flows             -> []    = no declared critical flows
    ---
    _endpoint_validated                  -> False = NOT validated   <- fails CLOSED, left alone

Seven functions where an exception hands back the release-permitting answer, silently. **#751 and
#752 were switched from REPORTING to BLOCKING this session on top of two of them** — a gate is
only as good as the evidence it reads.

The defaults are KEPT. Hard-failing here wedges every release on a hub hiccup, which is exactly
#789's trade and the same answer: the fail-open is fine, the silence is not. What changes is that
the gate can now distinguish *"ran and found nothing"* from *"did not run"*, in its own returned
record rather than only in a log line nobody reads at the cut.
"""
import logging

import pytest

from env_generator.llm_generator.multi_agent.runtime import delivery_gate as dg


@pytest.fixture(autouse=True)
def _clean():
    dg.reset_check_errors_790()
    yield
    dg.reset_check_errors_790()


class _Boom:
    """A workhub whose list_tasks raises — the shape a hub hiccup actually takes."""
    def list_tasks(self, *a, **k):
        raise RuntimeError("hub unavailable")


class _Hubs:
    def __init__(self):
        self.workhub = _Boom()


def test_the_permissive_default_is_unchanged():
    """Non-negotiable: the gate must not start hard-failing because a hub blipped."""
    assert dg.unresolved_bug_tasks_743(_Hubs()) == {}


def test_but_the_failure_is_now_recorded():
    dg.unresolved_bug_tasks_743(_Hubs())
    errs = dg.check_errors_790()
    assert errs and "unresolved_bug_tasks_743" in errs[0]
    assert "RuntimeError" in errs[0], "the cause has to travel, not just the fact"
    assert "no unresolved bugs" in errs[0], "and what it defaulted TO"


def test_the_warning_says_it_is_not_a_pass(caplog):
    with caplog.at_level(logging.WARNING):
        dg.unresolved_bug_tasks_743(_Hubs())
    msg = " ".join(r.getMessage() for r in caplog.records)
    assert "DELIVERY CHECK DID NOT RUN" in msg
    assert "NOT" in msg and "evidence the check passed" in msg


def test_it_is_recorded_once_not_per_call(caplog):
    with caplog.at_level(logging.WARNING):
        for _ in range(4):
            dg.unresolved_bug_tasks_743(_Hubs())
    assert len(dg.check_errors_790()) == 1
    assert sum("DELIVERY CHECK DID NOT RUN" in r.getMessage() for r in caplog.records) == 1


def test_a_healthy_run_records_nothing():
    """Non-vacuity in the other direction: this must be silent when everything works, or it is
    noise and will be ignored — which is how #788 happened."""
    class _Ok:
        def list_tasks(self, *a, **k):
            return []
    class _H:
        workhub = _Ok()
    dg.unresolved_bug_tasks_743(_H())
    assert dg.check_errors_790() == []


def test_the_reporter_cannot_break_the_gate():
    """It runs inside an exception handler on the release path; it must never raise."""
    class _Unprintable(Exception):
        def __str__(self):
            raise ValueError("even the message explodes")
    dg._swallowed_790("x", _Unprintable(), "y")          # must not raise


# --- coverage of the wiring itself ------------------------------------------------------------

def test_every_permissive_default_is_wired():
    import inspect
    src = inspect.getsource(dg)
    for fn in ("unresolved_bug_tasks_743", "incomplete_required_tasks",
               "_uncovered_business_endpoints", "_chain_touches_business",
               "business_chain_blockers", "noncanonical_business_response_keys",
               "_declared_critical_flows"):
        assert f'_swallowed_790("{fn}"' in src, fn


def test_the_fail_closed_one_was_left_alone():
    """`_endpoint_validated` returns False on error — the STRICT answer. Wrapping it would be
    cargo-culting the pattern onto a site that does not have the defect."""
    import inspect
    src = inspect.getsource(dg)
    assert '_swallowed_790("_endpoint_validated"' not in src


def test_the_verdict_carries_it():
    """A log line is not enough — #788's whole lesson is that nobody reads for an absence."""
    import inspect
    src = inspect.getsource(dg.validate_delivery_gate)
    assert '"checks_errored_790": check_errors_790(),' in src


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
