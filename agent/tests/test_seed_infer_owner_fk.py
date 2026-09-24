"""Seed rows for owner-scoped resources must carry their owner FK even when the lane
declared the column as a BARE ``user_id = Column(Integer)`` with no ForeignKey. Without
it the owner is NULL → owner-scoped reads return ZERO rows → every authenticated page is
blank though auth + endpoints work (outlook MM, 2026-06-29: avachen logged in but saw 0
folders/messages). render_seed_data now infers convention FKs (`user_id`→users,
`folder_id`→folders, `tenant_id`→tenants).
"""

import ast
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.backend_skeleton import _seed_infer_fk, render_seed_data  # noqa: E402


def test_infer_owner_and_parent_and_tenant():
    known = {"users", "folders", "messages", "tenants"}
    assert _seed_infer_fk("user_id", known) == "users"
    assert _seed_infer_fk("owner_id", known) == "users"        # synonym, no owners table
    assert _seed_infer_fk("created_by", known) == "users"
    assert _seed_infer_fk("folder_id", known) == "folders"     # base matches a table
    assert _seed_infer_fk("message_id", known) == "messages"
    assert _seed_infer_fk("tenant_id", known) == "tenants"


def test_seed_recognizes_EVERY_owner_name_the_reads_scope_on():
    """The by-construction guarantee: any column route_projector._owner_fk would scope a
    read on MUST be seeded with a user owner — else that table's owner reads go empty.
    Locks seed's owner vocabulary to the read side's, so a future env can't drift."""
    from multi_agent.runtime.route_projector import _OWNER_FK_NAMES, _TARGET_FK_NAMES
    known = {"users", "tenants"}
    for name in tuple(_OWNER_FK_NAMES) + tuple(_TARGET_FK_NAMES):
        assert _seed_infer_fk(name, known) == "users", (
            f"read side scopes on {name!r} but seed would leave it NULL → empty pages")
    # these are exactly the names the OLD synonym-only heuristic MISSED → would have
    # shipped blank owner-scoped pages on a feed/social/upload env:
    for missed in ("from_user_id", "actor_id", "uploaded_by", "addressee_id", "posted_by"):
        assert _seed_infer_fk(missed, known) == "users"


def test_infer_is_conservative():
    known = {"users", "folders"}
    # not an FK-looking column, or a base with no matching table & not an owner synonym
    assert _seed_infer_fk("subject", known) is None
    assert _seed_infer_fk("external_id", known) is None
    assert _seed_infer_fk("parent_id", known) is None          # no 'parents' table
    # explicit-FK columns are still inferred fine (caller prefers the explicit one)
    assert _seed_infer_fk("user_id", {"folders"}) is None      # no users table → leave NULL


def _seed_dict(py_src):
    """Extract the literal ``_SEED = {...}`` dict from generated seed_data.py."""
    tree = ast.parse(py_src)
    for node in tree.body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "_SEED":
            return ast.literal_eval(node.value)
    raise AssertionError("no _SEED in generated module")


def _tables_with_bare_user_id():
    # exactly the outlook shape: user_id / folder_id are BARE Integer columns (no fk)
    col = lambda name, typ, **kw: {"name": name, "type": typ, **kw}
    return {
        "users": {"schema": {"columns": [
            col("id", "serial", primary_key=True), col("email", "text")]}},
        "folders": {"schema": {"columns": [
            col("id", "serial", primary_key=True),
            col("user_id", "integer"),            # ← bare, no fk
            col("name", "text")]}},
        "messages": {"schema": {"columns": [
            col("id", "serial", primary_key=True),
            col("user_id", "integer"),            # ← bare, no fk
            col("folder_id", "integer"),          # ← bare, no fk
            col("subject", "text")]}},
    }


def test_generated_seed_populates_owner_fk():
    src = render_seed_data(_tables_with_bare_user_id())
    seed = _seed_dict(src)
    # every folder + message row carries a real owner in 1..5 (the seeded user ids)
    assert seed["folders"], "folders should be seeded"
    for r in seed["folders"]:
        assert r.get("user_id") in range(1, 6), f"folder owner not seeded: {r}"
    for r in seed["messages"]:
        assert r.get("user_id") in range(1, 6), f"message owner not seeded: {r}"
        assert r.get("folder_id") in range(1, 7), f"message folder not seeded: {r}"
    # the first seeded user (id 1 — the demo/test-user login) owns at least one row,
    # so the authenticated landing page is never blank
    assert any(r.get("user_id") == 1 for r in seed["folders"])
    assert any(r.get("user_id") == 1 for r in seed["messages"])


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
