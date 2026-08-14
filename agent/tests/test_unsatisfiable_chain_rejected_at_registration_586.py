r"""#586: catch an unsatisfiable chain when it is REGISTERED, not on every run forever.

Measured across the arc: of the 23 broken-step instances in the 8 runs that ultimately DIED on
`business_chain_failing`, **11 were one shape** — a step demanding a non-2xx on a request that
another step in the SAME chain demands succeed. The app cannot do both, so the chain can never
pass, and it also MISTEACHES the lane: chasing the impossible 400 in r132, the backend made the
endpoint require an `X-Profile-Id` header the harness cannot send, taking the failing-chain
count from 1 to 5 in two churn cycles.

Four runtime waivers now exist for this family (#566v, #566z, #570, #580). Every one of them is
a place where the framework decides to ignore a red result, and #580's first draft proved how
easily such a decision can hide a real leak. Rejecting at registration means the verifier is
told while it can still fix the chain, and fewer waivers ever have to fire. The runtime waivers
stay as the net for chains registered by an older framework (#59c).
"""
import pytest

from env_generator.llm_generator.multi_agent.runtime.chain_executor import (
    unsatisfiable_expectation_pairs as pairs,
)


def _s(method, path, expect=None, auth=None, body=None):
    st = {"method": method, "path": path}
    if expect is not None:
        st["expect"] = expect
    if auth:
        st["auth"] = auth
    if body is not None:
        st["body"] = body
    return st


def test_the_r132_r143_shape_is_caught():
    steps = [_s("GET", "/api/continue-watching", [200], auth="tokenA"),
             _s("GET", "/api/continue-watching", [400], auth="tokenA")]
    got = pairs(steps)
    assert got and got[0][:2] == (0, 1), got
    assert "GET /api/continue-watching" in got[0][2]


def test_order_does_not_matter():
    steps = [_s("GET", "/api/x", [400], auth="t"), _s("GET", "/api/x", [200], auth="t")]
    assert pairs(steps), "the deny step coming FIRST is the r135 shape"


def test_a_step_with_no_expect_counts_as_expecting_success():
    """An absent `expect` defaults to success, so it still contradicts a denial twin."""
    assert pairs([_s("GET", "/api/x", None, auth="t"), _s("GET", "/api/x", [403], auth="t")])


def test_a_different_actor_is_a_different_request():
    """THE case this must never flag: a genuine cross-user denial probe."""
    steps = [_s("GET", "/api/my-list", [200], auth="tokenA"),
             _s("GET", "/api/my-list", [403, 404], auth="tokenB")]
    assert pairs(steps) == []


def test_a_foreign_id_query_is_a_different_request():
    steps = [_s("GET", "/api/my-list", [200], auth="t"),
             _s("GET", "/api/my-list?profile_id=999", [403], auth="t")]
    assert pairs(steps) == []


def test_a_different_body_is_a_different_request():
    steps = [_s("POST", "/api/my-list", [201], auth="t", body={"title_id": 1}),
             _s("POST", "/api/my-list", [403], auth="t", body={"profile_id": 9, "title_id": 1})]
    assert pairs(steps) == []


def test_an_unauthenticated_probe_beside_an_authed_call_is_fine():
    steps = [_s("GET", "/api/my-list", [200], auth="t"), _s("GET", "/api/my-list", [401])]
    assert pairs(steps) == []


def test_a_clean_chain_reports_nothing():
    steps = [_s("POST", "/auth/register", [201]), _s("GET", "/api/titles", [200], auth="t"),
             _s("POST", "/api/my-list", [201], auth="t", body={"title_id": 1})]
    assert pairs(steps) == []


def test_a_state_transition_pair_is_NOT_flagged():
    """The false positive the historical replay caught: without a write-between guard the rule
    flagged 17 chains and 14 of them PASS — `DELETE /x/{id}` 204 then 404, `POST /profiles` 201
    then 409. The same request may legitimately answer differently once the state moved."""
    delete_twice = [_s("DELETE", "/api/my-list/${id}", [204], auth="t"),
                    _s("DELETE", "/api/my-list/${id}", [404], auth="t")]
    assert pairs(delete_twice) == []
    create_twice = [_s("POST", "/api/profiles", [201], auth="t", body={"name": "a"}),
                    _s("POST", "/api/profiles", [409], auth="t", body={"name": "a"})]
    assert pairs(create_twice) == []


def test_a_write_BETWEEN_two_reads_clears_the_pair():
    steps = [_s("GET", "/api/my-list", [200], auth="t"),
             _s("POST", "/api/my-list", [201], auth="t", body={"title_id": 1}),
             _s("GET", "/api/my-list", [404], auth="t")]
    assert pairs(steps) == [], "a write in between makes both answers possible"


def test_two_reads_with_nothing_between_are_still_flagged():
    steps = [_s("GET", "/api/continue-watching", [200], auth="t"),
             _s("GET", "/api/titles", [200], auth="t"),          # a read, not a write
             _s("GET", "/api/continue-watching", [400], auth="t")]
    assert pairs(steps), "only a WRITE can justify a different answer"


def test_garbage_never_raises():
    assert pairs(None) == []
    assert pairs([None, "x", 5]) == []


def test_registration_rejects_with_an_actionable_message():
    """The verifier must be told HOW to express what it meant."""
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import registryhub
    src = inspect.getsource(registryhub)
    i = src.index("unsatisfiable_expectation_pairs(norm)")
    window = src[i:i + 1200]
    assert "unsatisfiable expectations" in window
    assert "a different actor" in window and "foreign id" in window
    # #686 made headers real, so the constraint this text must name changed with it: a step
    # CAN set headers now, and what it still cannot do is change actor by supplying one.
    assert "A step CAN set `headers`" in window
    assert "not Authorization" in window and "different token" in window


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
