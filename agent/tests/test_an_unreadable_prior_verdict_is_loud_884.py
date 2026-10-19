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
import json
import pathlib
import tempfile
import types
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


# --- #1203pg: the announcement, DRIVEN -----------------------------------------------------------
#
# Every assertion above reads the SOURCE, and two mutations walked through:
#
#   * making the `_LOG.error` unreachable, which returns the site to the silent fail-open that
#     is the only thing this ticket changed;
#   * inverting the say-once latch, so the FIRST unreadable prior is suppressed and nothing
#     else sets the flag -- it never announces at all. `src.count("_said_prior_884") >= 2`
#     holds either way, because the flag is written once and read once.
#
# The permissive default was the only property with a real driver, and it was the only mutation
# the file caught. Same result in #882, #887 and #888 -- "fail open + say once" is a FAMILY, and
# these two mutations work on every member of it.
#
# The flag lives in module `globals()`, so it is per-PROCESS: without clearing it, the second
# test in any run would see a latched flag and silently assert nothing.


def _clear_884():
    vf.__dict__.pop("_said_prior_884", None)


def _drive_884(prior_bytes):
    """Persist a verdict over an existing `verdict.json` holding `prior_bytes`.

    Returns the error records the module logger received.
    """
    _clear_884()
    errors = []
    real = vf._LOG
    vf._LOG = types.SimpleNamespace(
        error=lambda *a, **k: errors.append((a[0] % a[1:]) if len(a) > 1 else str(a[0])),
        warning=lambda *a, **k: None, info=lambda *a, **k: None, debug=lambda *a, **k: None)
    try:
        d = pathlib.Path(tempfile.mkdtemp())
        vdir = d / "design" / "visual_gate"
        vdir.mkdir(parents=True)
        (vdir / "verdict.json").write_bytes(prior_bytes)
        (vdir / "a.png").write_bytes(b"PNG")
        vf._persist_verdict(
            d, passed=False, min_similarity=0.65, summary="s", coverage={},
            results=[{"name": "a", "route": "/a", "similarity": 0.5, "dimensions": {}}])
        return errors, json.loads((vdir / "verdict.json").read_text(encoding="utf-8"))
    finally:
        vf._LOG = real
        _clear_884()


def test_an_unreadable_prior_really_announces():
    errors, _ = _drive_884(b"{ this is not json")
    assert len(errors) == 1, "an unreadable prior verdict was silent -- #884's whole subject"
    assert "PRIOR VERDICT UNREADABLE" in errors[0]


def test_the_announcement_names_both_consequences():
    errors, _ = _drive_884(b"{ this is not json")
    msg = errors[0]
    assert "high-water merge is disabled" in msg
    assert "MISSING from the verdict" in msg
    assert "#872" in msg, "the boundary that makes it fatal must be named"
    assert "JSONDecodeError" in msg or "ValueError" in msg, msg


def test_it_really_says_it_once():
    """The flag is module-global, so a second unreadable prior in the same process is silent.

    That is the intended behaviour ("announced once"), and it is what makes the inverted-latch
    mutation invisible to a source count -- so it has to be driven.
    """
    errors = []
    real = vf._LOG
    _clear_884()
    vf._LOG = types.SimpleNamespace(
        error=lambda *a, **k: errors.append(str(a[0])), warning=lambda *a, **k: None,
        info=lambda *a, **k: None, debug=lambda *a, **k: None)
    try:
        for _ in range(3):
            d = pathlib.Path(tempfile.mkdtemp())
            vdir = d / "design" / "visual_gate"
            vdir.mkdir(parents=True)
            (vdir / "verdict.json").write_bytes(b"{ not json")
            (vdir / "a.png").write_bytes(b"PNG")
            vf._persist_verdict(
                d, passed=False, min_similarity=0.65, summary="s", coverage={},
                results=[{"name": "a", "route": "/a", "similarity": 0.5, "dimensions": {}}])
        assert len(errors) == 1, "announced %d times" % len(errors)
        assert vf.__dict__.get("_said_prior_884") is True
    finally:
        vf._LOG = real
        _clear_884()


def test_a_readable_prior_announces_nothing():
    """Non-vacuity in the other direction: a normal round must stay quiet."""
    errors, _ = _drive_884(json.dumps({"screens": [], "version": 1}).encode())
    assert errors == [], errors


def test_the_round_still_completes_on_an_unreadable_prior():
    """The permissive default is deliberate: a corrupt verdict.json must not block the gate."""
    _, written = _drive_884(b"{ not json")
    assert written.get("screens") is not None, "the round did not write a verdict at all"
