"""Gate C — behavioral COMPLETENESS gate in validation_runner.

A delivered endpoint must not just be REACHABLE (<500); its 2xx response must match
the response-contract SHAPE for its path-type (single resource → {item}, collection →
{items}). This is the hard guarantee that catches the real instagram M1 bug where
GET /api/users/me returned {"items":[all users]} — reachable but semantically wrong,
and api_smoke's <500 check missed it.
"""

import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.validation_runner import _expected_shape, _shape_violation  # noqa: E402


def test_expected_shape_single_vs_collection():
    # single → "item"
    assert _expected_shape("GET", "/api/users/me") == "item"
    assert _expected_shape("GET", "/api/users/{username}") == "item"
    assert _expected_shape("GET", "/api/posts/{id}") == "item"
    assert _expected_shape("POST", "/api/posts") == "item"
    assert _expected_shape("PUT", "/api/users/me") == "item"
    assert _expected_shape("DELETE", "/api/posts/{id}") == "item"
    # collection → "items"
    assert _expected_shape("GET", "/api/feed") == "items"
    assert _expected_shape("GET", "/api/users/suggested") == "items"
    assert _expected_shape("GET", "/api/users") == "items"
    assert _expected_shape("GET", "/api/posts/{id}/comments") == "items"


def test_me_returning_a_list_is_flagged():
    """The exact instagram M1 bug: GET /api/users/me returned {items:[all users]}."""
    v = _shape_violation("GET", "/api/users/me", 200, '{"items":[{"id":1},{"id":2}]}')
    assert v is not None and "single item" in v


def test_me_returning_single_item_passes():
    assert _shape_violation("GET", "/api/users/me", 200, '{"item":{"id":1}}') is None


def test_collection_returning_single_is_flagged():
    v = _shape_violation("GET", "/api/feed", 200, '{"item":{"id":1}}')
    assert v is not None and "list (items)" in v


def test_collection_returning_items_passes():
    assert _shape_violation("GET", "/api/feed", 200, '{"items":[],"total":0}') is None


def test_non_2xx_is_not_flagged():
    # a 4xx/5xx is the reachable gate's job, not the shape gate's
    assert _shape_violation("GET", "/api/users/me", 404, '{"items":[]}') is None
    assert _shape_violation("GET", "/api/users/me", None, "") is None


def test_custom_or_bare_shape_is_left_alone():
    # conservative: a response with neither item nor items key isn't force-failed
    assert _shape_violation("GET", "/api/users/me", 200, '{"id":1,"username":"x"}') is None
    assert _shape_violation("GET", "/api/feed", 200, "[]") is None       # bare array → not a dict
    assert _shape_violation("GET", "/api/users/me", 200, "not json") is None
