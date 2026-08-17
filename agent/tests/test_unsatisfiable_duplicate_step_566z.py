r"""#566z (netflix r132, live): the verifier authored the SAME request twice for the SAME actor
with mutually exclusive expectations:

    [5] GET /api/continue-watching  auth=tokenA  expect=[200]   -> 200   passes
    [6] GET /api/continue-watching  auth=tokenA  expect=[400]   -> 200   BROKEN

It meant "with no profile selected -> 400", which a chain step cannot express: steps carry
method/path/body/auth and NO headers. One request cannot be answered two ways.

Left standing it does not merely wedge -- it MISTEACHES the lane. Chasing the 400, the r132
backend made /api/continue-watching REQUIRE an X-Profile-Id header the harness cannot send, so
every legitimate 200-expecting step began failing with "X-Profile-Id header is required" and the
failing-chain count went 1 -> 5 across two churn cycles. That is precisely the "owner-scoping
oscillation" logged against r126-r130 (HANDOFF section 5.1: "400 missing X-Profile-Id header,
then too-permissive, then too-restrictive"): an unsatisfiable authored expectation is its engine.

Fix: waive a no-2xx-expecting step when the SAME actor already got a 2xx for the IDENTICAL
request earlier in the chain. Cannot mask a cross-user leak by construction -- the waiver needs
the actor to be the one already entitled to a 2xx, so no second identity is involved.
"""
import pytest

from env_generator.llm_generator.multi_agent.runtime import chain_executor as ce

_WAIVER = "unsatisfiable-duplicate-expectation-waived"


def _fake_app():
    """Answers 200 to any authed GET on the resource; 401 without a token."""
    state = {"log": []}

    def _fake_http(method, url, *, token=None, body=None, timeout=10, form=False,
                   headers=None):
        path = "/" + url.split("://", 1)[-1].split("/", 1)[-1]
        state["log"].append((method.upper(), path, token))
        if path == "/auth/register":
            return {"status": 201, "body_text": '{"access_token":"tok_%s","user":{"id":1}}'
                    % (len(state["log"])), "error": None}
        if not token:
            return {"status": 401, "body_text": '{"detail":"unauthenticated"}', "error": None}
        if method.upper() == "GET":
            return {"status": 200, "body_text": '{"items":[{"id":9}],"total":1}', "error": None}
        return {"status": 201, "body_text": '{"item":{"id":9}}', "error": None}

    return state, _fake_http


def _chain(*steps, name="c"):
    base = [{"method": "POST", "path": "/auth/register",
             "body": {"email": "a_${rand}@x.io", "password": "pw"},
             "save": {"tokenA": "access_token", "token": "access_token"}},
            {"method": "POST", "path": "/auth/register",
             "body": {"email": "b_${rand}@x.io", "password": "pw"},
             "save": {"tokenB": "access_token"}}]
    return {"name": name, "steps": base + list(steps)}


def _run(monkeypatch, chain):
    _state, fake = _fake_app()
    monkeypatch.setattr(ce, "_http", fake)
    return ce.execute_chain("http://app", chain)


def _waived(result):
    return [s for s in result["steps"] if _WAIVER in (s.get("autofilled") or [])]


def test_r132_repro_contradictory_expectation_same_actor_is_waived(monkeypatch):
    res = _run(monkeypatch, _chain(
        {"method": "GET", "path": "/api/continue-watching", "auth": "tokenA", "expect": [200]},
        {"method": "GET", "path": "/api/continue-watching", "auth": "tokenA", "expect": [400]},
    ))
    assert not res["broken"], res["broken"]
    assert len(_waived(res)) == 1


def test_a_different_actor_keeps_every_tooth(monkeypatch):
    """The isolation probe this must never soften: tokenB reading what tokenA can read."""
    res = _run(monkeypatch, _chain(
        {"method": "GET", "path": "/api/continue-watching", "auth": "tokenA", "expect": [200]},
        {"method": "GET", "path": "/api/continue-watching", "auth": "tokenB",
         "expect": [403, 404]},
    ))
    assert res["broken"], "a cross-actor denial probe must still break on a 2xx"
    assert not _waived(res)


def test_a_different_query_string_keeps_every_tooth(monkeypatch):
    res = _run(monkeypatch, _chain(
        {"method": "GET", "path": "/api/continue-watching", "auth": "tokenA", "expect": [200]},
        {"method": "GET", "path": "/api/continue-watching?profile_id=999", "auth": "tokenA",
         "expect": [403, 404]},
    ))
    assert res["broken"], "a foreign-id probe is a DIFFERENT request — must still break"
    assert not _waived(res)


def test_a_different_body_keeps_every_tooth(monkeypatch):
    res = _run(monkeypatch, _chain(
        {"method": "POST", "path": "/api/continue-watching", "auth": "tokenA",
         "body": {"title_id": 1}, "expect": [200, 201]},
        {"method": "POST", "path": "/api/continue-watching", "auth": "tokenA",
         "body": {"title_id": 2, "profile_id": 999}, "expect": [403]},
    ))
    assert res["broken"]
    assert not _waived(res)


def test_an_unauthenticated_probe_keeps_every_tooth(monkeypatch):
    """auth=None is a different actor — the classic 401 assertion must survive."""
    res = _run(monkeypatch, _chain(
        {"method": "GET", "path": "/api/continue-watching", "auth": "tokenA", "expect": [200]},
        {"method": "GET", "path": "/api/continue-watching", "expect": [401]},
    ))
    # the app really does 401 without a token, so this passes on its merits, unwaived
    assert not _waived(res)


def test_the_waiver_is_order_independent_566z_was_too_narrow(monkeypatch):
    """#570 CORRECTS this case. #566z shipped with the opposite assertion -- "the
    contradictory step FIRST has no earlier success to contradict, so it must break" -- and
    netflix r135 wedged on exactly that: steps [6][7][8] were the SAME request by the SAME
    actor expecting [400], [200], [403]; [8] was waived and [6] was not, purely by position.
    The contradiction is a property of the AUTHORED CHAIN, and the waiver's safety (same
    actor -> no second identity) never depended on order."""
    res = _run(monkeypatch, _chain(
        {"method": "GET", "path": "/api/continue-watching", "auth": "tokenA", "expect": [400]},
        {"method": "GET", "path": "/api/continue-watching", "auth": "tokenA", "expect": [200]},
    ))
    assert not res["broken"], res["broken"]
    assert len(_waived(res)) == 1


def test_r135_replay_all_three_contradictory_positions(monkeypatch):
    """r135 verbatim: [400] then [200] then [403] on one request. Only the 200 stands."""
    res = _run(monkeypatch, _chain(
        {"method": "GET", "path": "/api/continue-watching", "auth": "tokenA", "expect": [400]},
        {"method": "GET", "path": "/api/continue-watching", "auth": "tokenA", "expect": [200]},
        {"method": "GET", "path": "/api/continue-watching", "auth": "tokenA", "expect": [403]},
    ))
    assert not res["broken"], res["broken"]
    assert len(_waived(res)) == 2


def test_no_success_expectation_anywhere_still_breaks(monkeypatch):
    """Nothing in the chain claims this request should succeed → a 2xx on a denial
    expectation is a genuine finding and must survive."""
    res = _run(monkeypatch, _chain(
        {"method": "GET", "path": "/api/continue-watching", "auth": "tokenA", "expect": [400]},
        {"method": "GET", "path": "/api/continue-watching", "auth": "tokenA", "expect": [403]},
    ))
    assert res["broken"], "no step expects this identity to succeed — nothing to contradict"
    assert not _waived(res)


def test_a_step_can_never_waive_itself(monkeypatch):
    """A lone no-2xx step that gets a 2xx is a genuine finding, not a duplicate."""
    res = _run(monkeypatch, _chain(
        {"method": "GET", "path": "/api/continue-watching", "auth": "tokenA", "expect": [403]},
    ))
    assert res["broken"]
    assert not _waived(res)


def test_request_identity_distinguishes_what_it_must():
    step_a = {"auth": "tokenA"}
    step_b = {"auth": "tokenB"}
    base = ce._request_identity(step_a, "GET", "/api/x", None)
    assert base == ce._request_identity(step_a, "get", "/api/x/", None)   # verb + trailing /
    assert base != ce._request_identity(step_b, "GET", "/api/x", None)    # actor
    assert base != ce._request_identity(step_a, "GET", "/api/x?q=1", None)  # query
    assert base != ce._request_identity(step_a, "POST", "/api/x", None)   # verb
    assert base != ce._request_identity(step_a, "GET", "/api/x", {"a": 1})  # body
    # body key order must not matter
    assert (ce._request_identity(step_a, "GET", "/api/x", {"a": 1, "b": 2})
            == ce._request_identity(step_a, "GET", "/api/x", {"b": 2, "a": 1}))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
