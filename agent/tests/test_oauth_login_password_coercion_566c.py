"""#566c (netflix r114 — M1 wedge, framework-owned): POST /auth/login returned an uncaught 500
(`TypeError: unsupported operand type(s) for +: 'int' and 'str'`) whenever the login/register body
carried a NUMERIC password (JSON number). The framework oauth template coerced email, username and
tenant_id with str(...) but left `password = body.get("password") or ""` un-coerced, so an int
password flowed into verify_user_password/create_user and blew up on `password + salt`. The whole
agent team correctly flagged it framework-owned/unfixable-by-lanes; it blocked business_chain and
drove the run toward the delivery-gate STUCK-ABORT (rc=1, 0 releases).

Distinct from #555 (that was a transient DB-readiness OperationalError → 503). Fix: str-coerce the
password in BOTH the login and register handlers of oauth_routes.py.tmpl, matching the sibling
email/username/tenant_id coercions. Generalizable, no product literals; happy path unchanged.
"""
import ast

from env_generator.llm_generator.multi_agent.runtime.oauth_scaffold import render_oauth_module


def _routes():
    return render_oauth_module("oauth_routes.py")


def test_login_and_register_coerce_password_to_str():
    src = _routes()
    # both handlers (login + register) must str-coerce password, like email/username/tenant_id
    n = src.count('password = str(body.get("password") or "")')
    assert n >= 2, f"expected >=2 str-coerced password assignments, found {n}"


def test_no_uncoerced_password_assignment_remains():
    src = _routes()
    # the exact pre-fix line that let a numeric password reach `int + str` must be gone
    assert 'password = body.get("password") or ""' not in src, \
        "un-coerced password assignment survives — numeric password would 500 (int+str)"


def test_sibling_fields_still_coerced():
    # guard the invariant the fix mirrors: email/username/tenant_id remain str-coerced
    src = _routes()
    assert 'email = str(body.get("email") or "").strip()' in src
    assert 'tenant_id = str(body.get("tenant_id") or "default")' in src


def test_rendered_oauth_routes_is_valid_python():
    ast.parse(_routes())


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
