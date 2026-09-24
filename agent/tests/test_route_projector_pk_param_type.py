"""The projected by-id path param must follow the resource's PRIMARY-KEY column type.

A STRING/UUID primary key (outlook messages.id = String) was typed ``int`` because the
skeleton's _models_meta produced no per-column ``types`` map, so route_projector fell back
to the ``id → int`` default → a UUID path 422'd "Input should be a valid integer", wedging
business_chain. _models_meta now carries ``types`` (SQLAlchemy names), so a String PK types
the param ``str`` and an integer PK still types it ``int``.
"""

import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.backend_skeleton import render_skeleton_main  # noqa: E402


def _byid_handler_sig(pk_type):
    tables = {
        "users": {"schema": {"columns": [{"name": "id", "type": "serial", "primary_key": True}]}},
        "messages": {"schema": {"columns": [
            {"name": "id", "type": pk_type, "primary_key": True},
            {"name": "user_id", "type": "integer", "fk": "users.id"},
            {"name": "subject", "type": "text"}]}},
    }
    eps = [{"method": "GET", "path": "/api/messages/{messageId}"}]
    src = render_skeleton_main(eps, tables)
    line = next((ln for ln in src.splitlines()
                 if ln.startswith("def ") and "messages_messageid" in ln.lower()), "")
    return line


def test_uuid_pk_types_param_str():
    for t in ("uuid", "text", "varchar", "string"):
        sig = _byid_handler_sig(t)
        assert "messageId: str" in sig, f"{t!r} PK should type the by-id param str: {sig}"


def test_integer_pk_types_param_int():
    for t in ("serial", "integer", "bigint"):
        sig = _byid_handler_sig(t)
        assert "messageId: int" in sig, f"{t!r} PK should type the by-id param int: {sig}"


def test_types_map_populated_for_search():
    # the same `types` map lets search filter to text columns (no all-columns fallback)
    from multi_agent.runtime.backend_skeleton import _models_meta
    meta = _models_meta({"messages": {"schema": {"columns": [
        {"name": "id", "type": "uuid", "primary_key": True},
        {"name": "subject", "type": "text"},
        {"name": "is_read", "type": "boolean"}]}}})
    assert meta["messages"]["types"]["id"] == "String"
    assert meta["messages"]["types"]["subject"] == "Text"
    assert meta["messages"]["types"]["is_read"] == "Boolean"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
