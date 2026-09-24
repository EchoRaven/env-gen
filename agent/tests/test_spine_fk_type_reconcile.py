"""FK columns targeting a framework SPINE table must be typed to the spine PK (outlook
run-16, 2026-06-30).

Live-reproduced: the projected create handler bound ``user.id`` into the ``user_id`` column and
psycopg raised ``(DatatypeMismatch) column "user_id" is of type integer but expression is of type
character varying``. Cause: the lane declared ``Message.user_id = Column(String)`` while the
framework's ``users.id`` is a SERIAL integer (database_scaffold; JWT sub == str(users.id)).
``_reconcile_fk_types_in_map`` USED to skip FKs whose target isn't an app table — so FKs to the
spine ``users``/``tenants`` were never reconciled → SQLAlchemy binds VARCHAR → every INSERT with an
owner FK 500s. Now spine-targeting FKs are coerced to the spine PK's FIXED category
(users→integer, tenants→text). ENV-AGNOSTIC + LOCAL-ONLY (agent/tests/ gitignored).
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from multi_agent.runtime.backend_skeleton import (  # noqa: E402
    _reconcile_fk_types_in_map, _fk_type_category, render_models)


def _col(cols, name):
    return next(c for c in cols if c["name"] == name)


def test_string_user_id_fk_coerced_to_integer():
    by_name = {
        "messages": [{"name": "id", "type": "text", "primary_key": True},
                     {"name": "user_id", "type": "varchar", "references": "users.id"}],
        "folders":  [{"name": "id", "type": "text", "primary_key": True},
                     {"name": "user_id", "type": "text", "references": "users.id"}],
    }
    _reconcile_fk_types_in_map(by_name)
    for tbl in ("messages", "folders"):
        c = _col(by_name[tbl], "user_id")
        assert _fk_type_category(c["type"]) == "integer", (tbl, c)
        assert c.get("references") == "users.id"          # FK target preserved (structured field)


def test_tenant_fk_coerced_to_text():
    by_name = {"docs": [{"name": "id", "type": "integer", "primary_key": True},
                        {"name": "tenant_id", "type": "integer", "references": "tenants.id"}]}
    _reconcile_fk_types_in_map(by_name)
    assert _fk_type_category(_col(by_name["docs"], "tenant_id")["type"]) == "text"


def test_already_integer_user_id_untouched():
    by_name = {"m": [{"name": "id", "type": "text", "primary_key": True},
                     {"name": "user_id", "type": "integer", "references": "users.id"}]}
    _reconcile_fk_types_in_map(by_name)
    assert _fk_type_category(_col(by_name["m"], "user_id")["type"]) == "integer"


def test_app_table_fk_majority_vote_still_works():
    # a NON-spine app FK keeps the existing majority-vote reconcile (regression guard):
    # calendar_id (integer) referencing calendars.id (declared text) → calendars.id -> integer
    by_name = {
        "calendars": [{"name": "id", "type": "text"}],                       # declared text PK
        "events":    [{"name": "id", "type": "text", "primary_key": True},
                      {"name": "calendar_id", "type": "integer", "references": "calendars.id"}],
    }
    _reconcile_fk_types_in_map(by_name)
    assert _fk_type_category(_col(by_name["calendars"], "id")["type"]) == "integer"  # PK -> majority
    assert _fk_type_category(_col(by_name["events"], "calendar_id")["type"]) == "integer"


def test_unknown_external_fk_left_alone():
    by_name = {"x": [{"name": "id", "type": "text", "primary_key": True},
                     {"name": "ext_id", "type": "text", "references": "somewhere_external.id"}]}
    _reconcile_fk_types_in_map(by_name)
    assert _fk_type_category(_col(by_name["x"], "ext_id")["type"]) == "text"   # untouched


def test_render_models_emits_integer_user_id_fk():
    tables = {"messages": {"columns": [
        {"name": "id", "type": "text"},
        {"name": "user_id", "type": "varchar", "references": "users.id"},
        {"name": "subject", "type": "text"}]}}
    src = render_models(tables)
    line = next(l for l in src.splitlines() if "user_id" in l)
    assert "Integer" in line, line
    assert "String" not in line and "Text" not in line, line
    assert "ForeignKey" in line, line          # FK still declared


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
