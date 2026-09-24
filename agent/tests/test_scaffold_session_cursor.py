"""Scaffolded Session must expose .cursor() (outlook run-15, 2026-06-30).

Live-proven: the framework's get_db() yields a SQLAlchemy Session (the projected ORM handlers
need db.query()/db.add()), but the LLM lane routinely writes raw-DBAPI handlers —
    with db.cursor() as cur: cur.execute(sql, params)
— so EVERY such handler 500s with `AttributeError: 'Session' object has no attribute 'cursor'`
(run-15: 17 handlers, incl. GET /api/messages with real ?folder=/?focused= filtering the
projected handler can't replace). The scaffolded database.py now yields a Session subclass that
ALSO exposes .cursor(), delegating to the SAME session's DBAPI connection with dict rows by
default — so raw-style AND ORM-style handlers both work, by construction.

Tests the ACTUAL generated `_Session.cursor` from the backend_skeleton template. ENV-AGNOSTIC +
LOCAL-ONLY (agent/tests/ gitignored).
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)


def _load_session_class():
    from multi_agent.runtime.backend_skeleton import _DATABASE_PY
    ns: dict = {}
    exec(compile(_DATABASE_PY, "database.py", "exec"), ns)  # create_engine is lazy; no DB needed
    return ns["_Session"]


def _mock_session(_Session, driver, driver_connection_attr=True):
    """A bare _Session (no bind) whose .connection() returns a mock chain ending at `driver`."""
    dbapi = type("DBAPI", (), {"driver_connection": driver if driver_connection_attr else None,
                               "cursor": driver.cursor})()
    conn = type("Conn", (), {"connection": dbapi})()
    s = _Session.__new__(_Session)      # bypass Session.__init__ — no engine/bind required
    s.connection = lambda: conn         # shadow the bound-connection method with the mock
    return s


class _Driver:
    def __init__(self):
        self.calls = []
    def cursor(self, *a, **k):
        self.calls.append((a, k))
        return ("RAW_CURSOR", a, k)


def test_session_exposes_cursor_delegating_to_driver_connection():
    _Session = _load_session_class()
    assert hasattr(_Session, "cursor"), "scaffolded Session must expose .cursor()"
    drv = _Driver()
    s = _mock_session(_Session, drv)
    out = s.cursor()
    assert out[0] == "RAW_CURSOR"            # delegated to the raw DBAPI cursor
    (a, k), = drv.calls
    assert a == ()                           # no positional name passed through
    # dict rows requested by default when a psycopg lib is present (env-dependent)
    try:
        from psycopg.rows import dict_row  # noqa: F401
        assert k.get("row_factory") is not None
    except Exception:
        try:
            from psycopg2.extras import RealDictCursor  # noqa: F401
            assert k.get("cursor_factory") is not None
        except Exception:
            pass  # neither lib installed here — delegation itself still holds


def test_cursor_respects_explicit_positional_name():
    _Session = _load_session_class()
    drv = _Driver()
    s = _mock_session(_Session, drv)
    s.cursor("server_side")                  # a caller-supplied positional → no factory injected
    (a, k), = drv.calls
    assert a == ("server_side",)
    assert "row_factory" not in k and "cursor_factory" not in k


def test_cursor_respects_explicit_factory():
    _Session = _load_session_class()
    drv = _Driver()
    s = _mock_session(_Session, drv)
    s.cursor(row_factory="CUSTOM")           # explicit factory must be kept, not overwritten
    (a, k), = drv.calls
    assert k["row_factory"] == "CUSTOM"


def test_falls_back_to_proxy_when_no_driver_connection():
    # some SQLAlchemy/driver combos expose no `.driver_connection` — must use the proxy's cursor
    _Session = _load_session_class()
    drv = _Driver()
    s = _mock_session(_Session, drv, driver_connection_attr=False)
    out = s.cursor()
    assert out[0] == "RAW_CURSOR"            # used the DBAPI proxy's .cursor instead


class _PG3Driver:
    """Mimics a psycopg3 raw connection: cursor() takes row_factory and REJECTS the
    psycopg2 ``cursor_factory`` kwarg (the run-53 500)."""
    def __init__(self):
        self.calls = []
    def cursor(self, *a, **k):
        if "cursor_factory" in k:
            raise TypeError(
                "Connection.cursor() got an unexpected keyword argument 'cursor_factory'")
        self.calls.append((a, k))
        return ("PG3_CURSOR", a, k)
_PG3Driver.__module__ = "psycopg"          # psycopg3's connection module is "psycopg"


class _PG2Driver:
    """Mimics a psycopg2 raw connection: cursor() takes cursor_factory and REJECTS the
    psycopg3 ``row_factory`` kwarg."""
    def __init__(self):
        self.calls = []
    def cursor(self, *a, **k):
        if "row_factory" in k:
            raise TypeError(
                "cursor() got an unexpected keyword argument 'row_factory'")
        self.calls.append((a, k))
        return ("PG2_CURSOR", a, k)
_PG2Driver.__module__ = "psycopg2.extensions"


def test_pg3_conn_translates_lane_cursor_factory_to_row_factory():
    # FIX #131: a lane hand-wrote db.cursor(cursor_factory=RealDictCursor) (psycopg2
    # idiom) but the connection is psycopg3 -> the shim must NOT forward cursor_factory
    # (that 500s), it must translate to row_factory.
    _Session = _load_session_class()
    drv = _PG3Driver()
    s = _mock_session(_Session, drv)
    out = s.cursor(cursor_factory="RealDictCursor")   # must not raise
    assert out[0] == "PG3_CURSOR"
    (a, k), = drv.calls
    assert "cursor_factory" not in k, "psycopg2 kwarg must be stripped for a psycopg3 conn"


def test_pg2_conn_translates_lane_row_factory_to_cursor_factory():
    _Session = _load_session_class()
    drv = _PG2Driver()
    s = _mock_session(_Session, drv)
    out = s.cursor(row_factory="dict_row")            # must not raise on a psycopg2 conn
    assert out[0] == "PG2_CURSOR"
    (a, k), = drv.calls
    assert "row_factory" not in k, "psycopg3 kwarg must be stripped for a psycopg2 conn"


def test_matching_factory_kwarg_is_left_untouched():
    # a psycopg3 conn given the psycopg3 kwarg (row_factory) is fine — no translation,
    # no clobber (regression guard on the existing explicit-factory behavior).
    _Session = _load_session_class()
    drv = _PG3Driver()
    s = _mock_session(_Session, drv)
    s.cursor(row_factory="CUSTOM")
    (a, k), = drv.calls
    assert k.get("row_factory") == "CUSTOM" and "cursor_factory" not in k


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
