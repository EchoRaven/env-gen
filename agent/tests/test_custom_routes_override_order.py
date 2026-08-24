"""custom_routes.py (the lane's OWN backend file) must OVERRIDE projected handlers.

FastAPI/Starlette matches the FIRST-registered route for a METHOD+path, so the
lane-override hook only works if the custom router is included BEFORE the projected
@app.* routes. It used to be appended in the footer (registered LAST) → the projected
stub won every duplicate and the lane's correct handler never ran: outlook run #2
aborted because GET /api/auth/me shipped the projected {"items":[]} list stub and
POST /api/events/{eventId}/rsvp shipped a null-Event create, both shadowing correct
custom_routes handlers.

LOCAL-ONLY (agent/tests/ gitignored).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.backend_skeleton import render_skeleton_main  # noqa: E402

_EPS = [
    {"method": "GET", "path": "/api/auth/me", "auth_required": True},
    {"method": "POST", "path": "/api/events/{eventId}/rsvp", "auth_required": True},
    {"method": "GET", "path": "/api/messages", "auth_required": True},
]
_TABLES = {
    "users": {"columns": [{"name": "id"}, {"name": "email"}]},
    "events": {"columns": [{"name": "id"}, {"name": "title"}]},
    "event_attendees": {"columns": [{"name": "id"}, {"name": "event_id"}, {"name": "user_id"}, {"name": "response"}]},
}


def _src():
    return render_skeleton_main(_EPS, _TABLES)


def test_custom_routes_registered_before_projected():
    src = _src()
    i_custom = src.find("import custom_routes")
    i_proj = src.find("_projected_")
    assert i_custom != -1, "custom_routes include missing"
    assert i_proj != -1, "no projected routes rendered"
    assert i_custom < i_proj, (
        "custom_routes must be included BEFORE projected routes so the lane's "
        "handler overrides the projected stub (first-registered wins in Starlette)"
    )


def test_custom_include_is_import_guarded():
    # a missing/broken custom_routes must never kill app boot
    src = _src()
    # #127: the guard is now `except ImportError as _custom_imp:` (distinguishes a nested
    # broken import from a missing custom_routes) — still import-guarded, boot never dies.
    assert "except ImportError" in src
    assert "custom_routes failed to load" in src


def test_main_guard_still_last():
    src = _src().rstrip()
    assert src.endswith('uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("API_PORT", "8081")))')


def test_projected_me_is_single_item_not_list():
    # combined with the route_projector /me fix: even the PROJECTED fallback is single
    src = _src()
    block = src[src.find('@app.get("/api/auth/me")'):]
    me_handler = block.split("\n\n\n")[0]
    assert '{"item"' in me_handler and '"items"' not in me_handler, me_handler


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))


def _classifier():
    """Extract the _custom_route_overrides_projected fn (+ its _NESTED_CHILD_RESOURCES
    set, injected from the contract) rendered into main.py."""
    src = render_skeleton_main(
        [{"method": "POST", "path": "/api/messages"}],
        {"messages": {"columns": [{"name": "id"}]},
         "projects": {"columns": [{"name": "id"}]},
         "tasks": {"columns": [{"name": "id"}, {"name": "project_id"}]}})
    fn = src[src.index("_NESTED_CHILD_RESOURCES = set("):
             src.index("try:\n    import custom_routes")]
    ns = {}
    exec(fn, ns)  # noqa: S102 — trusted framework-generated code under test
    return ns["_custom_route_overrides_projected"]


def test_nested_child_resource_keeps_projected_handler():
    # smoke-proj 2026-06-29: the projector emits a functional parent-scoped nested
    # handler for /api/projects/{id}/tasks (a real child RESOURCE) — a buggy lane
    # custom handler (it called a non-existent jwt_manager.verify_token → 500) must
    # NOT shadow it. Projected wins for nested child-resource CRUD.
    f = _classifier()
    for m, p in [("GET", "/api/projects/{id}/tasks"),
                 ("POST", "/api/projects/{id}/tasks"),
                 ("GET", "/api/projects/{pid}/tasks/{tid}"),
                 ("PUT", "/api/projects/{pid}/tasks/{tid}")]:
        assert f(m, p) is False, f"{m} {p} (nested child resource) should keep projected"


def test_nested_action_verb_lets_custom_override():
    # a nested ACTION verb (<child> is NOT a registered resource) still lets custom win.
    f = _classifier()
    for m, p in [("POST", "/api/posts/{id}/like"),
                 ("POST", "/api/projects/{id}/archive"),
                 ("POST", "/api/messages/{id}/forward")]:
        assert f(m, p) is True, f"{m} {p} (nested action) should let custom override"


def test_standard_crud_WRITES_keep_projected_handler():
    # run #7: a buggy lane POST /api/messages (wrong columns, no try/except) 500-shadowed
    # the safe projected handler. Standard-CRUD WRITES (create/update/delete) must NOT be
    # overridable — projected mutations are owner-safe + shape-consistent. /me stays projected.
    f = _classifier()
    for m, p in [("POST", "/api/messages"),
                 ("PATCH", "/api/messages/{messageId}"),
                 ("DELETE", "/api/messages/{messageId}")]:
        assert f(m, p) is False, f"{m} {p} should keep the projected handler"


def test_auth_me_lets_custom_override():
    # run-27 (backend_skeleton lines 823-832): the projector EXCLUDES the /auth|/oauth control
    # surface, so there is NO projected handler for /api/auth/me. A lane-authored custom
    # /api/auth/me must therefore be KEPT (custom wins) — dropping it would 404 the frontend's
    # session restore. (/api/users/me & bare /me, which the projector DOES emit, stay projected.)
    f = _classifier()
    assert f("GET", "/api/auth/me") is True
    assert f("GET", "/api/oauth/me") is True


def test_standard_crud_GET_reads_keep_the_projected_read_528():
    """#528 reversed this case, and #77 had already removed its reason.

    The original expectation (outlook run-9) was that a lane GET must win because
    "the projected list / item-by-id GET is NOT owner-scoped, so a per-user-PRIVATE
    resource LEAKS other users' rows". #77 made the projected read owner-scoped BY
    CONSTRUCTION, which settles that; #528 then measured the opposite failure on
    netflix, live — a lane custom GET on a registered resource routinely runs raw
    SQL over columns that do not exist, 500s, and wedges business_chain while the
    frontend starves. The projected read is schema-safe and 200/404 by
    construction, so for GET on the two standard-CRUD read shapes of a REGISTERED
    resource it now wins.

    `messages` is registered by _classifier's table map, so both shapes below are
    exactly that case."""
    f = _classifier()
    for m, p in [("GET", "/api/messages"),
                 ("GET", "/api/messages/{messageId}")]:
        assert f(m, p) is False, f"{m} {p} (registered resource) must keep the projected read"


def test_unregistered_collection_get_still_lets_the_lane_win_528():
    """#528's own carve-out: the guard is GATED on registered-resource membership,
    because deciding projected-wins where no projected handler exists would 404."""
    f = _classifier()
    assert f("GET", "/api/search") is True
    assert f("GET", "/api/dashboard") is True


def test_action_endpoints_let_custom_override():
    # the /{id}/<verb> actions the projector mis-handles (treats as a create) → custom wins
    f = _classifier()
    for m, p in [("POST", "/api/messages/{messageId}/reply"),
                 ("POST", "/api/messages/{messageId}/forward"),
                 ("POST", "/api/events/{eventId}/rsvp")]:
        assert f(m, p) is True, f"{m} {p} should let custom_routes override"
