r"""#1202es: #1202em hardened the increments and missed the reads that feed comparisons.

#1202el established the shape: `save_gate_counters_1202ce` persisted never-set attributes
as null, restore wrote them back, and `getattr(self, X, 0)` then returns None because the
attribute EXISTS. #1202em hardened all six `getattr(self, X, 0) + 1` increments.

Searching for siblings with the same pattern — a persisted field read with a non-None
default and passed somewhere it is COMPARED — found three more, all reachable on a resume
and all three fields sitting as null in googlemaps-r16's milestone_gates.json:

    squad_release_decision()      `if attempts >= max_attempts`
        <- _rc_attempts           (orchestrator.py:4934)
        <- _tu_browser_attempts   (orchestrator.py:4871)
    _abort_grace_should_defer()   `if grace_used >= grace_max`
        <- _fwval_abort_grace_used (orchestrator.py:2684)

Hardened at both ends, as #1202em did: the pure functions guard themselves so any caller
is safe, and the call sites do not let a None leave the orchestrator.
"""
import sys
from pathlib import Path

import pytest

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

from multi_agent.runtime.test_user_squad import squad_release_decision  # noqa: E402

ORCH = (THIS_DIR.parent / "env_generator" / "llm_generator" / "multi_agent"
        / "orchestrator.py").read_text(encoding="utf-8")


def test_squad_release_survives_a_restored_none():
    """r16's shape: _rc_attempts / _tu_browser_attempts restored as None."""
    assert squad_release_decision(None, None, 1000.0)          # must not raise


def test_none_attempts_means_none_used_not_exhausted():
    got = squad_release_decision(None, None, 1000.0)
    exp = squad_release_decision(None, 0, 1000.0)
    assert got == exp


def test_a_real_exhausted_count_still_releases():
    """The guard keeps its teeth."""
    assert squad_release_decision(None, 99, 1000.0) == squad_release_decision(None, 3, 1000.0)


def test_the_abort_grace_predicate_survives_a_restored_none():
    from multi_agent.orchestrator import _abort_grace_should_defer
    _abort_grace_should_defer(True, None, "sig", "sig")          # must not raise


def test_the_abort_grace_predicate_keeps_its_ceiling():
    from multi_agent.orchestrator import _abort_grace_should_defer
    import inspect
    sig = inspect.signature(_abort_grace_should_defer)
    gmax = sig.parameters["grace_max"].default if "grace_max" in sig.parameters else 1
    assert _abort_grace_should_defer(True, gmax + 5, "sig", "sig") is False


@pytest.mark.parametrize("field", ["_fwval_abort_grace_used", "_rc_attempts",
                                   "_tu_browser_attempts", "_pages_gate_attempts",
                                   "_tu_squad_attempts"])
def test_the_call_sites_do_not_let_a_none_escape(field):
    assert f'getattr(self, "{field}", 0),' not in ORCH, f"{field} call site unhardened"
    assert f'(getattr(self, "{field}", 0) or 0)' in ORCH


def test_no_persisted_counter_is_read_bare_into_a_comparison():
    """The class, not the three instances — so a fourth cannot be added quietly."""
    import re
    bare = re.findall(r'getattr\(self, "(_[a-z_]*(?:attempts|count|used))", 0\),', ORCH)
    assert not bare, f"unhardened persisted-counter reads: {sorted(set(bare))}"
