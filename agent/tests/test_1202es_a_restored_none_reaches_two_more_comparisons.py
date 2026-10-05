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
    # #1203fj: anchored on "not followed by `or`" instead of on a trailing COMMA. The comma
    # form is only how a bare read looks when it is NOT the last argument -- which is the one
    # thing about a call site most likely to change. It did: adding a third `%s` to the squad
    # escape's warning turned `..., 0))` into `..., 0),` and this assertion fired on a read
    # that had been sitting there unhardened, invisible, the whole time.
    assert f'getattr(self, "{field}", 0)' not in ORCH.replace(
        f'(getattr(self, "{field}", 0) or 0)', ""), f"{field} call site unhardened"
    assert f'(getattr(self, "{field}", 0) or 0)' in ORCH


def test_no_persisted_counter_is_read_bare_into_a_comparison():
    """The class, not the three instances — so a fourth cannot be added quietly.

    #1203fj widened this two ways after the comma anchor let three reads through:

      * the PATTERN is "a bare read not followed by `or`", so argument position no longer
        decides whether the ratchet can see it;
      * the SCOPE is the whole multi_agent tree, not orchestrator.py. The three it had been
        missing are elsewhere: `_fwdeliver_grace_count` (delivery_gate),
        `_framework_validation_attempts` and `_fwval_stuck_count` (framework_validation) --
        and all three are in `milestone_resume`'s restored field lists, i.e. the same class
        this ratchet exists for.

    Those three were hardened with the widening, and NOT because a None could reach them
    today: #1202el's `_MISSING_1202EL` sentinel stopped the save side writing an absent
    attribute as null (the googlemaps-r16 failure), and nothing in the package assigns any of
    them None. They were hardened because the rule has to be uniform for the ratchet to mean
    "a fourth cannot be added quietly" -- the next one will be written by someone who has not
    read #1202el.

    `_ask_cap_count` (agents/runtime/preconditions.py) is deliberately out: it appears in that
    one file and in no resume or snapshot field list, so no restore can hand it a None. If it
    ever joins one, this sweep will start naming it.
    """
    import re
    from pathlib import Path as _P
    _root = _P(__file__).resolve().parents[1] / "env_generator" / "llm_generator" / "multi_agent"
    _pat = re.compile(r'getattr\((?:self|orch|[a-z_]+), "(_[a-z_]*(?:attempts|count|used))", 0\)'
                      r'(?!\s*or\b)')
    _exempt = {"_ask_cap_count"}
    bare = []
    for _f in sorted(_root.rglob("*.py")):
        for _m in _pat.finditer(_f.read_text(encoding="utf-8", errors="ignore")):
            if _m.group(1) in _exempt:
                continue
            bare.append("%s:%s" % (_f.name, _m.group(1)))
    assert not bare, f"unhardened persisted-counter reads: {sorted(set(bare))}"
