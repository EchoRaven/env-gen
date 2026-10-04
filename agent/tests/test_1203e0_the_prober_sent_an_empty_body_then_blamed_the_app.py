r"""#1203e0: the prober sent `{}`, then scored the app's correct rejection as a failure.

`plan_probe` builds a write's body as `example_body if example_body is not None else {}`, and
its ONE caller (`runhub/service.py`) never passes an `example_body`. So every POST/PUT/PATCH
probe sends an empty object, and a handler whose contract requires fields answers 400 or 422 --
correctly. `classify_probe_result` scored that through its catch-all as
`fail` P2 "unexpected status 422", and `deliverability` turns `fail_count > 0` into the blocker
"latest run has N failed endpoint probe(s)", which cannot self-clear: the next tick sends `{}`
again.

MEASURED over every run directory: of the 369 failing probe records on disk, **115 are
`unexpected status 422` and 32 are `unexpected status 400` — 147, 40% of all probe failures**.
The endpoints are `POST /auth/register` (7), `/oauth/authorize` (7), `/oauth/token` (7),
`POST /auth/signup`, `/api/auth/login`, `/api/v1/tenants` — the framework's own fixed contract
surface. (The other buckets: 401 159, 404 61 of which 50 were the templated paths #1203d9 just
stopped asking, 500 one, 405 one.)

★ It had been largely HIDDEN by a second defect. The pre-#1203d6 status rule skipped
`implemented` endpoints, so by the time validation ran the auth pair was usually already
promoted and never asked — r149 has zero failing probes for this reason. Fixing d6 removed the
shield, which is `feedback_new_path_reopens_settled_judgements` happening to my own patch:
**r151 was stopped nine minutes in at $11.70** once its live registry showed `POST /auth/register`
and `POST /auth/login` heading for exactly this, on FRAMEWORK-OWNED endpoints, permanently.

The fix is not to stop asking. A write probe's real question is "is this route wired", and the
answers still separate cleanly: 404 = not wired (fail), 5xx = wired but crashing (fail),
400/422 on a request we could not make well-formed = wired and validating. That mirrors the
precedent one line above it in the same function — `401/403 when auth_required -> pass,
"auth-protected as expected"` — an error status that is the correct answer to THIS probe.

Not masking: a 400 on a request whose declared fields are ALL optional stays a failure, because
then the endpoint was asked properly and refused anyway. That distinction is tested below.
"""
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

from multi_agent.runtime.hubs.runhub.probes import (  # noqa: E402
    ProbePlan, ProbeSkip, _required_request_fields_1203e0, classify_probe_result, plan_probe)

URL = "http://localhost:8000"
# ★ #1203e3 note: this used to be `POST /auth/register`, which is the shape that stopped r151 —
# but e3 now skips the framework's own fixed surface BEFORE the body is built, so that endpoint
# can no longer reach this code and a fixture using it would test an unreachable path. The field
# list is kept verbatim (two required, two optional) on a BUSINESS write, which is where the
# remaining 134 corpus cases live. See test_a_framework_endpoint_never_reaches_this_clause.
REGISTER = {"method": "POST", "path": "/api/comments", "status": "implemented",
            "auth_required": False,
            "schema": {"request": {"email": "str", "password": "str",
                                   "name": "str?", "tenant_id": "str?"}}}


def _plan(ep, **kw):
    return plan_probe(ep, base_url=URL, auth_required=bool(ep.get("auth_required")), **kw)


# ---------------------------------------------------------------- the predicate

def test_r151s_register_declares_two_required_fields():
    """★ The live field list that stopped r151, verbatim (on a business path — see REGISTER)."""
    assert _required_request_fields_1203e0(REGISTER) == {"email", "password"}


def test_optional_fields_are_not_required():
    ep = {"schema": {"request": {"limit": "int?", "cursor": "str?"}}}
    assert _required_request_fields_1203e0(ep) == set()


def test_a_non_string_type_counts_as_required():
    """Not a guess: the prober supplies NOTHING, so anything declared is unsent. 48 records
    carry a dict value and 5 a bool."""
    ep = {"schema": {"request": {"profile": {"id": "int"}, "flag": True}}}
    assert _required_request_fields_1203e0(ep) == {"profile", "flag"}


def test_a_missing_or_malformed_schema_yields_nothing():
    for ep in ({}, {"schema": None}, {"schema": {}}, {"schema": {"request": None}},
               {"schema": {"request": []}}, {"schema": "nope"}):
        assert _required_request_fields_1203e0(ep) == set(), ep


# ---------------------------------------------------------------- the plan

def test_the_plan_records_that_it_could_not_ask_properly():
    """★ The fact, carried where the classifier can read it."""
    p = _plan(REGISTER)
    assert isinstance(p, ProbePlan) and p.request_complete is False, p


def test_an_all_optional_write_is_a_complete_request():
    """The empty body genuinely satisfies this contract, so a 400 here IS the handler's."""
    ep = {"method": "POST", "path": "/api/ping", "status": "implemented",
          "schema": {"request": {"note": "str?"}}}
    assert _plan(ep).request_complete is True


def test_a_get_with_required_query_params_is_incomplete():
    """47 of 1907 probeable GETs declare required fields -- `/api/search` needs `q`."""
    ep = {"method": "GET", "path": "/api/search", "status": "implemented",
          "schema": {"request": {"q": "str"}}}
    assert _plan(ep).request_complete is False


def test_a_plain_get_is_complete():
    ep = {"method": "GET", "path": "/api/videos/feed", "status": "implemented"}
    assert _plan(ep).request_complete is True


def test_a_supplied_example_body_makes_the_request_complete():
    """★ The flag is a set DIFFERENCE, not a hard-coded no: the day a caller passes a body, the
    endpoints it covers become complete with no second place to update."""
    p = _plan(REGISTER, example_body={"email": "a@b.c", "password": "x"})
    assert p.request_complete is True
    assert p.body == {"email": "a@b.c", "password": "x"}


def test_a_partially_supplied_body_is_still_incomplete():
    assert _plan(REGISTER, example_body={"email": "a@b.c"}).request_complete is False


def test_the_default_keeps_every_other_construction_honest():
    """A ProbePlan built anywhere else must not silently claim incompleteness."""
    assert ProbePlan(method="GET", url=URL).request_complete is True


# ---------------------------------------------------------------- the classification

def test_a_422_on_an_unaskable_request_is_not_the_handlers_fault():
    """★ The defect, in one assertion: 115 of the 369 failures on disk."""
    o = classify_probe_result(422, "", auth_required=False, request_complete=False)
    assert o.verdict == "pass", o
    assert "route wired" in o.note and "malformed question" in o.note, o.note


def test_a_400_on_an_unaskable_request_likewise():
    """32 of the 369."""
    assert classify_probe_result(400, "", auth_required=False,
                                 request_complete=False).verdict == "pass"


def test_the_note_says_what_was_not_established():
    """#1202vx: the operator must not over-read this. The note has to name the two answers that
    WOULD have been about the handler."""
    n = classify_probe_result(422, "", auth_required=False, request_complete=False).note
    assert "404" in n and "5xx" in n, n


def test_a_400_on_a_well_formed_request_still_fails():
    """★ Not masking: when the probe asked properly and was refused, that is the handler's."""
    o = classify_probe_result(400, "", auth_required=False, request_complete=True)
    assert o.verdict == "fail" and o.severity == "P2", o


def test_404_still_fails_even_when_the_request_was_unaskable():
    """The route-not-wired signal is the whole point of probing a write; it must survive."""
    o = classify_probe_result(404, "", auth_required=False, request_complete=False)
    assert o.verdict == "fail" and o.severity == "P1", o


def test_500_still_fails_even_when_the_request_was_unaskable():
    """A handler that crashes on a malformed body is still a handler that crashes."""
    o = classify_probe_result(500, "", auth_required=False, request_complete=False)
    assert o.verdict == "fail" and o.severity == "P1", o


def test_405_still_fails_even_when_the_request_was_unaskable():
    o = classify_probe_result(405, "", auth_required=False, request_complete=False,
                              headers={"Allow": "GET"})
    assert o.verdict == "fail" and o.severity == "P1", o


def test_an_unrelated_4xx_still_fails():
    """409, 429 and friends are not about request shape and must not be excused."""
    for code in (409, 418, 429):
        o = classify_probe_result(code, "", auth_required=False, request_complete=False)
        assert o.verdict == "fail", (code, o)


def test_the_default_preserves_every_existing_caller():
    """Omitting the argument must behave exactly as before #1203e0."""
    assert classify_probe_result(422, "", auth_required=False).verdict == "fail"
    assert classify_probe_result(400, "", auth_required=False).verdict == "fail"


# ---------------------------------------------------------------- the wiring

def test_the_service_hands_the_flag_to_the_classifier():
    """The measurement is worthless if the call site drops it (#1202wk). Located between two
    landmarks, never a byte window (#943)."""
    import inspect
    from multi_agent.runtime.hubs.runhub import service as SV
    src = inspect.getsource(SV)
    i = src.index("outcome = classify_probe_result(")
    j = src.index("probe_record = {", i)
    assert "request_complete=" in src[i:j], src[i:j]


def test_a_framework_endpoint_never_reaches_this_clause():
    """★ #1203e3 took over the case this patch was written for. `POST /auth/register` is on the
    framework's fixed list and is now skipped before a body is built, so #1203e0's remaining job
    is the 134 non-framework endpoints that declare required fields. Pinned so the two patches
    cannot silently start fighting over the same endpoint."""
    r = plan_probe({"method": "POST", "path": "/auth/register", "status": "implemented",
                    "schema": {"request": {"email": "str", "password": "str"}}},
                   base_url=URL, auth_required=False)
    assert isinstance(r, ProbeSkip) and r.reason == "framework_fixed", r
