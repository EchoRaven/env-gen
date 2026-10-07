"""#1203gd -- the auth dependency blamed the caller's token for the server's own failures.

The framework-owned `get_current_user` ended like this:

    sub = claims.get("sub")
    if sub is None:
        raise HTTPException(status_code=401, detail="invalid token subject")
    try:
        row = db.execute(text("SELECT * FROM users WHERE id = :id"),
                         {"id": int(sub)}).mappings().first()
    except Exception:
        row = None
    if not row:
        raise HTTPException(status_code=401, detail="unknown user")

Three unrelated causes arrived at one answer:
  * a non-numeric `sub` -- `int(sub)` raises; that is the TOKEN
  * no matching row    -- genuinely an unknown USER
  * any database failure -- a pool exhausted, a `users` table a lane renamed, a dropped
    connection; that is OURS, and it is the one that does damage

`401 "unknown user"` appears 495 times across 46 corpus runs. How many were infrastructure is
not recoverable, because the exception that would have said so was replaced by `row = None`
before anything could log it -- which is the second half of the defect and why the measurement
cannot be sharpened after the fact.

Why the third case does damage: the framework's own `bc_auth.js` guard removes the stored token
and navigates to /login on ANY /api/ 401 that carried a token. So a transient DB fault did not
degrade one request -- it signed the user out. r164, the first run ever to deliver two
milestones, has its test-user reporting authenticated bounces to /login on four separate pages.

`"auth unavailable"` (the signing key did not load) was the same category error, stated outright:
the key is ours, not the caller's. It is rare but real -- twice in the corpus, under a comment
that read `pragma: no cover - AS modules must be present in a real env`.

The rule this restores: **401 means the caller's credential is the problem; 5xx means ours is.**
It is also the standing no-masking-fallback rule -- `except Exception: row = None` is exactly a
fallback that turns our failure into someone else's fault.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest
from fastapi import Depends, Header, HTTPException
from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "env_generator" / "llm_generator")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime import backend_scaffold as BS  # noqa: E402

SCAFFOLD_SRC = Path(BS.__file__).read_text(encoding="utf-8")


def _template(name: str) -> str:
    for node in ast.walk(ast.parse(SCAFFOLD_SRC)):
        if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
                and getattr(node.targets[0], "id", None) == name):
            return node.value.value
    raise AssertionError("template %s is gone from backend_scaffold.py" % name)


def _compile_from_template(template: str, want: str, ns: dict):
    """Pull one definition out of a projected template and make it callable.

    The template imports `database`, `jwt_manager` and friends, which only exist inside a
    generated app -- so take the definition, not the module, and hand it the world it needs.
    This is the SHIPPED text: a change to the template is a change to what runs here.
    """
    tree = ast.parse(template)
    node = next((n for n in tree.body
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                 and n.name == want), None)
    assert node is not None, "%s is no longer defined in the template" % want
    exec(compile(ast.Module(body=[node], type_ignores=[]), "<%s>" % want, "exec"), ns)
    return ns[want]


class _FakeJwt:
    """Stands in for the `jwt` module: only `decode` is reached."""
    def __init__(self, claims=None, exc=None):
        self._claims, self._exc = claims, exc

    def decode(self, *a, **k):
        if self._exc:
            raise self._exc
        return self._claims


class _FakeDb:
    def __init__(self, row=None, exc=None):
        self._row, self._exc = row, exc

    def execute(self, *a, **k):
        if self._exc:
            raise self._exc
        _row = self._row

        class _R:
            def mappings(self_inner):
                class _M:
                    def first(self_m):
                        return _row
                return _M()
        return _R()


def _get_current_user(*, pem=b"KEY", claims=None, decode_exc=None, row=None, db_exc=None):
    tmpl = _template("_AUTH_DEPENDENCY_PY")
    ns = {
        "HTTPException": HTTPException, "Header": Header, "Depends": Depends,
        "text": text, "_pyjwt": _FakeJwt(claims, decode_exc),
        "_PUBLIC_PEM": pem, "ALGORITHM": "RS256", "Session": object,
        # `Depends(get_db)` is a DEFAULT argument, so the name must exist at def time even
        # though every call below passes `db=` explicitly.
        "get_db": lambda: None,
    }
    _compile_from_template(tmpl, "_AuthUser", ns)
    fn = _compile_from_template(tmpl, "get_current_user", ns)
    return lambda auth="Bearer t": fn(authorization=auth, db=_FakeDb(row, db_exc))


# --- the caller's fault: 401 ------------------------------------------------------------------

def test_no_bearer_header_is_401():
    with pytest.raises(HTTPException) as e:
        _get_current_user()(auth=None)
    assert e.value.status_code == 401 and "missing bearer token" in e.value.detail


def test_an_undecodable_token_is_401():
    with pytest.raises(HTTPException) as e:
        _get_current_user(decode_exc=ValueError("bad signature"))()
    assert e.value.status_code == 401 and e.value.detail == "invalid token"


def test_a_token_with_no_subject_is_401():
    with pytest.raises(HTTPException) as e:
        _get_current_user(claims={})()
    assert e.value.status_code == 401 and e.value.detail == "invalid token subject"


def test_a_non_numeric_subject_blames_the_token_not_the_user():
    """#1203gd: `int("alice")` used to be swallowed and reported as "unknown user" -- which
    sent whoever read it looking in the users table for a row that was never the question."""
    with pytest.raises(HTTPException) as e:
        _get_current_user(claims={"sub": "alice"})()
    assert e.value.status_code == 401
    assert e.value.detail == "invalid token subject", e.value.detail


def test_a_genuinely_absent_row_is_still_unknown_user():
    with pytest.raises(HTTPException) as e:
        _get_current_user(claims={"sub": 7}, row=None)()
    assert e.value.status_code == 401 and e.value.detail == "unknown user"


# --- our fault: 5xx --------------------------------------------------------------------------

@pytest.mark.parametrize("exc", [
    RuntimeError("QueuePool limit of size 5 overflow 10 reached"),
    KeyError("users"),
    OSError("server closed the connection unexpectedly"),
])
def test_a_database_failure_is_503_and_names_itself(exc):
    """THE HARM. Before: 401 "unknown user" -> the frontend guard deletes the stored token ->
    the user is signed out by a database hiccup, and the exception is gone."""
    with pytest.raises(HTTPException) as e:
        _get_current_user(claims={"sub": 7}, db_exc=exc)()
    assert e.value.status_code == 503, e.value.status_code
    assert type(exc).__name__ in e.value.detail, e.value.detail
    assert str(exc).split()[0] in e.value.detail, e.value.detail


def test_a_missing_signing_key_is_503_not_401():
    with pytest.raises(HTTPException) as e:
        _get_current_user(pem=None)()
    assert e.value.status_code == 503
    assert "auth unavailable" in e.value.detail


# --- the happy path still works --------------------------------------------------------------

def test_a_valid_token_returns_the_user_both_ways():
    user = _get_current_user(claims={"sub": "7"}, row={"id": 7, "username": "ana"})()
    assert user["id"] == 7 and user.username == "ana"


# --- the subject-only helper carries the same split ------------------------------------------

def test_the_subject_helper_also_503s_on_a_missing_key():
    tmpl = _template("_JWT_SUB_HELPER")
    name = next(n.name for n in ast.parse(tmpl).body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)))
    ns = {"HTTPException": HTTPException}
    fn = _compile_from_template(tmpl, name, ns)
    import builtins
    real_import = builtins.__import__

    def _imp(n, *a, **k):
        if n == "jwt_manager":        # only the AS module; `import jwt` is unconditional
            raise ImportError(n)
        return real_import(n, *a, **k)
    builtins.__import__ = _imp
    try:
        with pytest.raises(HTTPException) as e:
            fn("whatever")
    finally:
        builtins.__import__ = real_import
    assert e.value.status_code == 503, e.value.status_code


# --- the pairing that makes the split matter -------------------------------------------------

def test_the_frontend_guard_only_destroys_a_session_on_a_401():
    """The whole point of answering 503: `bc_auth.js` removes the stored token and navigates
    on a 401 that carried auth. If either call site widened to any error status, a 503 would
    sign the user out again and this fix would be undone from the other side."""
    from multi_agent.runtime import frontend_scaffold as FS
    src = Path(FS.__file__).read_text(encoding="utf-8")
    guard = next(n.value.value for n in ast.walk(ast.parse(src))
                 if isinstance(n, ast.Assign) and isinstance(n.value, ast.Constant)
                 and isinstance(n.value.value, str) and "_bcOn401" in n.value.value)
    calls = [ln.strip() for ln in guard.splitlines()
             if "_bcOn401(" in ln and not ln.strip().startswith("function _bcOn401")]
    assert len(calls) >= 2, (
        "expected both call sites (fetch and XMLHttpRequest), found %d: %s" % (len(calls), calls))
    # #1203gd: `assert "401" in ln` was the first version and it could not fail -- the HELPER
    # IS CALLED `_bcOn401`, so the substring is in every line that calls it. Widening the fetch
    # site to `status >= 400` left that assertion green. Match the comparison, not the name.
    guard_re = re.compile(r"status\s*===\s*401\b")
    for ln in calls:
        assert guard_re.search(ln), "a _bcOn401 call not keyed on `status === 401`: %s" % ln
    assert "removeItem('access_token')" in guard or 'removeItem("access_token")' in guard


# --- the shape that caused it must not come back ---------------------------------------------

def test_no_handler_in_the_template_turns_a_failure_into_an_empty_result():
    """The defect's shape: `except Exception:` whose body only assigns a falsy sentinel that a
    later `if not <sentinel>` converts into a verdict about the caller."""
    tree = ast.parse(_template("_AUTH_DEPENDENCY_PY"))
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        for h in node.handlers:
            body = [st for st in h.body if not isinstance(st, ast.Pass)]
            if len(body) != 1 or not isinstance(body[0], ast.Assign):
                continue
            val = body[0].value
            if isinstance(val, ast.Constant) and not val.value:
                offenders.append("line %d: %s" % (h.lineno, ast.unparse(body[0])))
    assert not offenders, (
        "a swallowed exception becomes a falsy value here, and whatever reads it next will "
        "report our failure as the caller's:\n  " + "\n  ".join(offenders))
