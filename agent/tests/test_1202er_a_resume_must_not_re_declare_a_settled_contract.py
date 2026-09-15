r"""#1202er: two corrective LLM turns per attendee, on every resume, to rediscover that the
contract already exists.

The corrective turns exist because a lane sometimes drops or empties its kickoff section
(gemini did, when the inline JSON argument got long). On a RESUME the section is missing
for a different reason: the contract was settled by the earlier process and the lane has
nothing new to declare.

googlemaps-r16's resumes were rejected with

    kickoff-initial REJECTED: section='backend' has no substantive endpoint +
    data-model/table decisions

while RegistryHub already held 50 endpoints and 27 tables. Cost: two corrective turns per
attendee and ~250s of kickoff, every time.

This does NOT widen what counts as substantive. It skips to the terminal path the code
already takes once the turns are exhausted — the deferred stub, whose own note says "the
deterministic reconcile fills this section's gaps FROM THE CONTRACT". When the contract is
complete the reconcile has everything it needs; the turns can only rediscover that at LLM
prices. A fresh run with an incomplete contract is corrected exactly as before.
"""
import sys
from pathlib import Path

import pytest

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

MSG = (THIS_DIR.parent / "env_generator" / "llm_generator" / "multi_agent" / "agents"
       / "runtime" / "messaging.py").read_text(encoding="utf-8")


class _Hub:
    def __init__(self, eps, tbls):
        self._e, self._t = eps, tbls
    def get_endpoints(self): return self._e
    def list_tables(self): return self._t


class _Store:
    def __init__(self, d): self._d = d
    def value(self): return self._d


class _Hubs:
    def __init__(self, rh, documents=None):
        self.registryhub = rh
        self.workhub = type("W", (), {})()
        self.workhub.stores = type("S", (), {})()
        self.workhub.stores.documents = _Store(documents or {})


class _Agent:
    def __init__(self, rh, documents=None): self._hubs = _Hubs(rh, documents)


def _closed_kickoff(ms):
    return {"kind": "kickoff", "status": "closed",
            "metadata": {"milestone_index": ms,
                         "produced_artifacts": ["contract", "task_tree", "predicates"]}}


def _pred():
    from multi_agent.agents.runtime.messaging import AgentMessaging  # noqa: E402
    return AgentMessaging._contract_already_complete_1202er


def test_a_settled_contract_is_recognised():
    """r16's real shape: a RESUME. 50 endpoints and 27 tables in the registry AND an
    earlier kickoff for the same milestone that already closed with a contract.

    The first version of this test carried only the registry, which made it assert
    "registry non-empty means settled" — the milestone-blind reading #1202mo corrects.
    The meeting history is the part of r16's real shape that made it a resume.
    """
    a = _Agent(_Hub({f"e{i}": {} for i in range(50)}, {f"t{i}": {} for i in range(27)}),
               documents={"doc_earlier": _closed_kickoff(1)})
    assert _pred()(a, meeting_id="doc_resume", milestone_index=1) is True


def test_a_later_milestone_is_not_settled_by_an_earlier_ones_contract():
    """The case this file's docstring missed: it says a FRESH run with an incomplete
    contract is still corrected, and never considered M2 — not fresh, and its own
    contract not yet declared. tiktok-r123's M2 added 14 endpoints the registry did
    not have while this predicate told its lanes the contract was complete."""
    a = _Agent(_Hub({f"e{i}": {} for i in range(16)}, {f"t{i}": {} for i in range(5)}),
               documents={"doc_m1": _closed_kickoff(1)})
    assert _pred()(a, meeting_id="doc_m2", milestone_index=2) is False


def test_an_empty_contract_is_not():
    assert _pred()(_Agent(_Hub({}, {}))) is False


def test_a_half_built_contract_is_not():
    """Endpoints but no tables is exactly what the corrective turns are FOR."""
    assert _pred()(_Agent(_Hub({"e": {}}, {}))) is False
    assert _pred()(_Agent(_Hub({}, {"t": {}}))) is False


def test_a_missing_hub_answers_false():
    class _NoHub:
        _hubs = None
    assert _pred()(_NoHub()) is False


def test_a_raising_hub_answers_false():
    class _Boom:
        def get_endpoints(self): raise RuntimeError("hub down")
        def list_tables(self): return {}
    assert _pred()(_Agent(_Boom())) is False


def test_it_short_circuits_the_corrective_loop():
    i = MSG.index("for _attempt in range(2):")
    seg = MSG[i:MSG.index("await self.run_agentic_loop(", i)]
    # the call now passes its milestone scope (#1202mo), so match the name, not "()"
    assert "_contract_already_complete_1202er(" in seg
    assert "break" in seg


def test_it_does_not_widen_what_counts_as_substantive():
    """The substance predicate itself must be untouched — this only skips the retries."""
    i = MSG.index("def _has_substantive_section")
    seg = MSG[i:MSG.index("def _ensure_initial_section_decision", i)]
    assert "1202er" not in seg


def test_the_terminal_stub_path_is_unchanged():
    """The deferred stub — and the reconcile behind it — is what now runs sooner."""
    assert '"deferred": True' in MSG
    assert "auto_backup" in MSG
