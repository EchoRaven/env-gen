r"""#1202em: #1202el fixed the save side; the nulls already on disk still land.

#1202el stopped `save_gate_counters_1202ce` from persisting attributes that were never
set. It could not help a milestone_gates.json written BEFORE that fix, and googlemaps-r16
had one: twelve nulls, `_fwdeliver_grace_count` among them. Its second resume raised

    TypeError: '>=' not supported between instances of 'NoneType' and 'int'

eight times -- more than the four before the fix, because the run got further.

The traceback #1202el added pinned it in one shot, which is the whole reason that half
existed:

    orchestrator.py:4304  in _maybe_framework_deliver
    delivery_gate.py:2250 in convergence_grace  ->  if grace_used >= max_grace

`grace_used=getattr(self, "_fwdeliver_grace_count", 0)`. The default never fires: a
restored None makes the attribute PRESENT, so `getattr` returns None rather than 0. Every
`getattr(self, X, 0)` guard in the file has the same hole.
"""
import sys
from pathlib import Path

import pytest

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

from multi_agent.runtime.delivery_gate import convergence_grace  # noqa: E402

ORCH = (THIS_DIR.parent / "env_generator" / "llm_generator" / "multi_agent"
        / "orchestrator.py").read_text(encoding="utf-8")


def test_the_pure_function_survives_a_none_counter():
    """r16's exact call: a restored None for grace_used."""
    assert convergence_grace(failed_count=1, last_shrink_age_s=10.0,
                             grace_used=None) >= 0.0


def test_a_none_counter_is_treated_as_zero_not_as_exhausted():
    """None must mean 'no grace used yet', not 'grace exhausted'."""
    got = convergence_grace(failed_count=1, last_shrink_age_s=10.0, grace_used=None)
    exp = convergence_grace(failed_count=1, last_shrink_age_s=10.0, grace_used=0)
    assert got == exp


def test_a_real_exhausted_counter_still_returns_zero():
    """The guard must keep its teeth."""
    assert convergence_grace(failed_count=1, last_shrink_age_s=10.0,
                             grace_used=99) == 0.0


def test_the_caller_does_not_let_none_escape():
    i = ORCH.index("grace_used=(getattr(self")
    seg = ORCH[i:ORCH.index("if _grace > 0:", i)]
    assert "or 0" in seg


def test_every_counter_increment_is_hardened():
    """All four `getattr(self, X, 0) + 1` sites: absent OR None must read as 0."""
    import re
    bare = re.findall(r'getattr\(self, "(_[a-z_]+(?:count|attempts))", 0\)\s*\+\s*1', ORCH)
    assert not bare, f"unhardened counter increment(s): {bare}"


def test_the_hardened_form_is_actually_present():
    """Guard against the previous test passing because the sites were deleted."""
    assert ORCH.count("or 0) + 1") >= 3


# --- the structural half: "non-fatal" must not mean "skips the rest" -------------------

def _handler_segment():
    i = ORCH.index('framework delivery raised (non-fatal)')
    return ORCH[i:ORCH.index("def _write_preview_config", i)]


def test_the_swallowed_exception_still_lets_the_lanes_hear():
    """The harm measured on r16: the gate-check dispatch sits near the END of a ~900-line
    try, so a raise anywhere earlier skipped it. Dispatches per run:

        uninterrupted   41
        resume 1         0
        resume 2         1

    Nobody was told what to fix, the failing set stopped shrinking, and the run burned
    budget until the no-convergence fail-fast killed it. The exception is still swallowed
    -- the coordination loop must not break -- but this one piece of work is retried."""
    seg = _handler_segment()
    assert "dispatch_gate_level_checks" in seg
    assert "await RemediationDispatcher(self)" in seg


def test_the_retry_is_itself_guarded():
    """A failure in the fallback must not escape the handler that exists to swallow."""
    seg = _handler_segment()
    i = seg.index("await RemediationDispatcher(self)")
    assert "try:" in seg[:i]
    assert "fallback dispatch also failed" in seg


def test_it_does_not_run_when_the_gate_never_evaluated():
    """A raise before `gate = self._validate_delivery_gate()` leaves it unbound."""
    seg = _handler_segment()
    assert "NameError" in seg
    assert "if _g_fc:" in seg


def test_the_primary_dispatch_is_still_in_the_happy_path():
    """The fallback complements the normal call; it must not have replaced it."""
    i = ORCH.index("PROPOSAL #49")
    j = ORCH.index("framework delivery raised (non-fatal)", i)
    assert "dispatch_gate_level_checks" in ORCH[i:j]
