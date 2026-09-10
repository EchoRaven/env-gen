"""#1202je: the ledger's generic `failed` had no reason, and it is the most expensive bucket.

The terminal write names the stop through `_abort_status_1202hv` (provider or spend cap) or
`_stop_status_1202ik` (wall-clock/tick cap vs no-convergence abort). Both read a reason the run
had already latched. Everything else falls into a final `else "failed"` whose reason argument
is `_abort_1202eb or _budget_stop_1202if` — both empty by construction on that branch. The
comment two lines above it already says what that costs: "#1202if: ... the generic `failed`
erased the one sentence that explained the run." #1202if fixed the cap path and left this one.

Measured on this corpus: 8 runs carry `status: "failed"` with no reason at all, $1298 between
them. Reconstructing why r111 ($763) stopped took several passes over an 80MB log to establish
what the orchestrator knew at the moment it wrote the record — its own last failure set, its
stuck blocker, and how many times the delivery gate had declined.
"""
import sys
import pathlib

_AGENT = pathlib.Path(__file__).resolve().parents[1]
if str(_AGENT) not in sys.path:
    sys.path.insert(0, str(_AGENT))

from env_generator.llm_generator.multi_agent.orchestrator import Orchestrator  # noqa: E402


def _orch(**attrs):
    """A REAL Orchestrator, not a stand-in — a stand-in would supply attributes production
    does not have, which is how #1202fw shipped dead."""
    o = Orchestrator.__new__(Orchestrator)
    for k, v in attrs.items():
        setattr(o, k, v)
    return o


def test_it_names_what_the_run_was_stuck_on():
    """r111's shape: the gate held a failure set, a stuck blocker and declined deliveries,
    and the ledger recorded none of it."""
    r = _orch(_fwval_failure_set=frozenset({"business_chain", "docker_up"}),
              _fwval_stuck_blocker="business_chain", _fwval_stuck_count=4,
              _fwdeliver_stuck_count=3)._generic_stop_reason_1202je()
    assert "business_chain" in r and "docker_up" in r, r
    assert "4 consecutive" in r, r
    assert "declined 3" in r, r


def test_an_empty_state_says_so_rather_than_guessing():
    """"Nothing was on record" is itself the finding — it rules out the failure set as the
    cause and points at the loop's own exit. A fabricated reason would be worse than none."""
    r = _orch()._generic_stop_reason_1202je()
    assert "no framework-validation failure was on record" in r, r
    assert "business_chain" not in r


def test_it_never_raises():
    """This runs inside the terminal write's try; accounting must never be the reason a run
    fails to record itself."""
    class _Hostile:
        def __getattr__(self, k):
            raise RuntimeError("boom")
    h = _Hostile()
    h.__class__ = type("H", (_Hostile,), {
        "_generic_stop_reason_1202je": Orchestrator._generic_stop_reason_1202je})
    assert "could not be read" in h._generic_stop_reason_1202je()


def test_only_the_generic_branch_uses_it():
    """The two NAMED stops carry their own latched sentence. Overwriting those with a
    derived summary would replace a fact with an inference — and #1202hv/#1202ik exist
    precisely because the ledger was saying the wrong one of two things."""
    src = (_AGENT / "env_generator" / "llm_generator" / "multi_agent"
           / "orchestrator.py").read_text(encoding="utf-8")
    # Anchored on the NEXT LANDMARK, not a byte count: #943's ratchet exists because a
    # window sized in bytes breaks the moment a comment above it grows, and this test tripped
    # it (57 -> 58) on its first full-suite run. The terminal write's own `except` closes the
    # statement, so it is the honest end of the fragment.
    i = src.index("#1202je: the two named stops carry their own sentence")
    frag = src[i:src.index("except Exception:", i)]
    assert '_abort_1202eb or getattr(self, "_budget_stop_1202if", "")' in frag, frag
    assert 'or ("" if success else self._generic_stop_reason_1202je())' in frag, frag


def test_a_successful_run_gets_no_stop_reason():
    """`success` short-circuits it: a delivered run needs no explanation, and inventing one
    would put a failure sentence on a clean record."""
    src = (_AGENT / "env_generator" / "llm_generator" / "multi_agent"
           / "orchestrator.py").read_text(encoding="utf-8")
    assert '"" if success else self._generic_stop_reason_1202je()' in src
