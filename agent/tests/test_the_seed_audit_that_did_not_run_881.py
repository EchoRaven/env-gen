r"""#881: a seed audit that raised read as "the seed is fine", silently.

The #879 sweep, completed. Classifying all 34 swallowed-empty-then-tested sites by whether the
value drives a DECISION or a fallback render: **11 decision-driving, 23 fallback**. One was #879.
This is the one that gates delivery, and its handler was **bare** — no log, no record:

```python
except Exception:
    _issues = []          # byte-identical to "the seed is fine"
if _issues:
    blockers.append("authored seed quality: …")
```

★ **#792 lives in this file and exists for exactly this** — *"a delivery GATE that cannot load
must not read as a delivery gate that PASSED"*. It wired the two audit imports directly above and
never reached this one.

★★ **The pattern that makes this worth a ticket rather than a one-line fix:** #790 swept
`delivery_gate.py` and left the orchestrator's page-build detect (#879); #792 swept
`deliverability.py` and left this. **Both of my silence sweeps left a decision-driving swallow
inside a file they had swept.** Sweeping a file is not sweeping its handlers — the sweep followed
the sites I was already looking at, which is the same failure mode as instrumenting where I was
looking rather than where the failure was (#864 → #863 → #862).

The other nine decision-driving sites are recorded in the EXPERIMENTS item with their locations.
All nine are silent; "decision-driving" there is a keyword screen over the `if` body, not a
verdict, so they are listed for triage rather than claimed as defects.
"""
import inspect
import re

import pytest

from env_generator.llm_generator.multi_agent.runtime import deliverability as dl

_reset = next(getattr(dl, n) for n in dir(dl)
              if n.startswith("reset") and callable(getattr(dl, n)))


def _span():
    src = inspect.getsource(dl)
    start = src.index("from .seed_audit import audit_authored_seed")
    end = src.index("authored seed quality:", start)
    return src[start:end]


def test_the_site_is_findable():
    """Non-vacuity."""
    assert "audit_authored_seed" in inspect.getsource(dl)


def test_the_handler_is_no_longer_bare():
    span = _span()
    assert "except Exception as _sa_exc:" in span
    assert "_gate_absent_792(" in span


def test_it_reports_under_the_existing_aggregator():
    """★ Not a new channel. #792's reporter already surfaces "this gate could not run" into the
    verdict; a second mechanism would be another thing to remember to read."""
    span = _span()
    assert '"authored_seed_quality"' in span
    assert '"audit"' in span


def test_the_permissive_default_is_kept():
    """Failing open is deliberate — a broken audit must not wedge every release. What was missing
    was the record, not the default."""
    span = _span()
    assert "_issues = []" in span


def test_the_reporter_actually_records_and_announces(caplog):
    """★ Uses the module's OWN reset, not a poke at `_GATES_ABSENT_792`. My first version cleared
    that list directly and stayed red, because the say-once key lives in a SECOND global
    (`_SAID_700`) — and the reset's docstring says exactly this: *"Rather than have tests poke a
    private global, the reset is part of the contract."* The test was wrong; the code was right,
    and its own documentation had already answered the question."""
    import logging
    _reset()
    try:
        with caplog.at_level(logging.WARNING):
            dl._gate_absent_792("authored_seed_quality", ValueError("boom"), "audit")
        assert any("authored_seed_quality" in n for n in dl._GATES_ABSENT_792)
        assert any("DID NOT RUN" in r.getMessage() for r in caplog.records), \
            [r.getMessage() for r in caplog.records]
    finally:
        _reset()


def test_it_says_it_once_per_gate_and_stage():
    """The gate is recomputed every delivery tick; a note per tick would drown the verdict."""
    _reset()
    try:
        for _ in range(3):
            dl._gate_absent_792("authored_seed_quality", ValueError("boom"), "audit")
        assert len(dl._GATES_ABSENT_792) == 1, dl._GATES_ABSENT_792
    finally:
        _reset()


def test_the_two_neighbouring_audits_are_still_wired():
    """Non-vacuity for the premise: #792 did reach the imports directly above, which is why this
    omission is an oversight rather than a design choice."""
    src = inspect.getsource(dl)
    assert src.count("_gate_absent_792(") >= 3


def test_the_sweep_that_missed_it_is_named_at_the_site():
    """★ The transferable half. Without it the next reader sees a fix, not a pattern."""
    span = _span()
    assert "#792" in span and "#879" in span


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
