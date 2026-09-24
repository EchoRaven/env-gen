"""#323 — _registered_param_for_path must match a {param} in ANY segment position (not
just trailing), so the chain executor can recover an invented user in a sub-resource read.

r92 M3 NO-CONVERGENCE (75min): a chain authored GET /api/users/Owner/favorites against
/api/users/{username}/favorites. #245 only matched a TRAILING {param}, so "Owner" (no
such user; seed has real users avachen/therock/...) never recovered → business_chain
wedged. Now the param may be a MIDDLE segment; the function returns its index so the
caller replaces the RIGHT segment.
"""
import sys
from pathlib import Path
THIS = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS.parent / "env_generator" / "llm_generator"))
from multi_agent.runtime.chain_executor import _registered_param_for_path as f  # noqa: E402

EPS = [{"path": "/api/users/{username}"},
       {"path": "/api/users/{username}/favorites"},
       {"path": "/api/users/{username}/liked"},
       {"path": "/api/users/suggested"},
       {"path": "/api/posts/{id}"}]


def test_middle_param_favorites_matched():
    assert f("/api/users/Owner/favorites?sort=latest", EPS) == ("/api/users", "username", 2)


def test_middle_param_liked_matched():
    assert f("/api/users/Owner/liked", EPS) == ("/api/users", "username", 2)


def test_trailing_param_still_matched():
    assert f("/api/users/ProfileUser", EPS) == ("/api/users", "username", 2)


def test_static_endpoint_never_treated_as_param():
    assert f("/api/users/suggested", EPS) == (None, None, -1)   # STATIC WINS


def test_id_param_returned_for_caller_to_filter():
    # the function returns the id param; the CALLER filters it via _ID_PARAM_RE (so #136
    # numeric recovery handles it, not the username-field path).
    assert f("/api/posts/999", EPS) == ("/api/posts", "id", 2)


def test_no_template_match():
    assert f("/api/videos/5/comments", EPS) == (None, None, -1)
