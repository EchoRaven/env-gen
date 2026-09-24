"""FIX #286 — run_validation must record the api_smoke validation the delivery gate reads
(tiktok r68/r70/r71, live).

The delivery gate's `api_smoke_pass` (delivery_gate.py) is
    any(r.status=='passed' and r.metadata.check in {'api_smoke','api_health'}
        for r in get_validation_results())
run_validation recorded per-endpoint contract_tests (status='recorded'), build:* checks, and a
RunHub run — but never a `check=api_smoke` validation record. So a healthy app that passed
api_smoke still tripped `validation_api_smoke_missing`; the verifier was expected to hand-write
it (its prompt even claims auto-recording), drifted, and three runs idled through both
converging-grace windows to fail-fast.

Fix: run_validation emits the gate's record from its OWN pass/fail outcome — the same
deterministic-consequence principle behind the contract_test/build/runhub records it already
writes. Verified against a real hub: writing this record flips api_smoke_pass True.
ENV-AGNOSTIC + LOCAL-ONLY (agent/tests/ gitignored).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from tools.validation_tools import RunValidationTool  # noqa: E402


class _CodeHub:
    def __init__(self):
        self.calls = []

    def record_check(self, **kw):
        self.calls.append(kw)


class _Hubs:
    def __init__(self):
        self.codehub = _CodeHub()


def _tool(hubs):
    t = RunValidationTool.__new__(RunValidationTool)
    t._hubs = hubs
    return t


def test_passed_report_records_api_smoke_success():
    hubs = _Hubs()
    n = _tool(hubs)._record_api_smoke_check({"passed": True, "summary": "15/15 ok"})
    assert n == 1
    (call,) = hubs.codehub.calls
    assert call["name"] == "validation:api_smoke"
    assert call["status"] == "success"
    assert call["evidence"]["check"] == "api_smoke"
    assert call["agent"] == ""  # framework authority


def test_failed_report_records_failure_not_success():
    hubs = _Hubs()
    _tool(hubs)._record_api_smoke_check({"passed": False, "summary": "boot failed"})
    (call,) = hubs.codehub.calls
    assert call["status"] == "failure"
    assert call["evidence"]["check"] == "api_smoke"


def test_missing_codehub_is_safe():
    class _Bare:
        codehub = None
    assert _tool(_Bare())._record_api_smoke_check({"passed": True}) == 0
    assert _tool(None if False else type("H", (), {"codehub": object()})())._record_api_smoke_check({"passed": True}) == 0


def test_record_check_exception_never_raises():
    class _Boom:
        def record_check(self, **kw):
            raise RuntimeError("hub down")
    class _H:
        codehub = _Boom()
    assert _tool(_H())._record_api_smoke_check({"passed": True}) == 0


def test_gate_reads_the_record_end_to_end():
    """The record's shape must satisfy the gate's api_smoke_pass predicate: after
    get_validation_results canon, status becomes 'passed' and metadata.check=='api_smoke'."""
    from multi_agent.runtime.hub_registry import _canon_validation_status, _flatten_validation_metadata
    hubs = _Hubs()
    _tool(hubs)._record_api_smoke_check({"passed": True, "summary": "ok"})
    (call,) = hubs.codehub.calls
    assert _canon_validation_status(call["status"]) == "passed"
    md = _flatten_validation_metadata(call["evidence"])
    assert md.get("check") == "api_smoke"
