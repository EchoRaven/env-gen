"""Fix #35 (complete form) — param routes: resolve a REAL id, walk the detail
page; skip only when unresolvable.

outlook run-30 (live): the browser walker navigated the LITERAL ':id' of
/inbox/message/:id → the page fetched resource ":id" → rendered empty → FALSE
blank that burned the M1 deferral budget. The interim fix (skip param routes in
_is_walkable_route) silences the false signal but leaves every DETAIL page
(read-email, event-detail) with zero deterministic walk coverage. Now
test_user_runner.resolve_param_route fetches a real row id from the backend
(param-name stem first: {eventId}→events; preceding segment second:
message→messages; canonical {items:[...]} envelope / bare list / any list
value; id/<stem>_id/uuid/_id) as the SEEDED demo user, and heal_pipeline walks
the concrete route. Unresolvable → the interim skip stands. LOCAL-ONLY
(agent/tests/ gitignored).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.heal_pipeline import _is_walkable_route  # noqa: E402
from multi_agent.runtime.test_user_runner import (  # noqa: E402
    _rows_of, resolve_param_route)


def _fake_api(routes):
    """http_get stub: {'/api/messages': (200, {...}), ...}; records calls."""
    calls = []

    def get(url, token):
        calls.append((url, token))
        path = "/" + url.split("/", 3)[-1]
        return routes.get(path, (404, {}))
    get.calls = calls
    return get


# ------------------------------------------------------------------ resolver
def test_resolves_colon_param_from_preceding_segment():
    get = _fake_api({"/api/messages": (200, {"items": [{"id": "m_77"}]})})
    assert resolve_param_route("/inbox/message/:id", "http://x:1", "tok",
                               http_get=get) == "/inbox/message/m_77"
    assert get.calls[0][1] == "tok"          # authed as the demo user


def test_resolves_braced_param_from_param_name_stem_first():
    # {eventId} → events, even though the preceding segment is 'detail'
    get = _fake_api({"/api/events": (200, {"items": [{"id": 42}]})})
    assert resolve_param_route("/detail/{eventId}", "http://x:1", None,
                               http_get=get) == "/detail/42"
    assert "/api/events" in get.calls[0][0]


def test_bare_list_and_alt_envelope_and_alt_id_keys():
    get = _fake_api({"/api/messages": (200, [{"uuid": "u-1"}])})
    assert resolve_param_route("/m/message/:id", "http://x:1", None,
                               http_get=get) == "/m/message/u-1"
    get2 = _fake_api({"/api/events": (200, {"events": [{"event_id": 9}]})})
    assert resolve_param_route("/e/event/:id", "http://x:1", None,
                               http_get=get2) == "/e/event/9"


def test_multi_param_route_resolves_each_segment():
    get = _fake_api({"/api/calendars": (200, {"items": [{"id": 3}]}),
                     "/api/events": (200, {"items": [{"id": 8}]})})
    assert resolve_param_route("/calendar/:calendarId/event/:eventId",
                               "http://x:1", None, http_get=get) \
        == "/calendar/3/event/8"


def test_unresolvable_returns_none():
    get = _fake_api({})                       # every candidate 404s
    assert resolve_param_route("/inbox/message/:id", "http://x:1", None,
                               http_get=get) is None
    # empty collection → no rows → unresolvable
    get2 = _fake_api({"/api/messages": (200, {"items": []})})
    assert resolve_param_route("/inbox/message/:id", "http://x:1", None,
                               http_get=get2) is None
    # no api base at all
    assert resolve_param_route("/inbox/message/:id", None, None,
                               http_get=get) is None


def test_concrete_route_passes_through_untouched():
    get = _fake_api({})
    assert resolve_param_route("/inbox", "http://x:1", None,
                               http_get=get) == "/inbox"
    assert get.calls == []                    # no API traffic for concrete routes


def test_non_id_params_are_never_resolved():
    """Review a7f59d24 (MAJOR): substituting a row id where a :slug/:tab/:handle
    belongs fabricates a wrong-but-plausible route (/posts/7 for /posts/:slug)
    whose detail page misses → false blank behind the BLOCKING gate. Non-id
    params must return None (interim skip stands) even when the preceding-
    segment collection 200s with rows."""
    get = _fake_api({"/api/posts": (200, {"items": [{"id": 7}]}),
                     "/api/settings": (200, {"items": [{"id": 1}]}),
                     "/api/channels": (200, {"items": [{"id": 5}]})})
    assert resolve_param_route("/posts/:slug", "http://x:1", None, http_get=get) is None
    assert resolve_param_route("/settings/:tab", "http://x:1", None, http_get=get) is None
    assert resolve_param_route("/channel/{handle}", "http://x:1", None, http_get=get) is None
    # id-shaped names still resolve: :id, {eventId}, :message_id, :uuid, :pk
    get2 = _fake_api({"/api/messages": (200, {"items": [{"id": "m1"}]})})
    assert resolve_param_route("/m/message/:message_id", "http://x:1", None,
                               http_get=get2) == "/m/message/m1"
    get3 = _fake_api({"/api/messages": (200, {"items": [{"uuid": "u9"}]})})
    assert resolve_param_route("/m/message/:uuid", "http://x:1", None,
                               http_get=get3) == "/m/message/u9"


def test_error_envelope_is_not_rows_and_id_is_url_encoded():
    """Review a7f59d24 (minor ×2): a 200 {'errors':[{'id':...}]} envelope must
    not masquerade as rows; a resolved id with URL-hostile characters must be
    percent-encoded so the SPA navigates the intended route."""
    get = _fake_api({"/api/messages": (200, {"errors": [{"id": "AUTH_REQUIRED"}]})})
    assert resolve_param_route("/m/message/:id", "http://x:1", None,
                               http_get=get) is None
    get2 = _fake_api({"/api/messages": (200, {"items": [{"id": "a/b c"}]})})
    assert resolve_param_route("/m/message/:id", "http://x:1", None,
                               http_get=get2) == "/m/message/a%2Fb%20c"


def test_rows_of_shapes():
    assert _rows_of({"items": [1]}) == [1]
    assert _rows_of([2]) == [2]
    assert _rows_of({"messages": [3], "total": 1}) == [3]
    assert _rows_of({"total": 1}) == []
    assert _rows_of("junk") == []


# ------------------------------------------- interim skip stands (walkability)
def test_param_routes_are_not_url_walkable():
    assert not _is_walkable_route("/inbox/message/:id")
    assert not _is_walkable_route("/calendar/event/{eventId}")
    assert _is_walkable_route("/inbox")
    assert _is_walkable_route("/inbox/message/m_77")   # resolved form walks


# ------------------------------------------------------------- wiring pinned
def test_heal_pipeline_resolves_before_filtering():
    src = (ROOT / "env_generator" / "llm_generator" / "multi_agent" / "runtime"
           / "heal_pipeline.py").read_text(encoding="utf-8")
    assert "resolve_param_route" in src
    assert src.index("resolve_param_route(route") < src.index(
        "if route and _is_walkable_route(route)"), \
        "resolution must run BEFORE the walkability filter"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
