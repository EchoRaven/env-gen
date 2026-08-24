"""FIX #77 — owner-scoped-read isolation is FRAMEWORK-OWNED (outlook run-64 STUCK, 75min).

run-64: a lane custom GET /api/messages/{id} was UNSCOPED and OVERRODE the framework's scoped
projected read → cross-user leak → isolation depended on the LANE fixing its own read → the
75-min wall fired. #77 makes the framework OWN it. Two parts, both adversarially-review-hardened:

Part 1 (heal_pipeline._isolation_scoped_tables_from_chains): read-scoping may only be inferred
from a cross-user GET denial. A PUT/DELETE denial proves only WRITE authz (true for PUBLIC
resources too) — deriving read-scoping from it wrongly scoped a world-readable feed. Also the
by-id TARGET's collection is the segment BEFORE {id} (nested /posts/{id}/comments/{cid}→comments,
not posts).

Part 2 (backend_skeleton): for a flagged-private resource with a SINGLE unambiguous owner FK, the
PROJECTED scoped read WINS over the lane custom GET. A public feed (never flagged) and a
multi-principal DM table (sender+recipient — projected single-owner read would 404 the recipient)
are EXCLUDED → lane still wins. LOCAL-ONLY (agent/tests/ gitignored).
"""

import ast
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.heal_pipeline import _isolation_scoped_tables_from_chains  # noqa: E402
from multi_agent.runtime.backend_skeleton import render_skeleton_main  # noqa: E402


# ── Part 1: only a cross-user GET denial implies read-scoping ─────────────────
def _hub(chains):
    return types.SimpleNamespace(get_verification_chains=lambda: chains)


def _chain(*steps):
    return {"c": {"steps": list(steps)}}


def test_get_denial_flags_read_scoping():
    hub = _hub(_chain({"method": "GET", "path": "/api/messages/${mid}", "expect": [404]}))
    assert _isolation_scoped_tables_from_chains(hub, {"messages"}) == {"messages"}


def test_write_denial_does_NOT_flag_read_scoping():
    """A cross-user DELETE/PUT denial proves write-authz only — must NOT scope reads (else a
    public comment/post feed silently becomes per-user-private)."""
    for m in ("DELETE", "PUT", "PATCH"):
        hub = _hub(_chain({"method": m, "path": "/api/comments/${cid}", "expect": [403]}))
        assert _isolation_scoped_tables_from_chains(hub, {"comments"}) == set(), m


def test_nested_by_id_denial_attributes_the_child_not_parent():
    """/api/posts/{id}/comments/{cid} GET-denied → scope 'comments' (the by-id target), NOT
    'posts' (which would hide the whole public feed)."""
    hub = _hub(_chain({"method": "GET", "path": "/api/posts/${pid}/comments/${cid}", "expect": [404]}))
    assert _isolation_scoped_tables_from_chains(hub, {"posts", "comments"}) == {"comments"}


def test_bare_collection_get_denial_uses_last_segment():
    hub = _hub(_chain({"method": "GET", "path": "/api/notes", "expect": [403]}))
    assert _isolation_scoped_tables_from_chains(hub, {"notes"}) == {"notes"}


# ── Part 2: the projected-wins flip, scoped by principal-ambiguity ────────────
def _T(cols, owner_scoped=False):
    return {"schema": {"columns": cols}, "metadata": {"owner_scoped_reads": owner_scoped}}


def _pk(n="id"):
    return {"name": n, "type": "int", "primary_key": True}


def _fk(n):
    return {"name": n, "type": "int", "references": "users.id"}


_TABLES = {
    "users": _T([_pk(), {"name": "email", "type": "str"}]),
    "messages": _T([_pk(), _fk("user_id"), {"name": "body", "type": "str"}], owner_scoped=True),
    "feed": _T([_pk(), _fk("user_id"), {"name": "text", "type": "str"}], owner_scoped=False),
    "dms": _T([_pk(), _fk("sender_id"), _fk("recipient_id"), {"name": "body", "type": "str"}], owner_scoped=True),
}
_EPS = [{"method": "GET", "path": "/api/messages"}, {"method": "GET", "path": "/api/messages/{id}"},
        {"method": "GET", "path": "/api/feed/{id}"}, {"method": "GET", "path": "/api/dms/{id}"}]


def _override_fn():
    main = render_skeleton_main(_EPS, _TABLES)
    ast.parse(main)  # generated main is valid Python
    blk = main[main.index("_NESTED_CHILD_RESOURCES = "):main.index("try:\n    import custom_routes")]
    ns = {}
    exec(blk, ns)
    return ns["_custom_route_overrides_projected"]


def test_private_single_fk_resource_projected_read_wins():
    f = _override_fn()
    assert f("GET", "/api/messages/{id}") is False   # projected scoped read wins (no leak)
    assert f("GET", "/api/messages") is False


def test_public_resource_keeps_the_projected_read_528():
    """#528 reversed this one deliberately, and said so.

    `feed` is never flagged for GET-denial, so it is not in _OWNER_SCOPED_RESOURCES —
    which used to mean the lane read wins. #528 extended projected-wins to ANY
    registered resource and named the trade-off: "public LIST/read now serves from
    the PROJECTED handler (schema-correct, returns rows) instead of lane raw SQL —
    this trades any lane-added filtering/sorting on PUBLIC lists for guaranteed
    reachability/correctness", after measuring lane GETs that ran raw SQL over
    columns that do not exist, 500'd, and wedged business_chain.

    The isolation property this file is about is untouched: nothing here is a
    privacy boundary, and #1059's multi-principal carve-out below still holds."""
    f = _override_fn()
    assert f("GET", "/api/feed/{id}") is False


def test_multi_principal_dm_excluded_lane_wins():
    """dms has sender_id + recipient_id → the single-owner projected read would 404 the
    recipient → excluded → the lane's OR-correct read wins."""
    f = _override_fn()
    assert f("GET", "/api/dms/{id}") is True


def test_namespaced_path_still_covered():
    f = _override_fn()
    assert f("GET", "/api/v1/messages/{id}") is False  # resolves 'messages' via segment-before-id


def test_writes_and_actions_unaffected():
    """#77 only guards the GET branches (the _is_get gate), so non-GET verbs are byte-for-byte
    the pre-#77 behaviour: standard-CRUD writes keep the projected handler (return False),
    and an action verb falls through to the lane (return True)."""
    f = _override_fn()
    assert f("POST", "/api/messages") is False         # projected create wins (unchanged)
    assert f("PUT", "/api/messages/{id}") is False     # projected update wins (unchanged)
    assert f("POST", "/api/messages/{id}/reply") is True  # action verb → lane wins (unchanged)


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
