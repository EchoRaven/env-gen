"""Oracle: POST /register — happy path + duplicate-email rejection.

Spec:
  - success: 201 with body {id, email}
  - duplicate email: 400 or 422 with JSON error

Convention-tolerance via _conventions.py:
  - resolve_base handles bare vs /api prefix
  - assert_created accepts 200 or 201 and tolerates wrapper envelopes
  - assert_client_error accepts 400 or 422 and insists on JSON body
"""

import uuid

import requests

from tests.north_star._conventions import (
    assert_client_error,
    assert_created,
    resolve_base,
)


def _fresh_email():
    """Unique email per test run — guards against state leakage if the
    runner ever reuses a backing store between tests."""
    return f"reg-{uuid.uuid4().hex[:12]}@example.com"


def test_new_user_can_register(api_url, app_path):
    base = resolve_base(api_url, app_path)
    email = _fresh_email()

    resp = requests.post(
        f"{base}/register",
        json={"email": email, "password": "pw-correct-horse"},
        timeout=10,
    )

    # assert_created enforces 200/201 + presence of an id field
    # (envelope-tolerant). Behavior assertion: a real id must come back.
    new_id = assert_created(resp)
    assert new_id is not None


def test_duplicate_email_is_rejected(api_url, app_path):
    base = resolve_base(api_url, app_path)
    email = _fresh_email()
    payload = {"email": email, "password": "pw-correct-horse"}

    # First registration must succeed — this is the precondition for
    # the negative assertion below; if this fails the test is invalid,
    # not a duplicate-rejection bug.
    first = requests.post(f"{base}/register", json=payload, timeout=10)
    assert_created(first)

    # Second registration with the same email MUST be rejected with a
    # machine-readable 4xx (spec says 400 or 422).
    second = requests.post(f"{base}/register", json=payload, timeout=10)
    assert_client_error(second, expect=400)
