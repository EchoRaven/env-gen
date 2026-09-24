"""FIX #216 — a column named after a SQLAlchemy-declarative-RESERVED attribute
(``metadata``, ``registry``) must be remapped, or ``import models`` crashes.

Found by a proactive codegen stress-audit (not a full run): a contract column
named ``metadata`` renders ``metadata = Column(Text)``, and the declarative mapper
raises ``InvalidRequestError: Attribute name 'metadata' is reserved when using the
Declarative API`` → the backend won't boot → backend_health/business_chain fail →
delivery deadlock. Same class as #215/#158 (a column name that breaks the ORM).
``safe_column_name`` (#158) already remaps python keywords + non-identifiers and
pins the real DB name positionally; extend it to the SQLA-reserved attribute
names. Env-agnostic: ``metadata`` is a common column name (posts/files/events).
"""

import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.backend_skeleton import render_models, safe_column_name  # noqa: E402


def _exec_models(tables):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import declarative_base
    Base = declarative_base()
    db_mod = types.ModuleType("database")
    db_mod.Base = Base
    db_mod.engine = create_engine("sqlite://")
    sys.modules["database"] = db_mod
    models_mod = types.ModuleType("models")
    try:
        exec(compile(render_models(tables), "models.py", "exec"), models_mod.__dict__)
        Base.metadata.create_all(db_mod.engine)
    finally:
        sys.modules.pop("database", None)
    return models_mod


def test_metadata_column_does_not_break_import():
    tables = {"posts": {"columns": [
        {"name": "id", "type": "integer", "primary_key": True},
        {"name": "metadata", "type": "text"},
        {"name": "body", "type": "text"}]}}
    mod = _exec_models(tables)  # r-stress: raised InvalidRequestError('metadata' reserved)
    assert mod is not None


def test_registry_column_does_not_break_import():
    tables = {"events": {"columns": [
        {"name": "id", "type": "integer", "primary_key": True},
        {"name": "registry", "type": "text"}]}}
    assert _exec_models(tables) is not None


def test_safe_column_name_remaps_reserved_attrs():
    assert safe_column_name("metadata") == "metadata_"
    assert safe_column_name("registry") == "registry_"


def test_reserved_column_keeps_db_name_pinned():
    # the DDL column must stay 'metadata' (attr remapped, DB name pinned positionally).
    src = render_models({"posts": {"columns": [
        {"name": "id", "type": "integer", "primary_key": True},
        {"name": "metadata", "type": "text"}]}})
    assert "metadata_ = Column('metadata'" in src or 'metadata_ = Column("metadata"' in src


def test_ordinary_names_untouched():
    # a plain column name (not reserved / not a keyword) is unchanged.
    assert safe_column_name("caption") == "caption"
    assert safe_column_name("text") == "text"   # not an ATTR collision (handled by #215)
