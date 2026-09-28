"""#1202wj: a refusal of an ANONYMOUS request is not evidence of cross-user isolation.

FIX #192a injects a framework cross-user probe -- an intruder PUT on the item shape,
expecting 403/404 -- but only "when the chain has no denial step". That test is hand-rolled
as "expect contains 401 or 403", while this same file already carries
`_is_cross_user_denial`, whose docstring says the opposite of half of it: "NOT an
auth-roundtrip 401 (no token)". So a chain whose only denial is `no token -> 401` counts as
isolation coverage and the probe is suppressed, although nothing in that chain ever asks
whether one user may touch another user's row.

That is #1202vb's lesson one level up: `auth_enforced_401` proves a request carrying NO
token is refused and says nothing about who a token belongs to.

MEASURED over the corpus's 4630 chains: 927 have a tokenless 401 and no cross-user denial,
and 217 of those satisfy every other precondition of the probe.

THE PROBE IS STILL NOT INJECTED FOR THEM, deliberately. It expects 403/404 from "the
PROJECTED owner-safe write handler BY CONSTRUCTION (writes stay projected)", and that
premise is false in this corpus: of the runs defining an item PUT at all, netflix-r30 and 20
others define the SAME path in custom_routes.py too, so the request may be served by a lane
handler whose ownership behaviour is unknown. Widening a BLOCKING probe onto a premise
measured false trades a silent gap for false failures. This reports the gap and changes no
verdict.
"""
import logging
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

from multi_agent.runtime.chain_executor import (  # noqa: E402
    _is_cross_user_denial,
    normalize_steps,
)

_REGISTER = {"method": "POST", "path": "/auth/register", "expect": [200, 201],
             "save": {"tokenA": "access_token"}}


def _warned(caplog):
    return [r.getMessage() for r in caplog.records if "#1202wj" in r.getMessage()]


def test_a_tokenless_denial_alone_is_announced(caplog):
    with caplog.at_level(logging.WARNING):
        normalize_steps([dict(_REGISTER),
                         {"method": "GET", "path": "/api/videos", "expect": [401]}])
    assert _warned(caplog), (
        "a 401 for an anonymous request suppressed the cross-user probe silently")


def test_a_cross_user_denial_is_not_announced(caplog):
    with caplog.at_level(logging.WARNING):
        normalize_steps([dict(_REGISTER),
                         {"method": "PUT", "path": "/api/videos/1", "expect": [403]}])
    assert not _warned(caplog), _warned(caplog)


def test_a_404_denial_counts_as_cross_user(caplog):
    """#192a's own contract: a leaked row is masked as 404, so 404 is a denial too."""
    with caplog.at_level(logging.WARNING):
        normalize_steps([dict(_REGISTER),
                         {"method": "PUT", "path": "/api/videos/1", "expect": [404]}])
    assert not _warned(caplog), _warned(caplog)


def test_a_chain_with_no_denial_at_all_is_not_announced(caplog):
    """That case is the probe's own: it gets injected, so there is nothing to report."""
    with caplog.at_level(logging.WARNING):
        normalize_steps([dict(_REGISTER),
                         {"method": "GET", "path": "/api/videos", "expect": [200]}])
    assert not _warned(caplog), _warned(caplog)


def test_the_predicate_this_uses_excludes_the_tokenless_401():
    """★ The whole defect in one assertion: the correct predicate already existed."""
    assert not _is_cross_user_denial({"expect": [401]})
    assert _is_cross_user_denial({"expect": [403]})
    assert _is_cross_user_denial({"expect": [404]})
    assert not _is_cross_user_denial({"expect": [200, 403]}), (
        "a step that may also succeed asserts nothing about denial")


def test_the_announcement_names_where_the_chain_starts(caplog):
    with caplog.at_level(logging.WARNING):
        normalize_steps([dict(_REGISTER),
                         {"method": "GET", "path": "/api/videos", "expect": [401]}])
    msg = _warned(caplog)[0]
    assert "POST /auth/register" in msg, msg


def test_reporting_only_leaves_the_steps_alone(caplog):
    """No verdict changes: the same steps come back, with no probe appended.

    The chain must satisfy #192a's OTHER preconditions -- an authed POST to a bare
    `/api/<coll>` that saves an id -- or this asserts nothing: a first version used
    `/auth/register` as its only POST, so no probe could ever have been injected and the
    test stayed green against every mutation.
    """
    steps = [dict(_REGISTER),
             {"method": "POST", "path": "/api/videos", "auth": True,
              "body": {"caption": "x"}, "save": {"vid": "id"}, "expect": [200, 201]},
             {"method": "GET", "path": "/api/videos", "expect": [401]}]
    with caplog.at_level(logging.WARNING):
        out, _notes = normalize_steps([dict(s) for s in steps])
    assert not any("framework_isolation_probe" in str(s.get("action", "")) for s in out), (
        "the blocking probe must NOT be injected on a premise measured false")
    assert len(out) == len(steps), out
