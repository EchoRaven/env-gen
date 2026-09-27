"""#1202we: `/api/users/${id}` is the ITEM endpoint, not the collection.

`_norm_api_path_1202uv` turns a frontend call's template literal into a comparable path, and
it ended with `re.sub(r"\\{\\}$", "", q)` under the comment "a trailing query template is not a
path segment". That intent is right -- ``/api/search${qs}`` really is a suffix, not a segment
-- but the implementation stripped EVERY trailing `{}`, including one that follows a slash.

So `/api/users/${id}` came out as `/api/users`, and the two are different endpoints. A
contract carrying `GET /api/users/{id}` and not `GET /api/users` sees the call as
unimplemented; one carrying only the collection hides a genuinely missing item route.
MEASURED across the corpus: 288 calls in 117 of 157 runs end in a path-segment
interpolation, against 199 that end in a real suffix.

The distinction was already in the text the rule was reading: what precedes the `${`.
"""
import os
import sys

import pytest

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

from multi_agent.runtime.scaffolder import _norm_api_path_1202uv  # noqa: E402


@pytest.mark.parametrize("raw,expect", [
    # the segment: kept, because a slash precedes the interpolation
    ("/api/users/${id}", "/api/users/{}"),
    ("/api/places/${placeId}", "/api/places/{}"),
    ("/api/saved-lists/${l}/items/${p}", "/api/saved-lists/{}/items/{}"),
    ("/api/a/${x}?y=1", "/api/a/{}"),
    # the suffix: still stripped, which is what the rule was written for
    ("/api/search${qs}", "/api/search"),
    ("/api/videos${query}", "/api/videos"),
    # untouched shapes
    ("/api/videos/${id}/like", "/api/videos/{}/like"),
    ("/api/health", "/api/health"),
])
def test_the_slash_decides(raw, expect):
    assert _norm_api_path_1202uv(raw) == expect


def test_an_unresolvable_interpolation_is_still_refused():
    """Under-reporting stays the bargain: a literal this cannot close yields None."""
    assert _norm_api_path_1202uv("/api/x/${broken") is None


def test_the_item_and_the_collection_do_not_collide():
    """★ The property the regex used to destroy: two calls, two endpoints."""
    item = _norm_api_path_1202uv("/api/users/${id}")
    coll = _norm_api_path_1202uv("/api/users")
    assert item != coll, (
        "a call to one must never be comparable against the contract entry for the other")
