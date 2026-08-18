r"""#927: a BUILT route that 404s was filed as an unbuilt endpoint, so the chain read `passing`.

`execute_chain` softens a 404/405 to ``kind="missing"`` so a not-yet-implemented endpoint does
not fail the whole chain. It decided "built or not" from the response detail:

    _built_404 = isinstance(_d, str) and _d.strip().lower() not in ("not found", "")

and its own comment says why that should work — Starlette answers an unmatched path with exactly
``{"detail":"Not Found"}``, so anything else is a route that exists and rejected the request.
The ``.lower()`` erases the only signal the comment relies on.

Measured over the corpus — 365 soft steps sitting inside PASSING chains, 94 runs:

    "Not Found"           194  53%   Starlette's real default, correctly soft
    ★ "not found"         129  35%   a handler's own detail — folded onto the default by .lower()
    "Method Not Allowed"   34   9%   405 is never detail-checked at all
    other                   8

r153, released, is one of them: `my_list_per_profile_lifecycle` holds
``DELETE /api/my-list/1 -> 404 {"detail":"not found"}`` with ``kind="missing"``, and the handler
that wrote it is `main.py:1324`, three lines under ``@app.delete("/api/my-list/{title_id}")``.

Two controls before believing the 129:
  * a live probe of an unregistered path on r154 answered ``{"detail":"Not Found"}`` — title case;
  * 33 runs emit BOTH spellings, so no app-wide handler is rewriting the detail. The two
    spellings come from different places and the case was the only thing separating them.

★ The fix does not sharpen the string test — it stops guessing. FastAPI publishes the route table
at ``/openapi.json``; ask it. That also fixes what a source scan would get wrong: r154 declares
``@router.delete("/api/v1/tenants/{tenant_id}")`` in `custom_routes.py` and its live openapi has
no such path (the router is not mounted), so grepping the backend would have hard-failed a chain
on an endpoint the app genuinely does not serve.
"""
import json

import pytest

from env_generator.llm_generator.multi_agent.runtime import chain_executor as ce


_OPENAPI = json.dumps({"paths": {
    "/api/my-list": {"get": {}, "post": {}},
    "/api/my-list/{item_id}": {"delete": {}},
    "/api/titles/{title_id}/episodes": {"get": {}},
}})


@pytest.fixture(autouse=True)
def _clear_cache(monkeypatch):
    """★ The seam this fix introduces: a module-level cache keyed by base. Without this every
    test after the first would read the first one's table."""
    ce._ROUTE_TABLE_927.clear()
    monkeypatch.delenv("ENVGEN_CHAIN_ROUTE_TABLE", raising=False)
    yield
    ce._ROUTE_TABLE_927.clear()


def _serve(openapi=_OPENAPI, *, status=200, calls=None):
    def fake(method, url, *, token=None, body=None, timeout=10, form=False, headers=None):
        if url.endswith("/openapi.json"):
            if calls is not None:
                calls.append(url)
            return {"status": status, "body_text": openapi, "error": None}
        return {"status": 404, "body_text": '{"detail":"Not Found"}', "error": None}
    return fake


# --------------------------------------------------------------------------- the route table

def test_it_reads_the_apps_own_route_table(monkeypatch):
    monkeypatch.setattr(ce, "_http", _serve())
    assert ce._route_is_declared_927("http://app", "DELETE", "/api/my-list/1") is True


def test_a_path_without_the_verb_is_not_declared(monkeypatch):
    """★ The soft case this branch exists for: the app serves the path, never wrote the verb."""
    monkeypatch.setattr(ce, "_http", _serve())
    assert ce._route_is_declared_927("http://app", "DELETE", "/api/my-list") is False


def test_an_unknown_path_is_not_declared(monkeypatch):
    monkeypatch.setattr(ce, "_http", _serve())
    assert ce._route_is_declared_927("http://app", "GET", "/api/nope") is False


def test_a_template_matches_one_segment_only(monkeypatch):
    monkeypatch.setattr(ce, "_http", _serve())
    assert ce._route_is_declared_927("http://app", "DELETE", "/api/my-list/1") is True
    assert ce._route_is_declared_927("http://app", "DELETE", "/api/my-list/1/extra") is False


def test_a_multi_segment_template_matches(monkeypatch):
    monkeypatch.setattr(ce, "_http", _serve())
    assert ce._route_is_declared_927("http://app", "GET", "/api/titles/42/episodes") is True


def test_query_and_fragment_are_stripped_before_matching(monkeypatch):
    monkeypatch.setattr(ce, "_http", _serve())
    assert ce._route_is_declared_927("http://app", "GET", "/api/my-list?profile_id=3") is True


def test_the_table_is_fetched_once_per_base(monkeypatch):
    calls = []
    monkeypatch.setattr(ce, "_http", _serve(calls=calls))
    for _ in range(4):
        ce._route_is_declared_927("http://app", "GET", "/api/my-list")
    assert len(calls) == 1, calls


def test_no_table_is_None_not_False(monkeypatch):
    """★ 'empty container is not a fact': an unreachable openapi must not read as 'no routes',
    which would make every 404 a BUILT route and fail every chain."""
    monkeypatch.setattr(ce, "_http", _serve(status=500))
    assert ce._route_is_declared_927("http://app", "GET", "/api/my-list") is None


def test_garbage_openapi_is_None(monkeypatch):
    monkeypatch.setattr(ce, "_http", _serve(openapi="<html>nope</html>"))
    assert ce._route_is_declared_927("http://app", "GET", "/api/my-list") is None


def test_an_empty_paths_object_is_None(monkeypatch):
    """An app that serves openapi with zero paths is a broken read, not an app with no routes."""
    monkeypatch.setattr(ce, "_http", _serve(openapi='{"paths":{}}'))
    assert ce._route_is_declared_927("http://app", "GET", "/api/my-list") is None


def test_a_raising_http_client_is_None(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("network")
    monkeypatch.setattr(ce, "_http", boom)
    assert ce._route_is_declared_927("http://app", "GET", "/api/my-list") is None


# --------------------------------------------------------------------------- end to end

def _chain_hitting(method, path, expect=(200, 204)):
    return {"name": "c927", "steps": [
        {"method": "POST", "path": "/auth/register", "body": {"email": "a_${rand}@x.io"},
         "expect": [200, 201, 409], "save": {"token": "access_token"}},
        {"method": method, "path": path, "auth": "token", "expect": list(expect)},
    ]}


def _run(monkeypatch, *, detail, openapi=_OPENAPI, status=404,
         method="DELETE", path="/api/my-list/1"):
    def fake(m, url, *, token=None, body=None, timeout=10, form=False, headers=None):
        if url.endswith("/openapi.json"):
            return ({"status": 200, "body_text": openapi, "error": None} if openapi
                    else {"status": 503, "body_text": "", "error": None})
        if url.endswith("/auth/register"):
            return {"status": 201, "body_text": '{"access_token":"t","user":{"id":1}}',
                    "error": None}
        return {"status": status, "body_text": json.dumps({"detail": detail}), "error": None}
    monkeypatch.setattr(ce, "_http", fake)
    return ce.execute_chain("http://app", _chain_hitting(method, path))


def _kinds(res):
    return [s.get("kind") for s in res["steps"]]


def test_a_declared_route_that_404s_breaks_the_chain(monkeypatch):
    """★ r153's actual step, replayed: DELETE /api/my-list/1 -> 404 {"detail":"not found"}."""
    res = _run(monkeypatch, detail="not found")
    assert "broken" in _kinds(res), _kinds(res)
    assert res["broken"], "a built route answering 404 must fail its chain"


def test_the_same_404_on_an_UNDECLARED_route_stays_soft(monkeypatch):
    """The behaviour the branch exists for — an endpoint nobody built yet must not fail a chain."""
    res = _run(monkeypatch, detail="not found", path="/api/never-built/1")
    assert "missing" in _kinds(res), _kinds(res)
    assert not res["broken"], res["broken"]


def test_a_declared_route_405_breaks_too(monkeypatch):
    """405 was never detail-checked at all (34 in the corpus). The route table answers it."""
    res = _run(monkeypatch, detail="Method Not Allowed", status=405)
    assert "broken" in _kinds(res), _kinds(res)


def test_starlettes_own_default_on_a_declared_route_still_breaks(monkeypatch):
    """★ The case no string test can reach: the app IS serving the route and returned the exact
    default detail. Only the route table gets this right."""
    res = _run(monkeypatch, detail="Not Found")
    assert "broken" in _kinds(res), _kinds(res)


# --------------------------------------------------------------------------- the fallback

def test_without_a_route_table_lowercase_still_breaks(monkeypatch):
    """The `.lower()` removal, on its own: no openapi, handler-authored detail -> broken."""
    res = _run(monkeypatch, detail="not found", openapi="")
    assert "broken" in _kinds(res), _kinds(res)


def test_without_a_route_table_starlettes_default_stays_soft(monkeypatch):
    res = _run(monkeypatch, detail="Not Found", openapi="")
    assert "missing" in _kinds(res), _kinds(res)
    assert not res["broken"], res["broken"]


def test_the_kill_switch_restores_the_string_path(monkeypatch):
    monkeypatch.setenv("ENVGEN_CHAIN_ROUTE_TABLE", "0")
    res = _run(monkeypatch, detail="Not Found")
    assert "missing" in _kinds(res), "off, a declared route with the default detail is soft again"


def test_the_kill_switch_reads_the_usual_spellings(monkeypatch):
    for v in ("0", "false", "no", "off", "OFF"):
        monkeypatch.setenv("ENVGEN_CHAIN_ROUTE_TABLE", v)
        assert ce._env_off_927() is True, v
    for v in ("1", "true", "yes", "", "anything"):
        monkeypatch.setenv("ENVGEN_CHAIN_ROUTE_TABLE", v)
        assert ce._env_off_927() is False, v


def test_unset_means_on(monkeypatch):
    monkeypatch.delenv("ENVGEN_CHAIN_ROUTE_TABLE", raising=False)
    assert ce._env_off_927() is False


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
