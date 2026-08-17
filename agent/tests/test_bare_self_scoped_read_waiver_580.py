r"""#580: an AUTHENTICATED read that names no foreign identifier can only ever return the
caller's OWN scope, so demanding it be REJECTED is unsatisfiable by construction.

The recurring shape (r132, r135, r139, r141, r143 — five draws):

    [5] GET /api/continue-watching  auth=tokenA  expect=[400]   -> 200 {"items":[]}
    [6] GET /api/continue-watching  auth=tokenB  expect=[403]   -> 200 {"items":[]}

The verifier means "no profile selected -> reject". The framework's contract does the opposite:
`_fw_owner_val` resolves (and provisions) the caller's own scope, so the read succeeds with the
caller's own — possibly empty — data. #566z/#570 cannot help: no sibling step claims this
request should succeed, so there is nothing to contradict.

Safety comes from the REQUEST, not a heuristic: a GET with an auth ref, no query string, no id
segment and no body addresses exactly one scope. Any carrier of a foreign id present -> no
waiver.
"""
import pytest

from env_generator.llm_generator.multi_agent.runtime import chain_executor as ce

_B = ce._is_bare_self_scoped_read


def _step(auth="tokenA"):
    return {"auth": auth} if auth else {}


def test_r143_bare_authenticated_collection_read_is_self_scoped():
    assert _B(_step(), "GET", "/api/continue-watching", None) is True
    assert _B(_step(), "get", "/api/my-list", None) is True


def test_a_query_string_can_carry_a_foreign_id_so_no_waiver():
    assert _B(_step(), "GET", "/api/my-list?profile_id=10", None) is False
    assert _B(_step(), "GET", "/api/continue-watching?profile_id=${x}", None) is False


def test_an_id_segment_means_a_specific_resource_so_no_waiver():
    assert _B(_step(), "GET", "/api/my-list/10", None) is False
    assert _B(_step(), "GET", "/api/titles/${titleId}", None) is False
    assert _B(_step(), "GET", "/api/users/9f8e7d6c5b4a3210/posts", None) is False


def test_an_unauthenticated_read_keeps_its_401_probe():
    assert _B(_step(auth=None), "GET", "/api/my-list", None) is False


def test_writes_are_never_waived():
    for verb in ("POST", "PUT", "PATCH", "DELETE"):
        assert _B(_step(), verb, "/api/my-list", None) is False


def test_a_body_bearing_read_is_not_bare():
    assert _B(_step(), "GET", "/api/my-list", {"profile_id": 10}) is False


def test_a_nested_child_collection_with_no_id_is_still_self_scoped():
    assert _B(_step(), "GET", "/api/me/my-list", None) is True


def test_the_waiver_fires_end_to_end_and_is_recorded(monkeypatch):
    state = {"log": []}

    def fake(method, url, *, token=None, body=None, timeout=10, form=False, headers=None):
        path = "/" + url.split("://", 1)[-1].split("/", 1)[-1]
        state["log"].append(path)
        if path == "/auth/register":
            return {"status": 201, "body_text": '{"access_token":"t","user":{"id":1}}',
                    "error": None}
        return {"status": 200, "body_text": '{"items":[],"total":0}', "error": None}

    monkeypatch.setattr(ce, "_http", fake)
    chain = {"name": "cw_scope", "steps": [
        {"method": "POST", "path": "/auth/register", "body": {"email": "a_${rand}@x.io"},
         "save": {"tokenA": "access_token", "token": "access_token"}},
        {"method": "GET", "path": "/api/continue-watching", "auth": "tokenA",
         "expect": [400]},
    ]}
    res = ce.execute_chain("http://app", chain)
    assert not res["broken"], res["broken"]
    assert any("bare-self-scoped-empty-read-waived" in (s.get("autofilled") or [])
               for s in res["steps"]), res["steps"]


def test_a_bare_read_that_RETURNS_ROWS_still_breaks(monkeypatch):
    """THE safety case, and the one this fix nearly got wrong. The request shape proves no
    foreign id was NAMED; it cannot prove none was RETURNED. An unscoped collection read hands
    every actor the same rows — exactly how the r131/r133 leaks were caught (`GET /api/my-list`
    as tokenB returned user A's row). Rows present -> keep the leak verdict."""
    def fake(method, url, *, token=None, body=None, timeout=10, form=False, headers=None):
        path = "/" + url.split("://", 1)[-1].split("/", 1)[-1]
        if path == "/auth/register":
            return {"status": 201, "body_text": '{"access_token":"t","user":{"id":1}}',
                    "error": None}
        return {"status": 200, "body_text": '{"items":[{"id":2}],"total":1}', "error": None}

    monkeypatch.setattr(ce, "_http", fake)
    chain = {"name": "r133_leak", "steps": [
        {"method": "POST", "path": "/auth/register", "body": {"email": "b_${rand}@x.io"},
         "save": {"tokenB": "access_token", "token": "access_token"}},
        {"method": "GET", "path": "/api/my-list", "auth": "tokenB", "expect": [403, 404]},
    ]}
    res = ce.execute_chain("http://app", chain)
    assert res["broken"], "a bare read returning another owner's rows must still fail"
    assert not any("waived" in str(a) for s in res["steps"]
                   for a in (s.get("autofilled") or [])), res["steps"]


def test_a_foreign_id_probe_still_breaks_end_to_end(monkeypatch):
    """The one thing this must never soften."""
    def fake(method, url, *, token=None, body=None, timeout=10, form=False, headers=None):
        path = "/" + url.split("://", 1)[-1].split("/", 1)[-1]
        if path == "/auth/register":
            return {"status": 201, "body_text": '{"access_token":"t","user":{"id":1}}',
                    "error": None}
        return {"status": 200, "body_text": '{"items":[{"id":1}],"total":1}', "error": None}

    monkeypatch.setattr(ce, "_http", fake)
    chain = {"name": "leak", "steps": [
        {"method": "POST", "path": "/auth/register", "body": {"email": "a_${rand}@x.io"},
         "save": {"tokenA": "access_token", "token": "access_token"}},
        {"method": "GET", "path": "/api/my-list?profile_id=999", "auth": "tokenA",
         "expect": [403, 404]},
    ]}
    res = ce.execute_chain("http://app", chain)
    assert res["broken"], "a foreign-id probe returning rows must still fail"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
