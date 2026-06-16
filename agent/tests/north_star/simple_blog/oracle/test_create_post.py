"""Oracle: POST /posts (auth required) — happy path + unauthenticated reject.

Spec:
  - success: 201 with body {id, title, body, author_email}
  - unauthenticated: 401

Behavior assertion (strict): the created post MUST actually be
visible in GET /posts. This is the central anti-tolerance check —
without it an app could 201 every create and never persist anything
and the oracle would pass.
"""

import uuid

import requests

from tests.north_star._conventions import (
    _id_of,
    assert_created,
    assert_unauthorized,
    authenticate,
    items_of,
    resolve_base,
)


def _fresh_email():
    return f"create-{uuid.uuid4().hex[:12]}@example.com"


def test_authenticated_user_can_create_post_and_see_in_list(api_url, app_path):
    base = resolve_base(api_url, app_path)
    email = _fresh_email()
    password = "pw-correct-horse"

    s = requests.Session()
    reg = s.post(
        f"{base}/register",
        json={"email": email, "password": password},
        timeout=10,
    )
    assert_created(reg)
    authenticate(s, base, email, password)

    # Unique title so we can find this exact post in a shared listing.
    title = f"hello-{uuid.uuid4().hex[:8]}"
    body_text = "world body text"

    create = s.post(
        f"{base}/posts",
        json={"title": title, "body": body_text},
        timeout=10,
    )
    post_id = assert_created(create)

    # CRITICAL behavior assertion: the created post must really appear
    # in GET /posts (envelope-tolerant via items_of). DO NOT loosen.
    listing = s.get(f"{base}/posts", timeout=10).json()
    items = items_of(listing)
    assert items, "GET /posts returned an empty/unrecognized envelope after create"
    assert any(_id_of(p) == post_id for p in items), (
        f"created post {post_id} not visible in GET /posts listing "
        f"(found ids: {[_id_of(p) for p in items]})"
    )


def test_unauthenticated_post_creation_is_rejected(api_url, app_path):
    base = resolve_base(api_url, app_path)

    # Plain requests.post — no Session with credentials. MUST be
    # rejected with 401 (or 403 per assert_unauthorized's tolerance).
    resp = requests.post(
        f"{base}/posts",
        json={"title": "should-not-land", "body": "no auth provided"},
        timeout=10,
    )
    assert_unauthorized(resp)
