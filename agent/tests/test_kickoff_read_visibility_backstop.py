"""Deterministic READ-VISIBILITY backstop in kickoff contract synthesis.

The per-table owner_scoped_reads flag is LLM-authored (backend kickoff) and
demonstrably inconsistent run-to-run (smoke-notes: set in exp3, forgotten in
exp1/exp5 → a per-user-private app shipped with leaking reads). _build_contract
fills the gap deterministically: when the lane did NOT decide owner_scoped_reads,
the table is owned-per-user (owner FK to users), AND the GOAL explicitly states
per-user privacy, set it true. Explicit lane decisions are always respected;
public-feed goals match none of the private phrases.
"""

import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.kickoff.run_kickoff import (  # noqa: E402
    _build_contract,
    _goal_implies_per_user_private,
    _table_has_owner_fk,
)

# the real smoke-notes goal (the run that FORGOT the flag)
_NOTES_GOAL = (
    'Build a minimal multi-tenant "Notes" web application. Authenticated entry. '
    "Each user only sees their own notes. Business rows are owned per user; every "
    "query is scoped to the authenticated user."
)
_PUBLIC_FEED_GOAL = (
    "Build a social photo feed. Users post photos; the home feed shows posts from "
    "everyone, newest first. Anyone can open any post by id and view its comments. "
    "A public explore page surfaces trending posts."
)

_NOTES_TABLE = {"name": "notes", "columns": [
    {"name": "id", "type": "int", "primary_key": True},
    {"name": "user_id", "type": "int", "references": "users.id"},
    {"name": "title", "type": "text"},
]}
_POSTS_TABLE = {"name": "posts", "columns": [
    {"name": "id", "type": "int", "primary_key": True},
    {"name": "author_id", "type": "int", "references": "users.id"},
    {"name": "caption", "type": "text"},
]}


# ---- phrase detector --------------------------------------------------------

def test_goal_detects_per_user_private():
    assert _goal_implies_per_user_private(_NOTES_GOAL) is True
    assert _goal_implies_per_user_private("every record is scoped to the authenticated user") is True
    assert _goal_implies_per_user_private("each user can only see their own orders") is True


def test_goal_does_not_match_public_feed():
    assert _goal_implies_per_user_private(_PUBLIC_FEED_GOAL) is False
    assert _goal_implies_per_user_private("a shared public catalog everyone can browse") is False
    assert _goal_implies_per_user_private("") is False


# ---- owner-fk detector ------------------------------------------------------

def test_owner_fk_detection():
    assert _table_has_owner_fk(_NOTES_TABLE) is True
    assert _table_has_owner_fk(_POSTS_TABLE) is True   # author_id is an owner fk
    assert _table_has_owner_fk({"name": "tags", "columns": [
        {"name": "id", "type": "int", "primary_key": True},
        {"name": "label", "type": "text"}]}) is False


# ---- _build_contract integration -------------------------------------------

def _contract(table, goal):
    drafts = {"backend": {"endpoints": [{"method": "GET", "path": "/api/notes"}],
                          "data_model": {"tables": [table]}}}
    c = _build_contract(drafts, goal)
    return c["data_model"]["tables"][0]

def test_backstop_sets_flag_for_private_goal_owner_table():
    t = _contract(dict(_NOTES_TABLE), _NOTES_GOAL)
    assert t.get("owner_scoped_reads") is True

def test_backstop_skips_public_feed_goal():
    t = _contract(dict(_POSTS_TABLE), _PUBLIC_FEED_GOAL)
    assert "owner_scoped_reads" not in t          # public goal → untouched

def test_backstop_skips_table_without_owner_fk():
    tags = {"name": "tags", "columns": [
        {"name": "id", "type": "int", "primary_key": True},
        {"name": "label", "type": "text"}]}
    t = _contract(tags, _NOTES_GOAL)              # private goal but no owner fk
    assert "owner_scoped_reads" not in t

def test_explicit_lane_decision_false_is_respected():
    # the lane EXPLICITLY marked it public — the backstop must NOT override
    tbl = {**_NOTES_TABLE, "owner_scoped_reads": False}
    t = _contract(tbl, _NOTES_GOAL)
    assert t.get("owner_scoped_reads") is False

def test_explicit_lane_decision_true_is_respected():
    tbl = {**_POSTS_TABLE, "owner_scoped_reads": True}
    t = _contract(tbl, _PUBLIC_FEED_GOAL)
    assert t.get("owner_scoped_reads") is True


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
