"""Oracle: GET /posts/<id> — happy path + 404 for nonexistent.

Spec:
  - success: 200 with body {id, title, body, author_email}
  - nonexistent: 404
  - no auth required for read

Behavior assertion (strict): the returned post's title + body MUST
match what was POSTed. Just-status-200 would pass an app that
returns an empty/wrong body.
"""

import uuid

import requests

from tests.north_star._conventions import (
    _id_of,
    assert_created,
    authenticate,
    resolve_base,
)


def _fresh_email():
    return f"view-{uuid.uuid4().hex[:12]}@example.com"


def _unwrap(body):
    """GET /posts/<id> may return the post bare or under a wrapper
    ({data: ...}, {post: ...}, {item: ...}, {result: ...}) — mirror
    the envelope tolerance _id_of already applies."""
    if not isinstance(body, dict):
        return body
    if any(k in body for k in ("title", "body")):
        return body
    for parent in ("data", "post", "item", "result"):
        sub = body.get(parent)
        if isinstance(sub, dict):
            return sub
    return body


def test_can_view_existing_post_by_id(api_url, app_path):
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

    title = f"view-title-{uuid.uuid4().hex[:8]}"
    body_text = f"view-body-{uuid.uuid4().hex[:8]}"
    create = s.post(
        f"{base}/posts",
        json={"title": title, "body": body_text},
        timeout=10,
    )
    post_id = assert_created(create)

    # Read is unauthenticated per spec — use a plain client to prove it.
    resp = requests.get(f"{base}/posts/{post_id}", timeout=10)
    assert resp.status_code == 200, (
        f"GET /posts/{post_id} expected 200, got {resp.status_code}"
    )
    fetched = _unwrap(resp.json())

    # CRITICAL behavior assertions: title + body must round-trip.
    assert fetched.get("title") == title, (
        f"fetched title mismatch: posted {title!r}, got {fetched.get('title')!r}"
    )
    assert fetched.get("body") == body_text, (
        f"fetched body mismatch: posted {body_text!r}, got {fetched.get('body')!r}"
    )
    # And the id we asked for must be the id we got back.
    assert _id_of(fetched) == post_id, (
        f"fetched id mismatch: asked {post_id!r}, got {_id_of(fetched)!r}"
    )


def test_nonexistent_post_returns_404(api_url, app_path):
    base = resolve_base(api_url, app_path)

    # Id schemes vary by stack (int autoincrement vs uuid). We probe
    # BOTH a huge-int id and a fresh uuid; at least one must be a
    # well-formed-but-nonexistent id for this app, and for THAT id
    # the response MUST be 404 per spec.
    #
    # An id that is malformed for the app's id scheme may legitimately
    # 400/422 instead — we tolerate that as "not the right probe for
    # this app" and rely on the other probe to carry the 404 check.
    # Behavior assertion stays strict: a real not-found case must 404,
    # not 200/2xx (which would silently hide a missing-row bug).
    saw_404 = False
    statuses = {}
    for fake_id in ("999999999", uuid.uuid4().hex):
        resp = requests.get(f"{base}/posts/{fake_id}", timeout=10)
        statuses[fake_id] = resp.status_code
        if resp.status_code == 404:
            saw_404 = True
        else:
            # If the app accepted the id shape (didn't 400/422), then
            # the only correct response for a nonexistent row is 404.
            assert resp.status_code in (400, 422), (
                f"GET /posts/{fake_id} for a nonexistent id expected "
                f"404 (or 400/422 if id shape mismatched), got "
                f"{resp.status_code}"
            )
    assert saw_404, (
        "neither id probe returned 404 for a nonexistent post "
        f"(statuses: {statuses}); 404 is required by the spec for the "
        "matching id shape"
    )
