"""Framework main.py registers a JSON encoder for raw SQLAlchemy rows (outlook run-23, 2026-07-01).

Live-reproduced: the lane writes GET handlers like ``return {"items":
db.execute(text(...)).fetchall()}`` — raw ``Row`` objects. FastAPI's jsonable_encoder can't
serialize a Row (it falls back to ``dict(row)`` → "dictionary update sequence element #0 has
length 36; 2 is required" the moment a value is a UUID) → 500 on EVERY authed GET (run-23: all of
folders/messages/contacts/calendars/events 500'd; _framework_auth_guard just propagated it). The
generated main.py header now registers a Row/RowMapping encoder in FastAPI's ENCODERS_BY_TYPE, so
such handlers serialize BY CONSTRUCTION — no handler rewrite, no index/attr-access risk.

ENV-AGNOSTIC + LOCAL-ONLY (agent/tests/ gitignored).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.backend_skeleton import _MAIN_HEADER  # noqa: E402


def test_header_compiles_and_registers_row_encoder():
    compile(_MAIN_HEADER, "main.py", "exec")   # valid Python
    for needle in ("from fastapi.encoders import ENCODERS_BY_TYPE as _FW_ENCODERS",
                   "from sqlalchemy.engine import Row as _FWRow",
                   "_FW_ENCODERS[_FWRow] = lambda _r: dict(_r._mapping)",
                   "RowMapping as _FWRowMapping"):
        assert needle in _MAIN_HEADER, needle


def test_registered_encoder_serializes_raw_row_with_uuid():
    """The exact failure: a raw Row whose value is a 36-char UUID. Register the encoder the way
    the header does, then confirm FastAPI's jsonable_encoder serializes {"items": rows}."""
    from fastapi.encoders import ENCODERS_BY_TYPE, jsonable_encoder
    from sqlalchemy.engine import Row
    from sqlalchemy.engine.row import RowMapping
    from sqlalchemy import create_engine, text

    ENCODERS_BY_TYPE[Row] = lambda r: dict(r._mapping)
    ENCODERS_BY_TYPE[RowMapping] = lambda m: dict(m)
    try:
        eng = create_engine("sqlite://")
        with eng.connect() as c:
            rows = c.execute(text(
                "SELECT '91eb5af4-439b-496f-af91-56a1d008da15' AS id, 13 AS user_id, "
                "'Inbox' AS name")).fetchall()
            # what a lane handler returns → FastAPI runs jsonable_encoder on it
            out = jsonable_encoder({"items": rows, "total": len(rows)})
        assert out["items"][0]["id"].startswith("91eb5af4")   # UUID value serialized, not crashed
        assert out["items"][0]["user_id"] == 13
        assert out["items"][0]["name"] == "Inbox"
        assert out["total"] == 1
    finally:
        ENCODERS_BY_TYPE.pop(Row, None)
        ENCODERS_BY_TYPE.pop(RowMapping, None)


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
