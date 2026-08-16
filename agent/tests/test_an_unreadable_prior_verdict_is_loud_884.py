r"""#884: an unreadable prior verdict silently turned a partial capture into a gate failure.

#883 (concurrent) built a baseline scanner for silent empty-defaults over eight **gate/audit
files**. ★ `visual_fidelity.py` is not among them — and it is the gate where **70 of the 94
non-completed corpus runs die**. Applying #883's own criteria to the three uncovered files found
**19 more** silent empty-default handlers (visual_fidelity 12, workflow_policies 5,
codehub/service 2). This is the one that matters.

```python
try:
    if _pp.is_file():                      # separates "no prior" from "unreadable prior"
        ... prior_by_name[s["name"]] = s
except Exception:
    prior_by_name = {}                     # silent
```

Reaching that handler means the file **exists and could not be parsed**, and `{}` then does two
things:

1. #500's high-water merge stops merging — every screen takes this round's live score, so a
   previously-passing screen can regress.
2. ★ the carry-over loop below (*"prior screens absent from this possibly-partial capture"*)
   carries **nothing**, so a screen this round did not capture **vanishes from the verdict**.

**(2) is the dangerous one.** #872 established that `visual_gate_verdict` fails any owned screen
left unjudged — *"an owned screen that was never judged is a FAILURE, not a skip"* — and it is not
recoverable within the round. So a corrupt `verdict.json` **silently converts a partial capture
into a gate failure**.

★ This is the direction the usual analysis misses. Every other site in this census had an empty
default that read as a **permissive pass**; here it reads as a **silent fail**. The data cannot be
recovered from an unparseable file, so the available fix is to stop it being silent.

### the bug in the fix, caught before it shipped

The first cut called `logger.error(...)`. **This module has no `logger`** — it uses `_LOG`. A
`NameError` inside an `except` block propagates, so the "fix" would have turned an unreadable
verdict into a crashed merge. `compile()` does not catch an undefined name; checking the module's
own logging convention does.
"""
import inspect
import logging

import pytest

from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf


def _span():
    src = inspect.getsource(vf)
    start = src.index("#884: an UNREADABLE prior verdict")
    end = src.index("merged: List", start)
    return src[start:end]


def test_the_site_is_findable():
    """Non-vacuity."""
    assert "#884: an UNREADABLE prior verdict" in inspect.getsource(vf)
    assert "prior_by_name = {}" in _span()


def test_it_announces():
    span = _span()
    assert "_LOG.error" in span
    assert "PRIOR VERDICT UNREADABLE" in span


def test_it_uses_the_module_s_own_logger():
    """★ The bug in the fix. `logger` does not exist here; a NameError inside this `except` would
    turn an unreadable verdict into a crashed merge."""
    span = _span()
    assert "logger.error" not in span.replace("_LOG.error", "")
    assert hasattr(vf, "_LOG") and isinstance(vf._LOG, logging.Logger)


def test_it_names_both_consequences():
    """The merge stopping is the obvious one; the carry-over loss is the one that fails the gate."""
    span = _span()
    assert "high-water merge is disabled" in span
    assert "MISSING from the verdict" in span


def test_it_names_the_boundary_that_makes_it_fatal():
    """Without #872's finding this reads as a cosmetic regression rather than a gate failure."""
    span = _span()
    assert "#872" in span
    assert "failure rather than a skip" in span


def test_it_says_it_once():
    """The merge runs every judged round; a line per round would drown the log (#845)."""
    src = inspect.getsource(vf)
    assert src.count("_said_prior_884") >= 2


def test_the_permissive_default_is_unchanged():
    """`{}` stays — the data is not recoverable from an unparseable file. Only the silence was
    fixable."""
    span = _span()
    assert "prior_by_name = {}" in span
    assert "raise" not in span


def test_the_no_prior_case_is_still_silent():
    """★ First round has no `verdict.json` at all and must stay quiet — the `is_file()` check is
    what separates "no information" from "information that could not be read", the distinction
    #873 named and #877 fixed elsewhere."""
    src = inspect.getsource(vf)
    i = src.index("#884: an UNREADABLE prior verdict")
    before = src[src.rindex("try:", 0, i):i]
    assert "_pp.is_file()" in before


def test_the_carry_over_loop_it_protects_still_exists():
    """Non-vacuity for consequence (2): if the carry-over goes away, this warning names something
    that no longer happens."""
    src = inspect.getsource(vf)
    i = src.index("#884: an UNREADABLE prior verdict")
    after = src[i:src.index("#595", i)]
    assert "for name, p in prior_by_name.items():" in after
    assert "if name not in _names_now:" in after


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
