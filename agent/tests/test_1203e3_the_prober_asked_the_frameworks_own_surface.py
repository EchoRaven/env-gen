r"""#1203e3: the generic prober asked the FRAMEWORK's own endpoints, and 41% of all probe failures came from there.

`plan_probe` probed every live endpoint, including the 14 (method, path) pairs the framework
registers for itself — `/auth/register`, `/auth/login`, the four `/oauth/*`, the two
`/.well-known/*`, `/health`, and the `/api/v1/*` tenant control plane.

MEASURED over every probe record on disk, split by that list:

    the framework's fixed surface    414 probed →  171 fail   (41%)
    business endpoints            45981 probed →  203 fail   (0.4%)

A hundredfold difference in failure rate between two halves of one battery is not one half of
the app being worse. It is generic probing being wrong there: `POST /auth/login` sent `{}`
answers 401, `POST /oauth/token` answers 422 — both correct, both carrying no information about
the app — and `api_smoke` already exercises this surface PROPERLY one stage earlier with a real
body and real credentials (`auth_register_login`), while the healthcheck stage already pings
`/health`.

★ LIVE confirmation from r152, which probed this surface for the first time because #1203d6
un-skipped `implemented`: its third validation run failed on exactly five endpoints and all five
are on the list — `/oauth/register`, `GET` and `POST /oauth/authorize`, `/oauth/token`,
`/auth/login`. Four of them because the framework registers its own `schema.request` as `{}` or
`null` while its handlers require fields, so #1203e0 cannot even see those as incomplete.

And those five recur every tick, which is worse than one failing gate record:
`last_successful_run_since` requires `completed` AND `fail_count == 0`, so no NEW run can ever
qualify and the gate reads an ever-staler earlier one until `stale_build_evidence` holds the
release. r152 is only still viable because its run #2 qualified before the registry grew.

#1202kf introduced this exact list for the dead-code audit with the words "the framework's own
endpoints are not the lane's dead code". The same sentence applies to probing, so this delegates
to that function rather than restating the list.
"""
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

from multi_agent.runtime.coverage_audit import _framework_fixed_1202kf  # noqa: E402
from multi_agent.runtime.hubs.runhub.probes import (  # noqa: E402
    ProbePlan, ProbeSkip, _framework_fixed_1203e3, plan_probe)

URL = "http://localhost:8000"


def _p(method, path, status="implemented", auth=False, schema=None):
    ep = {"method": method, "path": path, "status": status, "auth_required": auth}
    if schema is not None:
        ep["schema"] = schema
    return plan_probe(ep, base_url=URL, auth_required=auth)


# ---------------------------------------------------------------- the predicate

def test_the_five_that_failed_in_r152_are_all_recognised():
    """★ The live case, verbatim from r152's third validation run."""
    for m, p in (("POST", "/oauth/register"), ("GET", "/oauth/authorize"),
                 ("POST", "/oauth/authorize"), ("POST", "/oauth/token"),
                 ("POST", "/auth/login")):
        assert _framework_fixed_1203e3({"method": m, "path": p}), (m, p)


def test_business_endpoints_are_not_the_frameworks():
    """★ The invariant: the lane's own API must keep being probed."""
    for m, p in (("GET", "/api/videos/feed"), ("POST", "/api/videos"),
                 ("GET", "/api/me"), ("POST", "/api/comments")):
        assert not _framework_fixed_1203e3({"method": m, "path": p}), (m, p)


def test_the_predicate_delegates_rather_than_restating_the_list():
    """#1202dc's rule: two consumers of one concept must not keep separate copies of it. Asserted
    by AGREEMENT on the whole list, so a divergence shows up here rather than in a run."""
    for m, p in sorted(_framework_fixed_1202kf()):
        assert _framework_fixed_1203e3({"method": m, "path": p}), (m, p)


def test_a_trailing_slash_does_not_hide_an_endpoint():
    assert _framework_fixed_1203e3({"method": "POST", "path": "/auth/login/"})


def test_the_method_is_compared_case_insensitively():
    assert _framework_fixed_1203e3({"method": "post", "path": "/auth/login"})


def test_a_different_method_on_the_same_path_is_not_covered():
    """The list is (method, path) pairs, not paths: `DELETE /auth/login` is not on it."""
    assert not _framework_fixed_1203e3({"method": "DELETE", "path": "/auth/login"})


def test_a_malformed_endpoint_does_not_raise():
    for ep in ({}, {"method": None, "path": None}, {"path": "/health"}):
        _framework_fixed_1203e3(ep)


# ---------------------------------------------------------------- the planner

def test_a_framework_endpoint_is_skipped_with_its_own_reason():
    r = _p("POST", "/auth/login", schema={"request": {"email": "str", "password": "str"}})
    assert isinstance(r, ProbeSkip) and r.reason == "framework_fixed", r


def test_oauth_token_is_skipped_even_with_an_empty_declared_schema():
    """The four that #1203e0 could not help, because the framework declares `request: {}`."""
    r = _p("POST", "/oauth/token", schema={"request": {}})
    assert isinstance(r, ProbeSkip) and r.reason == "framework_fixed", r


def test_health_is_skipped_because_the_healthcheck_stage_owns_it():
    assert isinstance(_p("GET", "/health"), ProbeSkip)


def test_a_business_endpoint_is_still_probed():
    """★ 8 business endpoints per run at the median still answer; that is the coverage that is
    about the lane's work."""
    r = _p("GET", "/api/videos/feed")
    assert isinstance(r, ProbePlan) and r.url == URL + "/api/videos/feed", r


def test_a_business_write_still_reaches_1203e0():
    """e3 must not make e0 dead: 134 non-framework endpoints with required fields remain."""
    r = _p("POST", "/api/comments", schema={"request": {"video_id": "int", "text": "str"}})
    assert isinstance(r, ProbePlan) and r.request_complete is False, r


def test_destructive_still_wins_on_a_framework_path():
    """Reason precedence: the earlier skips say more, which is why this one is placed last."""
    r = _p("DELETE", "/api/v1/tenants/{tenant_id}")
    assert isinstance(r, ProbeSkip) and r.reason == "destructive", r


def test_a_templated_framework_path_reads_as_path_params():
    """`POST /api/v1/reset` is concrete, but the tenant-delete pair is templated; the ordering
    keeps the more specific reason."""
    r = _p("GET", "/api/v1/tenants/{tenant_id}")
    assert isinstance(r, ProbeSkip) and r.reason == "path_params", r
