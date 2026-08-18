r"""#952: "not built yet" and "built but unreachable" are different instructions.

Found by running r154's own `tenant_admin_lifecycle` against r154's own live app — not a fixture.
The chain calls `DELETE /api/v1/tenants/{id}`; `custom_routes.py:138` declares exactly that
handler; the served openapi has no such path. #927 files the step `missing` (correct — the app
really does not serve it) and the chain survives (also correct). Nobody says the third thing:
**a lane wrote a handler that cannot be reached, and a verifier wrote a chain that exercises it.**

r154: 46 declared routes, 39 served, exactly one orphan — and that one is why a chain reported
passing over a 404.

★ Source-vs-LIVE, never source alone. #936 records what a source-only scan gets wrong (it would
have hard-failed a chain on an endpoint the app genuinely does not serve); this is the same
comparison run the other way round, and only the pair is safe.
"""
import pytest

from env_generator.llm_generator.multi_agent.runtime.chain_executor import (
    _declared_but_unmounted_952 as detect,
)


def _app(tmp_path, files):
    d = tmp_path / "app" / "backend"
    d.mkdir(parents=True)
    for name, body in files.items():
        (d / name).write_text(body, encoding="utf-8")
    return tmp_path


_ROUTES = '''
@router.delete("/api/v1/tenants/{tenant_id}")
def drop(): ...
@app.get("/api/titles")
def titles(): ...
'''


def test_a_declared_route_that_missed_is_reported(tmp_path):
    p = _app(tmp_path, {"custom_routes.py": _ROUTES})
    out = detect(p, [{"method": "DELETE", "path": "/api/v1/tenants/t0", "kind": "missing"}], "u")
    assert len(out) == 1
    assert out[0]["declared_in"] == "custom_routes.py"
    assert out[0]["declared_as"] == "/api/v1/tenants/{tenant_id}"


def test_a_genuinely_unwritten_route_is_not_reported(tmp_path):
    """★ The soft case #768 protects must stay quiet, or this becomes noise on every round."""
    p = _app(tmp_path, {"custom_routes.py": _ROUTES})
    assert detect(p, [{"method": "GET", "path": "/api/never", "kind": "missing"}], "u") == []


def test_the_verb_must_match(tmp_path):
    """A declared GET does not make a missing DELETE 'unmounted'."""
    p = _app(tmp_path, {"r.py": '@app.get("/api/titles/{id}")\ndef t(): ...\n'})
    assert detect(p, [{"method": "DELETE", "path": "/api/titles/1", "kind": "missing"}], "u") == []


def test_an_include_router_prefix_is_honoured(tmp_path):
    p = _app(tmp_path, {"r.py": '@router.get("/items")\ndef i(): ...\n',
                        "main.py": 'app.include_router(r, prefix="/api/v2")\n'})
    out = detect(p, [{"method": "GET", "path": "/api/v2/items", "kind": "missing"}], "u")
    assert len(out) == 1 and out[0]["declared_as"] == "/api/v2/items"


def test_no_app_dir_is_silent(tmp_path):
    assert detect(tmp_path, [{"method": "GET", "path": "/x", "kind": "missing"}], "u") == []


def test_no_missing_steps_is_silent(tmp_path):
    assert detect(_app(tmp_path, {"r.py": _ROUTES}), [], "u") == []


def test_it_never_raises(tmp_path):
    assert detect(None, None, "u") == []
    assert detect(tmp_path, [{"method": None, "path": None}], "u") == []


def test_run_chains_returns_it_as_data():
    """#947's rule: a finding that only exists in a log line is not a finding."""
    import ast
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import chain_executor as ce
    fn = [n for n in ast.walk(ast.parse(inspect.getsource(ce)))
          if isinstance(n, ast.FunctionDef) and n.name == "run_chains"][0]
    rets = [n for n in ast.walk(fn) if isinstance(n, ast.Return) and isinstance(n.value, ast.Dict)]
    assert rets and any(
        isinstance(k, ast.Constant) and k.value == "declared_but_unmounted_952"
        for r in rets for k in r.value.keys)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
