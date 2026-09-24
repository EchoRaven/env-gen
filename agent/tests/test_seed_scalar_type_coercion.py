"""FIX #213 — a scalar seed value whose TYPE doesn't match the column (a caption
STRING in an INTEGER count column) must be coerced, not left to nuke the table.

r16 live "No data yet": the lane's seed_data.json put a caption string in the
videos.comments field, but the schema types `comments INTEGER` (a count). On
postgres the per-table INSERT dies adapting 'a caption' → INTEGER, the rollback
drops EVERY video row, and every page reads empty (the fallback list + the real
UI both show nothing). This is the SCALAR inverse of #156 (nested→String): the
loader must coerce a numeric string to int/float and neutralize a non-numeric
string in a numeric column (→ 0) so ONE mis-typed field never loses the row.
Env-agnostic: LLM seed data routinely confuses a field's semantics.
"""

import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.backend_skeleton import render_models, render_seed_data  # noqa: E402

_TABLES = {
    "users": {"columns": [
        {"name": "id", "type": "integer", "primary_key": True},
        {"name": "email", "type": "text"}, {"name": "name", "type": "text"},
        {"name": "password_hash", "type": "text"}, {"name": "tenant_id", "type": "text"}]},
    "videos": {"columns": [
        {"name": "id", "type": "integer", "primary_key": True},
        {"name": "caption", "type": "text"},
        {"name": "likes", "type": "integer"},
        {"name": "comments", "type": "integer"},   # a COUNT — r16 put a string here
        {"name": "duration", "type": "float"}]},
}


def _coercer(tmp_path):
    """Exec the rendered loader and return its _coerce_nested_for_string_cols +
    the Video model class (dialect-independent — inspects the SA column types)."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import declarative_base, sessionmaker
    eng = create_engine(f"sqlite:///{tmp_path}/app.db")
    Base = declarative_base()
    db_mod = types.ModuleType("database")
    db_mod.Base = Base
    db_mod.SessionLocal = sessionmaker(bind=eng)
    sys.modules["database"] = db_mod
    models_mod = types.ModuleType("models")
    exec(compile(render_models(_TABLES), "models.py", "exec"), models_mod.__dict__)
    sys.modules["models"] = models_mod
    src = render_seed_data(_TABLES)
    loader = tmp_path / "seed_data.py"
    loader.write_text(src, encoding="utf-8")
    ns = {"__file__": str(loader)}
    exec(compile(src, str(loader), "exec"), ns)
    return ns["_coerce_nested_for_string_cols"], models_mod.Video, db_mod, models_mod


def _cleanup():
    for m in ("database", "models"):
        sys.modules.pop(m, None)


def test_nonnumeric_string_in_integer_column_neutralized(tmp_path):
    coerce, Video, _db, _m = _coercer(tmp_path)
    try:
        out = coerce(Video, {"caption": "hi", "comments": "a caption string"})
        # the mis-typed value becomes a valid int (0) so the row survives the INSERT
        assert out["comments"] == 0, out
        assert isinstance(out["comments"], int)
    finally:
        _cleanup()


def test_numeric_string_coerced_to_int(tmp_path):
    coerce, Video, _db, _m = _coercer(tmp_path)
    try:
        out = coerce(Video, {"likes": "257"})
        assert out["likes"] == 257 and isinstance(out["likes"], int)
    finally:
        _cleanup()


def test_numeric_string_coerced_to_float(tmp_path):
    coerce, Video, _db, _m = _coercer(tmp_path)
    try:
        out = coerce(Video, {"duration": "83.5"})
        assert abs(out["duration"] - 83.5) < 1e-6 and isinstance(out["duration"], float)
    finally:
        _cleanup()


def test_valid_scalars_and_text_untouched(tmp_path):
    coerce, Video, _db, _m = _coercer(tmp_path)
    try:
        out = coerce(Video, {"caption": "a real caption", "likes": 42, "comments": 7})
        assert out["caption"] == "a real caption"   # TEXT unchanged
        assert out["likes"] == 42 and out["comments"] == 7  # valid ints unchanged
    finally:
        _cleanup()


def test_none_stays_none(tmp_path):
    coerce, Video, _db, _m = _coercer(tmp_path)
    try:
        out = coerce(Video, {"likes": None})
        assert out["likes"] is None   # a NULL is a legitimate value, not coerced to 0
    finally:
        _cleanup()


def test_nested_into_text_still_json_serialized(tmp_path):
    # the original #156 behavior must be preserved.
    import json
    coerce, Video, _db, _m = _coercer(tmp_path)
    try:
        out = coerce(Video, {"caption": [{"a": 1}]})
        assert isinstance(out["caption"], str) and json.loads(out["caption"]) == [{"a": 1}]
    finally:
        _cleanup()
