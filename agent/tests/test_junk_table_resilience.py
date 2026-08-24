"""FIX #90 — a junk no-column table registration must not KILL the run (run-9, 2026-07-06).

Run-9 delivered M1 (v1.0.0) then DIED at M2 kickoff: `Generation failed:
database_scaffold: table 'dummy' has no columns` — the lane registered a placeholder
table with no columns and render_schema_sql raised, aborting the whole run. The MODELS
renderer already tolerates this exact shape (it synthesises an `id` PK when none exists),
so the DDL renderer raising is an inconsistency, not a safety net. Fixes: (a) DDL
synthesises the same `id` PK (junk table → harmless one-column table, renderers agree);
(b) register_table rejects an EXPLICITLY empty schema at the write boundary so the LLM
gets immediate feedback (name-only pre-registration with schema=None stays allowed).
ENV-AGNOSTIC + LOCAL-ONLY (agent/tests/ gitignored).
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.database_scaffold import render_schema_sql  # noqa: E402


def test_no_column_table_renders_synthesised_pk_instead_of_raising():
    tables = {
        "dummy": {"name": "dummy", "schema": {}},                     # the run-9 killer
        "posts": {"name": "posts", "columns": [
            {"name": "id", "type": "integer", "primary_key": True},
            {"name": "caption", "type": "text"}]},
    }
    sql = render_schema_sql(tables)                                   # must NOT raise
    assert '"posts"' in sql and "caption" in sql                      # real table intact
    assert '"dummy"' in sql                                           # junk table exists,
    assert "id" in sql.split('"dummy"', 1)[1][:200]                   # with a synthesised id


def test_named_but_empty_columns_list_also_survives():
    sql = render_schema_sql({"t": {"name": "t", "columns": []}})
    assert '"t"' in sql


def test_ddl_and_models_renderers_agree_on_junk_tables():
    """the models renderer always synthesised an id PK for column-less tables; after
    FIX #90 the DDL renderer does the same — a junk registration yields a harmless
    one-column table in BOTH, never a dead run. (A write-boundary rejection was tried
    and reverted: kickoff/seed flows legitimately register empty/minimal schemas.)"""
    from multi_agent.runtime.backend_skeleton import render_models
    models = render_models({"dummy": {"name": "dummy", "schema": {}}})
    assert "class" in models and "dummy" in models                    # model exists
    sql = render_schema_sql({"dummy": {"name": "dummy", "schema": {}}})
    assert '"dummy"' in sql                                           # table exists too


def test_projected_create_reraises_integrity_errors_for_global_mapping():
    """FIX #93 (run-12 M2 live): POST /api/users probe → NotNullViolation
    (password_hash) → the projected create's catch-all turned it into an
    HONEST-but-wrong 500 'create failed', BYPASSING #82's global IntegrityError
    handler → business_endpoints_reachable wedged 7 cycles. Integrity errors are
    CLIENT-DATA problems (REST 4xx): the projected create/update must rollback and
    RE-RAISE IntegrityError so the by-construction global handler maps it
    (23503→404, 23505→409, other incl. NotNull→400). Genuine server bugs still 500."""
    import inspect
    from multi_agent.runtime import route_projector
    src = inspect.getsource(route_projector)
    assert "except IntegrityError" in src
    # the generated handler code re-raises (global handler owns the mapping)
    i = src.index("except IntegrityError")
    # semantic end: the handler block this anchor opens, not a character count
    _end = src.find("\ndef ", i)          # last top-level construct -> EOF
    window = src[i:_end if _end != -1 else len(src)]
    assert "rollback" in window and "raise" in window
    # and the generated main.py header imports it
    from multi_agent.runtime.backend_skeleton import _MAIN_HEADER
    assert "IntegrityError" in _MAIN_HEADER


def test_counter_columns_default_zero_by_construction():
    """FIX #97 (run-15 live): post.likes_count += 1 hit a NULL (seed omitted it, no
    DB default) → TypeError → 500 → business_chain wedge. Counter columns
    (integer *_count, non-PK, non-FK, no explicit default) get DEFAULT 0 in BOTH
    renderers by construction — a NULL counter can then never reach handler code
    for rows that simply omit the column."""
    tables = {"posts": {"name": "posts", "columns": [
        {"name": "id", "type": "integer", "primary_key": True},
        {"name": "likes_count", "type": "integer"},
        {"name": "user_id", "type": "integer", "references": "users.id"},
    ]}}
    sql = render_schema_sql(tables)
    seg = sql.split("likes_count", 1)[1].split("\n", 1)[0]
    assert "DEFAULT 0" in seg, sql
    from multi_agent.runtime.backend_skeleton import render_models
    models = render_models(tables)
    line = [l for l in models.splitlines() if "likes_count" in l][0]
    assert "default=0" in line or "server_default" in line, line
    # explicit defaults / FK ints / PKs untouched
    assert "user_id" in sql and "DEFAULT 0" not in sql.split("user_id", 1)[1].split("\n", 1)[0]
