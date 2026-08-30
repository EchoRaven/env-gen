"""#553 (netflix r105, 2026-08-06) — a TRANSIENT business_chain failure at the FINAL
delivery gate must not kill an otherwise fully-green run, and a correctly-rejected 401
(a tokenless request to an auth-required endpoint that a negative-test step EXPECTS)
must score PASS — while a GENUINE failure (5xx, or a 2xx-expected step returning 4xx)
must still FAIL.

GROUND TRUTH (r105 log ~22:41 + registryhub_verification_chains.json): the run exited
rc=1 with NO release on ['business_chain_failing'] though Part-A was solved
(blocking_average 0.6825) and the app delivered 6× (r99-r104). At the final gate the
chain registry showed `auth_register_login_round_trip` failing on a SINGLE
`POST /auth/login → 500` while two IDENTICAL register→login chains PASSED in the SAME
run pass (a transient), and `tenant_lifecycle` failing on a control-plane 400 (already
#486-filtered — it touches no business endpoint). The `auth_required_endpoints_enforce_
401` negative-test chain PASSED — so the 401 the log shows was the Verifier's OWN manual
test_api probe, NOT a mis-scored chain step. The final-gate readiness retry only WAITS +
RE-READS the stale registry (it NEVER re-executes the chains), and the visual-ESCAPE
delivery path leaves `_milestone_gate_cleared_at` unset so the #139 drift-waiver could
not fire → immediate rc=1.

These tests lock:
  (1) a negative-test step (expect [401,403]) that gets a 401 on a tokenless request to
      an auth-required endpoint scores PASS (broken == []);
  (2) a real 5xx on a 2xx-expecting step FAILS (broken non-empty, names the 5xx);
  (3) a 2xx-expecting step that gets a deterministic 4xx FAILS (broken non-empty);
  (4) the final-gate convergence DECISION: on the visual-escape path (no milestone-clear
      stamp) a `business_chain_failing`-only gate is NOT immediately raised — it is
      re-validation-warranted (a bounded re-run happens before raising); a STRUCTURAL
      failure (docker/contract/build) is NOT warranted and raises immediately; and the
      decision is pure (never forces the gate green — a genuine re-fail still raises).
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from env_generator.llm_generator.multi_agent.runtime.chain_executor import execute_chain
from env_generator.llm_generator.multi_agent.orchestrator import (
    REVALIDATION_FIXABLE_CHECKS,
    FINAL_GATE_DRIFT_CLASSES,
    _final_gate_drift_waiver,
    _final_gate_revalidation_warranted,
    _fwval_can_early_return,
)


# ─────────────────────────── in-process app under test ───────────────────────────
class _Handler(BaseHTTPRequestHandler):
    """A minimal, CORRECT auth-enforcing app: /auth/* mint a token, /api/titles
    requires a Bearer (tokenless → 401), plus two deterministically-failing routes
    (/api/broken → 500, /api/reject → 400) to prove real failures still block."""

    def log_message(self, *_a):  # silence the test server
        return

    def _send(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def _has_bearer(self):
        return bool((self.headers.get("Authorization") or "").lower().startswith("bearer "))

    def do_POST(self):
        self._read_body()
        path = self.path.split("?", 1)[0].rstrip("/")
        if path in ("/auth/register", "/auth/login"):
            return self._send(200, {"access_token": "tok-abc", "id": 1,
                                    "email": "a@b.com"})
        if path == "/api/broken":
            return self._send(500, {"detail": "Internal Server Error"})
        if path == "/api/reject":
            return self._send(400, {"detail": "not allowed"})
        return self._send(404, {"detail": "Not Found"})

    def do_GET(self):
        path = self.path.split("?", 1)[0].rstrip("/")
        if path == "/api/titles":
            if self._has_bearer():
                return self._send(200, [{"id": 1, "title": "X"}])
            return self._send(401, {"detail": "authentication required"})
        return self._send(404, {"detail": "Not Found"})


@pytest.fixture()
def base_url():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}"
    finally:
        srv.shutdown()
        srv.server_close()


_REGISTER = {"method": "POST", "path": "/auth/register", "expect": [200, 201],
             "save": {"token": "access_token"},
             "body": {"email": "a@b.com", "password": "Pw123!x", "name": "T"}}


# ─────────────────────────── (1) correct-401 scores PASS ───────────────────────────
def test_negative_test_401_on_auth_required_endpoint_scores_pass(base_url):
    """A step whose endpoint requires auth and whose TOKENLESS request returns 401 is
    the EXPECTED outcome (expect [401,403]) — it must NOT count as a chain failure."""
    chain = {"name": "auth_enforced_probe", "steps": [
        _REGISTER,
        # tokenless (no `auth` ref) GET of a protected endpoint — 401 is CORRECT.
        {"method": "GET", "path": "/api/titles", "expect": [401, 403]},
    ]}
    res = execute_chain(base_url, chain, endpoints=[])
    assert res["broken"] == [], f"correct-401 wrongly scored broken: {res['broken']}"


def test_authed_read_of_same_endpoint_still_passes(base_url):
    """The positive arm: the SAME auth-required endpoint, hit WITH a minted token,
    returns 200 and passes — proving the token round-trip is carried on protected steps."""
    chain = {"name": "auth_roundtrip", "steps": [
        _REGISTER,
        {"method": "GET", "path": "/api/titles", "expect": [200], "auth": "token"},
        {"method": "GET", "path": "/api/titles", "expect": [401, 403]},  # negative arm
    ]}
    res = execute_chain(base_url, chain, endpoints=[])
    assert res["broken"] == [], f"authed round-trip wrongly broke: {res['broken']}"


# ─────────────────────────── (2)+(3) real failures still FAIL ───────────────────────────
def test_real_5xx_on_success_step_still_fails(base_url):
    """A 2xx-expecting step that 500s is a GENUINE break and MUST block delivery —
    the convergence fix must never mask this (a create 500ing is a real bug)."""
    chain = {"name": "create_flow", "steps": [
        _REGISTER,
        {"method": "POST", "path": "/api/broken", "expect": [200, 201],
         "auth": "token", "body": {"x": 1}},
    ]}
    res = execute_chain(base_url, chain, endpoints=[])
    assert res["broken"], "a real 500 on a success step must fail the chain"
    assert any("500" in b for b in res["broken"]), res["broken"]


def test_2xx_expected_step_returning_4xx_still_fails(base_url):
    """A step that EXPECTS success but gets a deterministic 4xx (not an auth-negative
    step — it carries a token and expects 2xx) is a real flow failure and must block."""
    chain = {"name": "reject_flow", "steps": [
        _REGISTER,
        {"method": "POST", "path": "/api/reject", "expect": [200, 201],
         "auth": "token", "body": {"foo": "bar"}},
    ]}
    res = execute_chain(base_url, chain, endpoints=[])
    assert res["broken"], "a 2xx-expected step returning 4xx must fail the chain"
    assert any("400" in b for b in res["broken"]), res["broken"]


# ─────────────────────────── (4) final-gate convergence decision ───────────────────────────
def test_constants_shared_and_membership():
    assert REVALIDATION_FIXABLE_CHECKS == frozenset(
        {"business_chain_failing", "verification_checklist_not_ready"})
    # #1184: these were ONE object ("single source of truth"), and that identity is why the
    # #139 drift waiver never fired in seven runs. They answer different questions:
    # REVALIDATION_FIXABLE asks "can re-running validation clear this?" (chains, checklists);
    # DRIFT_CLASSES asks "is this mutable hub state a lane wrote during the delivery tail?".
    # All three observed final-gate rejections — r17/r18 validation_ui_evidence_failed, r20
    # unresolved_failed_tasks — were the second kind and none was the first. The revalidation
    # set is unchanged; the drift set now contains it.
    assert REVALIDATION_FIXABLE_CHECKS < FINAL_GATE_DRIFT_CLASSES
    assert FINAL_GATE_DRIFT_CLASSES - REVALIDATION_FIXABLE_CHECKS == frozenset(
        {"validation_ui_evidence_failed", "unresolved_failed_tasks"})


@pytest.mark.parametrize("failed,expected", [
    ({"business_chain_failing"}, True),
    ({"verification_checklist_not_ready"}, True),
    ({"business_chain_failing", "verification_checklist_not_ready"}, True),
    (set(), False),                                   # nothing failed → nothing to re-run
    ({"docker_up_failed"}, False),                    # structural → raise immediately
    ({"contract_alignment"}, False),                  # structural → raise immediately
    ({"business_chain_failing", "docker_up_failed"}, False),  # any structural disqualifies
])
def test_final_gate_revalidation_warranted(failed, expected):
    assert _final_gate_revalidation_warranted(failed) is expected


def test_escape_path_reruns_before_raising_but_structural_raises():
    """The r105 escape-path contract, expressed via the two decision helpers the final
    gate uses in sequence. On the visual-ESCAPE path _milestone_gate_cleared_at is None,
    so the #139 drift-waiver CANNOT fire — but a business_chain_failing-only gate is
    re-validation-warranted, so a bounded re-run happens BEFORE raising. A structural
    failure is neither waived nor re-run → it raises immediately."""
    now = 1_000_000.0
    escape_failed = {"business_chain_failing"}
    # escape path: no milestone-clear stamp → drift waiver unavailable ...
    assert _final_gate_drift_waiver(None, escape_failed, now) is False
    # ... but the re-run IS warranted (converge before rc=1).
    assert _final_gate_revalidation_warranted(escape_failed) is True

    structural = {"docker_up_failed"}
    assert _final_gate_drift_waiver(None, structural, now) is False
    assert _final_gate_revalidation_warranted(structural) is False  # raises immediately


def test_revalidation_decision_is_pure_and_does_not_force_green():
    """The decision only chooses WHETHER to re-run; it never asserts the gate passed —
    so a genuine re-fail after the re-run still raises (the final gate re-evaluates and
    only delivers if _validate_delivery_gate() itself returns ok)."""
    failed = {"business_chain_failing"}
    snapshot = set(failed)
    assert _final_gate_revalidation_warranted(failed) is True
    assert failed == snapshot  # not mutated
    # early-return guard shares the same set: business_chain_failing keeps the
    # coordination loop RUNNING (so validation re-runs), never early-returns.
    assert _fwval_can_early_return(True, ["business_chain_failing"]) is False
    assert _fwval_can_early_return(True, ["ui_page_unwired"]) is True
