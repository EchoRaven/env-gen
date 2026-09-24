"""All-2xx chain expects accept any 2xx; non-2xx expects stay exact (run-26+29, 2026-07-01).

The verifier GUESSES each step's exact success code — `expect: [200]` on an rsvp the handler
implements as a 201-create, [200] on a 204-delete. Strict membership failed the WHOLE
business_chain forever on a WORKING flow (outlook run-29 live: rsvp 201-vs-[200] wedged 4+
validation cycles; run-26 M3 flagged the same class). _status_ok now treats an ALL-2xx expect
list as "this step succeeds" (any 2xx passes); an expect carrying ANY non-2xx — isolation
probes [403,404], mixed [200,404] — keeps EXACT matching so a 200 never satisfies an
expected-denial probe. ENV-AGNOSTIC + LOCAL-ONLY (agent/tests/ gitignored).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.chain_executor import _status_ok  # noqa: E402


def test_exact_match_still_passes():
    assert _status_ok(200, [200]) and _status_ok(404, [404]) and _status_ok(409, [201, 409])


def test_success_family_tolerance():
    assert _status_ok(201, [200]) is True          # run-29 rsvp: create-status vs authored 200
    assert _status_ok(204, [200]) is True          # no-content delete vs authored 200
    assert _status_ok(200, [201]) is True
    assert _status_ok(202, [200, 201]) is True


def test_non_2xx_expectations_stay_exact():
    assert _status_ok(200, [403, 404]) is False    # isolation probe: success must NOT satisfy denial
    assert _status_ok(201, [403]) is False
    assert _status_ok(200, [200, 404]) is True     # exact member
    # (FIX #104 contract update: a 2xx actual with ANY 2xx member in a mixed list now
    # PASSES — run-21 M3 live wedged a working flow on 201-vs-[200,404]. The denial-
    # safety assertions above are the load-bearing ones and are unchanged.)
    assert _status_ok(201, [200, 404]) is True
    assert _status_ok(302, [301]) is False         # non-2xx families stay exact


def test_failures_still_fail():
    assert _status_ok(500, [200]) is False
    assert _status_ok(422, [200, 201]) is False
    assert _status_ok(None, [200]) is False


def test_empty_expect_any_2xx():
    assert _status_ok(204, []) is True
    assert _status_ok(404, []) is False


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))


def test_mixed_expect_with_any_2xx_accepts_success_family():
    """FIX #104 (run-21 M3 live): expect [200, 404] + actual 201 wedged the chain — the
    mixed list disabled the all-2xx family rule, but the verifier's intent decomposes to
    'success OR tolerated-404'; a 201 IS the success arm. A 2xx actual now passes when
    the expect contains ANY 2xx member. Pure denial probes ([401]/[403,404]) contain no
    2xx and still reject success statuses."""
    import multi_agent.runtime.chain_executor as ce
    assert ce._status_ok(201, [200, 404]) is True     # the run-21 wedge
    assert ce._status_ok(204, [200, 404]) is True
    assert ce._status_ok(404, [200, 404]) is True     # tolerated arm unchanged
    assert ce._status_ok(403, [200, 404]) is False    # non-member non-2xx still fails
    assert ce._status_ok(200, [401]) is False         # pure denial probe: leak still fails
    assert ce._status_ok(201, [403, 404]) is False
