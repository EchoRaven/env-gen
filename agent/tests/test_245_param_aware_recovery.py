"""#245 — param-aware chain recovery (the top recurring business_chain killer).

Across r27/r29/r33 EVERY broken business_chain step was the same shape:
``GET /api/users/<X>`` where the contract declares ``/api/users/{username}`` but the
chain authored a literal id or an invented name:

  r27  /api/users/ProfileUser -> 404   (invented name)
  r29  /api/users/13,18,20,21,23 -> 500 (numeric id into a string-typed param)
  r33  /api/users/1,17,23,32,33,39,50,61 -> 404

The #136/#144 ladder only recovers NUMERIC ids and only on 404, so none of these were
reachable. #245 matches the literal against the REGISTERED template, reads the param
NAME, and recovers a real value of that FIELD from the collection.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from env_generator.llm_generator.multi_agent.runtime.chain_executor import (  # noqa: E402
    _ID_PARAM_RE,
    _registered_param_for_path,
    _rows_of_payload,
)

EPS = [
    {"path": "/api/users/{username}"},
    {"path": "/api/users/suggested"},
    {"path": "/api/users/{username}/videos"},
    {"path": "/api/videos/{id}"},
    {"path": "/api/videos/feed"},
]


# ---- template matching ----

def test_real_r29_r33_numeric_literal_maps_to_username_param():
    for lit in ("/api/users/13", "/api/users/61", "/api/users/1"):
        coll, name, idx = _registered_param_for_path(lit, EPS)
        assert (coll, name, idx) == ("/api/users", "username", 2), lit
        assert not _ID_PARAM_RE.search(name)   # → param-aware recovery, not the id ladder


def test_real_r27_invented_name_maps_to_username_param():
    coll, name, idx = _registered_param_for_path("/api/users/ProfileUser", EPS)
    assert (coll, name, idx) == ("/api/users", "username", 2)


def test_id_shaped_param_left_to_the_existing_id_ladder():
    coll, name, idx = _registered_param_for_path("/api/videos/299", EPS)
    assert name == "id" and _ID_PARAM_RE.search(name)


def test_registered_static_endpoint_never_treated_as_param():
    # /api/users/suggested and /api/videos/feed are REAL endpoints — rewriting them
    # would mask a genuine failure of that endpoint.
    assert _registered_param_for_path("/api/users/suggested", EPS) == (None, None, -1)
    assert _registered_param_for_path("/api/videos/feed", EPS) == (None, None, -1)


def test_middle_segment_param_now_matches():
    # #323: /api/users/{username}/videos — the param is NOT the trailing segment.
    # Pre-#323 this returned (None, None); now it maps the middle segment (index 2)
    # so a chain step GET /api/users/<lit>/videos can recover a real username.
    coll, name, idx = _registered_param_for_path("/api/users/alice/videos", EPS)
    assert (coll, name, idx) == ("/api/users", "username", 2)


def test_static_prefix_must_match():
    assert _registered_param_for_path("/api/posts/13", EPS) == (None, None, -1)


def test_no_endpoints_or_empty_path_is_noop():
    assert _registered_param_for_path("/api/users/13", []) == (None, None, -1)
    assert _registered_param_for_path("", EPS) == (None, None, -1)
    assert _registered_param_for_path(None, EPS) == (None, None, -1)


def test_query_string_stripped():
    coll, name, idx = _registered_param_for_path("/api/users/13?x=1", EPS)
    assert (coll, name, idx) == ("/api/users", "username", 2)


# ---- rows extraction (recovery source) ----

def test_rows_of_payload_shapes():
    assert _rows_of_payload({"items": [{"username": "a"}]}) == [{"username": "a"}]
    assert _rows_of_payload([{"username": "a"}]) == [{"username": "a"}]
    # error envelopes must not masquerade as rows
    assert _rows_of_payload({"errors": [{"id": "E"}], "users": [{"username": "real"}]}) \
        == [{"username": "real"}]
    assert _rows_of_payload({}) == []
    assert _rows_of_payload(None) == []


def test_id_param_regex_families():
    for p in ("id", "user_id", "videoId", "pk", "uuid"):
        assert _ID_PARAM_RE.search(p), p
    for p in ("username", "handle", "slug", "email", "name"):
        assert not _ID_PARAM_RE.search(p), p
