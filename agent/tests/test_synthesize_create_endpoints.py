"""FIX #76 — CRUD-create completeness by construction (outlook run-63 STUCK-ABORT).

The kickoff LLM intermittently registers a resource's reads + reply/forward/patch/delete but
DROPS the plain create (POST /api/messages) — run-62 had it, run-63 (same env) didn't. Then
create → 405, the business_chain can't make a message, the reply/forward ${message_id} never
resolves → 422 → STUCK. synthesize_missing_create_endpoints adds the missing create for a
resource that ALREADY proves it is mutable (a collection GET + another write), so a read-only
collection is never given a spurious create, and the projector emits a real create handler.
LOCAL-ONLY (agent/tests/ gitignored).
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.database_scaffold import synthesize_missing_create_endpoints  # noqa: E402
from multi_agent.runtime.backend_skeleton import render_skeleton_main  # noqa: E402


def _cols(*names):
    out = [{"name": "id", "type": "int", "primary_key": True},
           {"name": "user_id", "type": "int", "references": "users.id"}]
    out += [{"name": n, "type": "text"} for n in names]
    return {"schema": {"columns": out}}


# the run-63 shape: reads + reply/forward/patch/delete, but NO POST /api/messages
_RUN63_EPS = [
    {"method": "GET", "path": "/api/messages"},
    {"method": "GET", "path": "/api/messages/{messageId}"},
    {"method": "PATCH", "path": "/api/messages/{messageId}"},
    {"method": "DELETE", "path": "/api/messages/{messageId}"},
    {"method": "POST", "path": "/api/messages/{messageId}/reply"},
    {"method": "POST", "path": "/api/messages/{messageId}/forward"},
]
_TABLES = {"messages": _cols("subject", "body")}


def test_synthesizes_missing_create_for_mutable_resource():
    out, added = synthesize_missing_create_endpoints(_RUN63_EPS, _TABLES)
    assert added == ["/api/messages"]
    ep = next(e for e in out if e["method"] == "POST" and e["path"] == "/api/messages")
    assert ep["schema"]["request"] == {"subject": "text", "body": "text"}  # no id/user_id/created_at


def test_subaction_alone_is_NOT_a_write_signal_477():
    """#477 reversed this, with the cost measured.

    A POST SUB-ACTION (/<res>/{id}/<verb> — rate, like, follow) is an action on a
    RELATED resource; it does not mean the collection is user-CREATABLE. Taking it
    as one marked the READ-ONLY titles catalog writable, synthesised a spurious
    POST /api/titles, and the business_chain then tested it: 400, convergence
    churn, r48/r51 never delivered.

    Only a DIRECT item mutation proves it now — "you can create X if you can
    edit/delete X"."""
    eps = [{"method": "GET", "path": "/api/posts"},
           {"method": "POST", "path": "/api/posts/{id}/like"}]
    _, added = synthesize_missing_create_endpoints(eps, {"posts": _cols("title")})
    assert added == []


def test_direct_item_mutation_is_still_a_write_signal_477():
    """The case #477 explicitly preserved: outlook messages has PATCH/DELETE
    /messages/{id}, so it still gets its create."""
    for verb in ("PATCH", "PUT", "DELETE"):
        eps = [{"method": "GET", "path": "/api/messages"},
               {"method": verb, "path": "/api/messages/{id}"}]
        _, added = synthesize_missing_create_endpoints(
            eps, {"messages": _cols("subject")})
        assert added == ["/api/messages"], verb


def test_read_only_collection_gets_no_spurious_create():
    """SAFETY: a collection with NO other write (feed/notifications) must NOT be given a create."""
    eps = [{"method": "GET", "path": "/api/feed"},
           {"method": "GET", "path": "/api/notifications"}]
    _, added = synthesize_missing_create_endpoints(
        eps, {"feed": _cols("text"), "notifications": _cols("text")})
    assert added == []


def test_existing_create_not_duplicated():
    eps = [{"method": "GET", "path": "/api/events"},
           {"method": "POST", "path": "/api/events"},
           {"method": "DELETE", "path": "/api/events/{id}"}]
    _, added = synthesize_missing_create_endpoints(eps, {"events": _cols("title")})
    assert added == []


def test_no_backing_table_skipped():
    """An aggregate/derived collection (GET /api/search) with no table gets no create."""
    eps = [{"method": "GET", "path": "/api/search"},
           {"method": "DELETE", "path": "/api/search/{id}"}]
    _, added = synthesize_missing_create_endpoints(eps, {"messages": _cols("subject")})
    assert added == []


def test_nested_collection_not_treated_as_single(tmp_path=None):
    """A nested path (/api/boards/{id}/cards) is not a single-segment collection → not
    mistaken for a top-level create target off its own GET."""
    eps = [{"method": "GET", "path": "/api/boards/{id}/cards"},
           {"method": "PATCH", "path": "/api/boards/{id}/cards/{cid}"}]
    _, added = synthesize_missing_create_endpoints(eps, {"cards": _cols("title")})
    assert added == []


def test_projector_emits_working_create_handler():
    """End-to-end: the synthesized endpoint makes render_skeleton_main project a REAL create
    handler that builds the row, injects the owner FK, and inserts it."""
    out, _ = synthesize_missing_create_endpoints(_RUN63_EPS, _TABLES)
    main = render_skeleton_main(out, _TABLES)
    import ast
    ast.parse(main)  # valid Python
    i = main.find('@app.post("/api/messages"')
    assert i > 0, "no POST /api/messages route projected"
    j = main.find("@app.", i + 10)          # slice to the next route
    block = main[i:j if j > 0 else i + 800]
    assert "def _projected_post_api_messages" in block  # a real create handler, not a stub
    assert "Message(" in block and "db.add" in block and "db.commit" in block  # real insert
    assert "user_id" in block  # injects the authenticated owner FK


def test_never_raises_on_garbage():
    assert synthesize_missing_create_endpoints(None, None) == ([], [])
    assert synthesize_missing_create_endpoints([{"bad": 1}], {}) == ([{"bad": 1}], [])


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
