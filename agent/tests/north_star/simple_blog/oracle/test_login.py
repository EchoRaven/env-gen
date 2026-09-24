"""Oracle: POST /login — happy path + wrong-password rejection.

Spec:
  - success: 200 with body — reference uses cookie (Set-Cookie httpOnly),
    target uses Bearer (body contains {token: ...})
  - wrong password: 401

Convention-tolerance via _conventions.py:
  - authenticate() handles BOTH the cookie and Bearer conventions:
    pulls a token from common body keys when present, otherwise
    relies on Set-Cookie persisting through the Session.
  - resolve_base handles bare vs /api prefix
"""

import uuid

import requests

from tests.north_star._conventions import (
    assert_created,
    assert_unauthorized,
    authenticate,
    resolve_base,
)


def _fresh_email():
    return f"login-{uuid.uuid4().hex[:12]}@example.com"


def _register(session, base, email, password):
    """Register a user and assert it succeeded — precondition helper."""
    resp = session.post(
        f"{base}/register",
        json={"email": email, "password": password},
        timeout=10,
    )
    assert_created(resp)


def test_registered_user_can_log_in(api_url, app_path):
    base = resolve_base(api_url, app_path)
    email = _fresh_email()
    password = "pw-correct-horse"

    s = requests.Session()
    _register(s, base, email, password)

    # authenticate() asserts the login itself was 200/201/204 and pins
    # Bearer if returned, leaving cookies in the session otherwise.
    authenticate(s, base, email, password)

    # Behavior check: after authenticate(), the session must actually
    # carry credentials in SOME convention. We accept either a Bearer
    # Authorization header (target convention) OR a non-empty cookie
    # jar (reference convention) — but NOT neither. The latter is the
    # "logged in successfully but no credential issued" silent bug.
    has_bearer = "Authorization" in s.headers
    has_cookie = len(s.cookies) > 0
    assert has_bearer or has_cookie, (
        "login returned success but issued no credential "
        "(neither Authorization header nor Set-Cookie)"
    )


def test_wrong_password_is_rejected(api_url, app_path):
    base = resolve_base(api_url, app_path)
    email = _fresh_email()

    # Register with the real password.
    s = requests.Session()
    _register(s, base, email, "pw-correct-horse")

    # Now attempt login with a different password — MUST be rejected
    # with a 401 (or 403 per assert_unauthorized's tolerance).
    resp = requests.post(
        f"{base}/login",
        json={"email": email, "password": "pw-WRONG-horse"},
        timeout=10,
    )
    assert_unauthorized(resp)
