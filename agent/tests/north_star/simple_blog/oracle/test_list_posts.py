"""Oracle: GET /posts — happy path + empty-body create rejection.

Spec:
  - success: 200 with body {posts: [{id, title, body, author_email}, ...]}
    (envelope can also be {items: []}, {data: []}, or bare [] —
    oracle tolerates via items_of)
  - no auth required for read

Negative covered here: per the spec POST /posts with an empty body
must be rejected (400 or 422). This belongs in the list-flow oracle
because it guards against the "garbage post lands in the listing"
bug — i.e. it's the listing-integrity counterpart to the happy
path's "real post lands in the listing".
"""

import uuid

import requests

from tests.north_star._conventions import (
    _id_of,
    assert_client_error,
    assert_created,
    authenticate,
    items_of,
    resolve_base,
)


def _fresh_email():
    return f"list-{uuid.uuid4().hex[:12]}@example.com"


def test_listing_contains_multiple_created_posts(api_url, app_path):
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

    # Create two posts with unique titles so we can find them.
    ids = []
    for i in range(2):
        title = f"list-title-{i}-{uuid.uuid4().hex[:8]}"
        create = s.post(
            f"{base}/posts",
            json={"title": title, "body": f"list-body-{i}"},
            timeout=10,
        )
        ids.append(assert_created(create))

    # GET /posts is unauthenticated per spec — use a plain client.
    resp = requests.get(f"{base}/posts", timeout=10)
    assert resp.status_code == 200, (
        f"GET /posts expected 200, got {resp.status_code}"
    )
    items = items_of(resp.json())

    # Behavior assertion (strict): BOTH created ids must appear in the
    # listing. Do not loosen to "at least one" — that hides the bug
    # where the second create silently dropped.
    assert items, "GET /posts returned an empty/unrecognized envelope"
    listed_ids = {_id_of(p) for p in items}
    missing = [pid for pid in ids if pid not in listed_ids]
    assert not missing, (
        f"created posts {missing} not in listing "
        f"(listing ids: {sorted(str(x) for x in listed_ids)})"
    )


def test_create_post_with_empty_body_is_rejected(api_url, app_path):
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

    # Empty JSON object — title and body both missing. MUST be
    # rejected with a machine-readable 4xx (spec says 400 or 422).
    resp = s.post(f"{base}/posts", json={}, timeout=10)
    assert_client_error(resp, expect=400)
