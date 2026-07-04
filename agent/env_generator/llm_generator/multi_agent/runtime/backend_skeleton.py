"""Framework-owned BACKEND SKELETON — by-construction generation of the whole backend.

Root direction (instagram MM, 2026-06-09, user-chosen "skeleton根治"): the backend lane
writing the entire app (models + handlers + storage) is the source of STRUCTURAL
non-determinism — across runs it produces ORM / raw-SQL / file-based-JSON / fragmented
apps, and DB-centric repairs can't cover every shape. So take "by construction" all the
way (the principle already used for the DDL and the OAuth2 AS): the framework
DETERMINISTICALLY generates the complete backend FROM THE CONTRACT — ORM models from the
SchemaHub tables, all CRUD handlers from the RegistryHub endpoints, a fixed storage layer
(database.py) and auth — so the same contract always yields a byte-identical, consistent,
working, auth-enforced backend. The lane's role shrinks to AUTHORING THE CONTRACT.

This module renders the pieces; ``write_backend_skeleton`` composes them. Handlers are
projected via ``route_projector._generate_handler`` (standard CRUD MVP — feed/suggested
become generic lists; richer business logic is a later lane-override extension).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

from .database_scaffold import _columns_of, _is_constraint_pseudo_column

# ── SQL type → SQLAlchemy type ──────────────────────────────────────────────
_SA_TYPE = {
    "text": "Text", "varchar": "String", "character varying": "String", "char": "String",
    "citext": "Text", "uuid": "String", "inet": "String",
    "integer": "Integer", "int": "Integer", "int4": "Integer", "serial": "Integer",
    "bigint": "BigInteger", "int8": "BigInteger", "bigserial": "BigInteger",
    "smallint": "Integer", "int2": "Integer",
    "boolean": "Boolean", "bool": "Boolean",
    "timestamp": "DateTime", "timestamptz": "DateTime", "datetime": "DateTime",
    "timestamp without time zone": "DateTime", "timestamp with time zone": "DateTime",
    "date": "Date", "time": "Time",
    "json": "JSON", "jsonb": "JSON",
    "float": "Float", "real": "Float", "double": "Float", "double precision": "Float",
    "numeric": "Numeric", "decimal": "Numeric", "money": "Numeric",
}

# The framework-owned tenancy + identity spine (mirrors _TENANCY_SPINE_SQL). The ORM must
# model these so projected handlers can ``db.query(User)`` / resolve tenants. App tables
# named ``users``/``tenants`` MERGE their extra columns onto these bases (full_name, …).
_SPINE_USER_COLS: List[Dict[str, Any]] = [
    {"name": "id", "type": "integer", "primary_key": True},
    {"name": "email", "type": "text", "nullable": False},
    {"name": "name", "type": "text", "nullable": False, "default": "''"},
    {"name": "password_hash", "type": "text", "nullable": False},
    {"name": "tenant_id", "type": "text", "nullable": False, "fk": "tenants.id"},
    {"name": "created_at", "type": "timestamp"},
]
_SPINE_TENANT_COLS: List[Dict[str, Any]] = [
    {"name": "id", "type": "text", "primary_key": True},
    {"name": "name", "type": "text", "nullable": False, "default": "''"},
    {"name": "status", "type": "text", "nullable": False, "default": "'active'"},
    {"name": "created_at", "type": "timestamp"},
]
# AS-owned tables the app never models via the ORM (the OAuth2 AS owns them).
_SKIP_TABLES = {"oauth_clients", "oauth_authorization_codes", "oauth_tokens",
                "oauth_refresh_tokens", "oauth_codes"}

_FK_RE = re.compile(r"references\s+([A-Za-z_]\w*)\s*(?:\(\s*(\w+)\s*\)|\.\s*(\w+))",
                    re.IGNORECASE)


def _class_name(table: str) -> str:
    """``user_posts`` → ``UserPosts``; singularise a trailing plural ``s``."""
    base = re.sub(r"[^A-Za-z0-9]+", "_", str(table)).strip("_")
    parts = [p for p in base.split("_") if p]
    if parts and parts[-1].endswith("s") and not parts[-1].endswith("ss"):
        parts[-1] = parts[-1][:-1]
    return "".join(p[:1].upper() + p[1:] for p in parts) or "Model"


def _sa_type(raw: str) -> str:
    t = (raw or "").strip().lower()
    t = re.sub(r"\(.*?\)", "", t)          # varchar(255) → varchar
    t = re.sub(r"\breferences\b.*$", "", t, flags=re.IGNORECASE).strip()  # strip inline FK
    t = re.sub(r"\b(primary key|not null|unique|default.*)\b.*$", "", t, flags=re.IGNORECASE).strip()
    t = t.strip()
    for key in sorted(_SA_TYPE, key=len, reverse=True):
        if t == key or t.startswith(key):
            return _SA_TYPE[key]
    return "String"


def _fk_target(col: Dict[str, Any]) -> Optional[str]:
    """Resolve a column's FK target ``table.col`` from an explicit ``fk`` field or an
    inline ``references`` in the type."""
    fk = col.get("fk") or col.get("references")
    if isinstance(fk, str) and fk:
        return fk.replace("(", ".").replace(")", "").strip()
    m = _FK_RE.search(str(col.get("type") or ""))
    if m:
        return f"{m.group(1)}.{m.group(2) or m.group(3)}"
    return None


def _render_column(col: Dict[str, Any]) -> Optional[str]:
    name = str(col.get("name") or "").strip()
    if not name or _is_constraint_pseudo_column(col):
        return None
    args = [_sa_type(str(col.get("type") or "text"))]
    fk = _fk_target(col)
    if fk:
        args.append(f'ForeignKey("{fk}")')
    kw = []
    if col.get("primary_key") or col.get("pk"):
        kw.append("primary_key=True")
        # A TEXT/UUID primary key has NO auto-generator (unlike an Integer SERIAL PK), so an
        # INSERT that omits the id fails: NotNullViolation "null value in column \"id\"" — the
        # projected create handler does ``Model(**valid)`` WITHOUT an id, so EVERY POST create
        # 500'd on UUID/text-id schemas (outlook run-24; runs 21/23/24 all used text ids). Give
        # a text/uuid PK a Python-side UUID default so the ORM generates the id on insert, BY
        # CONSTRUCTION. Integer PKs keep SQLAlchemy autoincrement (untouched).
        if _fk_type_category(col.get("type")) in ("text", "uuid"):
            kw.append("default=lambda: str(_uuid.uuid4())")
    if col.get("nullable") is False or col.get("not_null"):
        kw.append("nullable=False")
    if col.get("unique"):
        kw.append("unique=True")
    default = col.get("default")
    if default is not None:
        d = str(default).strip()
        # server_default writes the DEFAULT into the CREATE TABLE DDL that
        # Base.metadata.create_all() emits. ``default=`` ALONE is a Python/ORM-side
        # value applied only when a row is inserted THROUGH the ORM — it never
        # reaches the DDL, so a raw-SQL insert (e.g. the AS seeding the 'default'
        # tenant, or any INSERT omitting the column) hits a bare ``NOT NULL`` and
        # Postgres rejects it. instagram_fresh aborted exactly here: tenants.status
        # had ``default='active'`` (ORM-only) → DDL was ``status TEXT NOT NULL`` with
        # no DB default → register's raw tenant insert failed the not-null constraint
        # every validation cycle. Emit BOTH: ORM-side for ORM creates, server_default
        # so the column is safe for inserts that omit it.
        if d.lower() in ("now()", "current_timestamp"):
            args.append("default=datetime.utcnow")
            kw.append("server_default=text('now()')")
        elif not (col.get("primary_key") or col.get("pk")):
            # ORM-side literal. ``true``/``false`` must become Python ``True``/``False``
            # (a bare ``default=false`` is a NameError that breaks ``import models``).
            if d.lower() in ("true", "false"):
                lit = "True" if d.lower() == "true" else "False"
            elif d.startswith(("'", '"')) or d.replace(".", "").isdigit():
                lit = d
            else:
                lit = repr(d)
            kw.append(f"default={lit}")
            # SQL literal for the DDL DEFAULT: quoted strings / numbers / bools pass
            # through; a bare word is wrapped as a quoted string literal.
            if d.startswith(("'", '"')) or d.replace(".", "").isdigit() or d.lower() in ("true", "false"):
                _sd_sql = d
            else:
                _sd_sql = "'" + d.replace("'", "''") + "'"
            kw.append(f"server_default=text({_sd_sql!r})")
    return f"    {name} = Column({', '.join(args + kw)})"


def _merge_cols(base: List[Dict[str, Any]], extra: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = {c["name"] for c in base}
    out = list(base)
    for c in extra:
        n = str(c.get("name") or "").strip()
        if n and n not in seen and not _is_constraint_pseudo_column(c):
            out.append(c)
            seen.add(n)
    return out


def _fk_type_category(raw: Any) -> str:
    """Coarse FK-consistency category for a column type string
    (integer / text / uuid / numeric / boolean / timestamp)."""
    s = re.sub(r"\(.*?\)", "", str(raw or "").strip().lower())
    s = re.sub(r"\breferences\b.*$", "", s, flags=re.IGNORECASE).strip()
    s = re.sub(r"\b(primary key|not null|unique|default.*)\b.*$", "", s,
               flags=re.IGNORECASE).strip()
    head = s.split()[0] if s.split() else "text"
    if "int" in head or "serial" in head:
        return "integer"
    if "uuid" in head:
        return "uuid"
    if any(k in head for k in ("char", "text", "string", "clob")):
        return "text"
    return head  # bool / date / numeric / ...


def _set_col_base_category(col: Dict[str, Any], category: str) -> None:
    """Set a column's base type to ``category`` while PRESERVING an inline
    ``references …`` clause when the FK lives in the type string (structured
    ``fk``/``references`` fields carry the target separately, so the bare type is
    safe to overwrite)."""
    cur = str(col.get("type") or "")
    m = _FK_RE.search(cur)
    if m and not (col.get("fk") or col.get("references")):
        col["type"] = "{} references {}({})".format(
            category, m.group(1), m.group(2) or m.group(3))
    else:
        col["type"] = category


# Framework SPINE tables are NOT in the app-table map, but their PK types are FIXED by
# construction: users.id is a SERIAL integer (database_scaffold ``users(id SERIAL PRIMARY
# KEY)``; oauth_scaffold: "users.id is an integer SERIAL PK; JWT sub == str(users.id)") and
# tenants.id is TEXT. A lane that types a FK to users.id as String/Text (run-16:
# ``message.user_id = Column(String)`` vs the integer users.id) drifts from the DB, so
# SQLAlchemy binds the value as VARCHAR → ``DatatypeMismatch`` on EVERY insert with an owner
# FK. Coercing FK columns that target a spine PK to that spine PK's known category closes it.
_SPINE_PK_CATEGORY = {"users": "integer", "tenants": "text"}


def _reconcile_fk_types_in_map(by_name: Dict[str, List[Dict[str, Any]]]) -> None:
    """Enforce FK referential TYPE-consistency across the contract's business
    tables, in place (PROPOSAL #3, L1 — the runtime-truth fix; the DDL is later
    introspected FROM these models, so making the model consistent makes the DDL
    consistent too).

    Invariant: for every column an FK targets, the target PK's type must equal the
    type of every FK column referencing it. On a CONFLICT, resolve toward the type
    the MAJORITY of referencing FKs use (surrogate ids are integer by convention)
    and ensure the target is a primary key. A target whose type ALREADY matches all
    its referencing FKs is left untouched — so a uniform text/uuid PK is never
    coerced. FKs that target a SPINE table (users/tenants — not in this app-table
    map) are skipped, so the framework ``tenants.id TEXT PRIMARY KEY`` exemption
    holds BY CONSTRUCTION (no special-casing). Domain-agnostic.

    youtube run #16: ``channels.id`` was text while every ``*.channel_id`` FK was
    integer → CREATE TABLE videos aborted (incompatible types) → postgres exit 3 →
    docker_up FAIL. This coerces ``channels.id`` → integer (the FK majority)."""
    from collections import Counter
    refs: Dict[tuple, List[Dict[str, Any]]] = {}
    for cols in by_name.values():
        for c in cols:
            tgt = _fk_target(c)
            if not tgt:
                continue
            tt, _, tc = tgt.partition(".")
            tt = tt.strip().lower()
            tc = (tc or "id").strip().lower()
            _spine = _SPINE_PK_CATEGORY.get(tt)
            if _spine is not None:
                # FK to a framework spine table (users/tenants): coerce to the spine PK's
                # FIXED category (users→integer, tenants→text) regardless of whether the
                # spine is in the app-table map — the spine PK type is not up for a vote.
                if _fk_type_category(c.get("type")) != _spine:
                    _set_col_base_category(c, _spine)
                continue
            if tt not in by_name:  # unknown external target → leave as-is
                continue
            refs.setdefault((tt, tc), []).append(c)
    for (tt, tc), refcols in refs.items():
        tgtcol = next((c for c in by_name[tt]
                       if str(c.get("name", "")).strip().lower() == tc), None)
        if tgtcol is not None and not (tgtcol.get("primary_key") or tgtcol.get("pk")):
            tgtcol["primary_key"] = True
        ref_cats = [_fk_type_category(c.get("type")) for c in refcols]
        cats = set(ref_cats) | (
            {_fk_type_category(tgtcol.get("type"))} if tgtcol is not None else set())
        if len(cats) <= 1:
            continue  # already consistent (incl. a uniform non-integer PK)
        canon = Counter(ref_cats).most_common(1)[0][0] if ref_cats else "integer"
        if tgtcol is not None and _fk_type_category(tgtcol.get("type")) != canon:
            _set_col_base_category(tgtcol, canon)
        for c in refcols:
            if _fk_type_category(c.get("type")) != canon:
                _set_col_base_category(c, canon)


def _temporal_synonym_lines(real: List[Dict[str, Any]]) -> List[str]:
    """Fix #61 (outlook run-46, live) — SQLAlchemy ``synonym`` aliases for the
    ``_at``↔``_time`` datetime-column naming drift.

    A lane routinely authors handlers against ``event.start_time`` /
    ``Event(start_time=...)`` while the framework-projected model (from the
    contract's ``start_at``) has ``start_at`` → ``AttributeError: 'Event' object
    has no attribute 'start_time'`` on read AND ``invalid keyword argument`` on
    construct → EVERY events read/write 500'd (run-46 wedged business_chain on
    GET /api/events/{id} → 500). ``synonym`` (unlike ORM ``__getattr__``) aliases
    the sibling for READ, WRITE, and CONSTRUCTOR kwargs alike, so the buggy lane
    code just works. Scoped to the temporal suffix family (the highest-frequency,
    lowest-risk drift) and only emitted when the sibling name is NOT already a
    real column — never shadows a declared column. Env-agnostic."""
    names = {str(c.get("name") or "").lower() for c in real}
    out: List[str] = []
    for c in real:
        nm = str(c.get("name") or "").strip()
        low = nm.lower()
        satype = _sa_type(str(c.get("type") or "")).lower()
        if not nm or ("date" not in satype and "time" not in satype):
            continue  # only datetime/date/time-typed columns get a temporal synonym
        sib = None
        if low.endswith("_at"):
            sib = nm[:-3] + "_time"
        elif low.endswith("_time"):
            sib = nm[:-5] + "_at"
        if sib and sib.lower() not in names and sib.lower() != low:
            names.add(sib.lower())   # a second temporal col won't re-alias the same name
            out.append(f'    {sib} = synonym("{nm}")')
    return out


def render_models(tables: Dict[str, Any]) -> str:
    """Render ``models.py`` (SQLAlchemy ORM) from the SchemaHub ``tables`` contract.
    Always emits the spine ``User``/``Tenant``; app tables generate one model each."""
    by_name: Dict[str, List[Dict[str, Any]]] = {}
    for name, table in (tables or {}).items():
        if isinstance(table, dict):
            by_name[str(name).lower()] = _columns_of(table)
    # PROPOSAL #3 (L1): make FK column types agree with the PK they reference BEFORE
    # rendering the ORM, so the models — and the DDL introspected from them — never
    # carry an unbootable integer→text FK (run #16 channels.id).
    _reconcile_fk_types_in_map(by_name)

    blocks: List[str] = []

    def emit(table: str, cols: List[Dict[str, Any]]) -> None:
        real = [c for c in cols if not _is_constraint_pseudo_column(c)]
        # Ensure exactly one primary key. If a column is already PK, keep it. Else mark
        # an existing ``id`` column PK (NOT prepend a duplicate — a second ``id =
        # Column(...)`` in the class body shadows the first → "no primary key"). Only
        # synthesise an id when there is none.
        if not any(c.get("primary_key") or c.get("pk") for c in real):
            idc = next((c for c in real if str(c.get("name", "")).lower() == "id"), None)
            if idc is not None:
                real = [{**c, "primary_key": True} if c is idc else c for c in real]
            else:
                real = [{"name": "id", "type": "integer", "primary_key": True}] + real
        lines = [c for c in (_render_column(col) for col in real) if c]
        lines += _temporal_synonym_lines(real)   # #61: _at↔_time drift aliases
        body = "\n".join(lines) or "    pass"
        blocks.append(f'class {_class_name(table)}(Base):\n'
                      f'    __tablename__ = "{table}"\n{body}')

    emit("tenants", _merge_cols(_SPINE_TENANT_COLS, by_name.get("tenants", [])))
    emit("users", _merge_cols(_SPINE_USER_COLS, by_name.get("users", [])))
    for name, cols in by_name.items():
        if name in ("users", "tenants") or name in _SKIP_TABLES:
            continue
        emit(name, cols)

    header = (
        '"""Framework-generated SQLAlchemy ORM models — by-construction from the\n'
        'SchemaHub contract. The spine (Tenant/User) mirrors the tenancy+identity tables\n'
        'the embedded OAuth2 AS owns; app models come from the declared tables. Do not\n'
        'hand-edit: this is regenerated deterministically from the contract."""\n'
        "import uuid as _uuid\n"
        "from datetime import datetime\n\n"
        "from sqlalchemy import (Column, Integer, BigInteger, String, Text, Boolean,\n"
        "                        DateTime, Date, Time, Float, Numeric, JSON, ForeignKey,\n"
        "                        text)\n"
        "from sqlalchemy.orm import synonym\n"
        "from database import Base\n\n\n"
    )
    return header + "\n\n\n".join(blocks) + "\n"


# ── database.py (fixed storage layer) ───────────────────────────────────────
_DATABASE_PY = '''"""Framework-generated storage layer — engine + session + Base. Fixed by
construction (the DATABASE_URL is the SQLAlchemy psycopg3 URL from the env)."""
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session

_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://sandbox:sandbox@database:5432/app")
engine = create_engine(_URL, pool_pre_ping=True, future=True)


class _Session(Session):
    """SQLAlchemy Session that ALSO exposes .cursor(), so handlers written in the RAW
    DBAPI style (``with db.cursor() as cur: cur.execute(sql, params)``) work against the
    SAME session/transaction the ORM handlers use. Without it a raw-style handler raises
    ``AttributeError: 'Session' object has no attribute 'cursor'`` -> 500 (a very common
    LLM handler shape). Rows default to DICTS so ``fetchall()`` yields JSON-serialisable
    objects (psycopg3 ``dict_row`` / psycopg2 ``RealDictCursor``); an explicit factory or
    positional name the caller passes is respected."""

    def cursor(self, *args, **kwargs):
        _c = self.connection().connection
        raw = getattr(_c, "driver_connection", None) or _c
        if not args and "row_factory" not in kwargs and "cursor_factory" not in kwargs:
            try:
                from psycopg.rows import dict_row
                kwargs["row_factory"] = dict_row
            except Exception:
                try:
                    from psycopg2.extras import RealDictCursor
                    kwargs["cursor_factory"] = RealDictCursor
                except Exception:
                    pass
        return raw.cursor(*args, **kwargs)


SessionLocal = sessionmaker(
    bind=engine, class_=_Session, autoflush=False, autocommit=False, future=True)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
'''


def _models_meta(tables: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Build the ``route_projector._orm_models``-shaped dict
    (``{table: {cls, cols, fks}}``) DIRECTLY from the contract, so handler projection
    needs no models.py round-trip."""
    by_name: Dict[str, List[Dict[str, Any]]] = {}
    for name, table in (tables or {}).items():
        if isinstance(table, dict):
            by_name[str(name).lower()] = _columns_of(table)
    meta: Dict[str, Dict[str, Any]] = {}

    def add(table: str, cols: List[Dict[str, Any]]) -> None:
        names, fks, types, uniq = [], {}, {}, []
        have_pk = False
        pk_name, pk_type = None, "integer"
        for c in cols:
            if _is_constraint_pseudo_column(c):
                continue
            n = str(c.get("name") or "").strip()
            if not n:
                continue
            names.append(n)
            # SQLAlchemy type NAME per column (Integer/String/Text/…), the shape
            # route_projector expects in ``meta["types"]`` — WITHOUT this the by-id path
            # param + search both fall back to int/all-columns: a STRING/UUID primary key
            # (outlook messages.id = String) typed the {id} param ``int`` → a UUID path 422'd.
            types[n] = _sa_type(str(c.get("type") or ""))
            # FIX #74: per-column UNIQUE (from the contract) — the demo-content
            # concentrator de-dupes these on clone so a copied subject/name/slug does not
            # collide with the row it was cloned from.
            if c.get("unique"):
                uniq.append(n)
            if c.get("primary_key") or c.get("pk"):
                have_pk = True
                pk_name = n
                pk_type = str(c.get("type") or "integer")
            tgt = _fk_target(c)
            if tgt:
                fks[n] = tgt.split(".")[0]
        if not have_pk and "id" not in names:
            names.insert(0, "id")
            types.setdefault("id", "Integer")   # synthesized SERIAL id
        if pk_name is None:
            pk_name = "id"  # synthesized SERIAL id
        meta[table] = {"cls": _class_name(table), "cols": names, "fks": fks,
                       "pk": pk_name, "pk_type": pk_type, "types": types,
                       "unique": uniq}

    add("tenants", _merge_cols(_SPINE_TENANT_COLS, by_name.get("tenants", [])))
    add("users", _merge_cols(_SPINE_USER_COLS, by_name.get("users", [])))
    for name, cols in by_name.items():
        if name in ("users", "tenants") or name in _SKIP_TABLES:
            continue
        add(name, cols)
    return meta


_MAIN_HEADER = '''"""Framework-generated FastAPI backend — by-construction from the contract.

Every business handler below is PROJECTED from the RegistryHub endpoint contract over the
generated ORM models (standard CRUD). The OAuth2 AS (/oauth/*, /auth/register|login) is
framework-owned; auth is enforced on every /api/ business route by the middleware. Do
not hand-edit: regenerated deterministically from the contract."""
import os

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import or_
from sqlalchemy.orm import Session

from database import Base, engine, get_db
from auth_dependency import get_current_user
import models  # noqa: F401  (registers all ORM tables on Base.metadata)
from models import *  # noqa: F401,F403


def _fw_uid(user):
    """Authenticated caller's id, coerced to the owner column's likely type. Auth deps
    commonly carry the JWT `sub` as a STRING; comparing it raw against an INTEGER owner
    column makes postgres raise `operator does not exist: integer = character varying`
    → every owner-scoped read/write 500s (outlook run-39, live). Digits → int; else as-is
    (text/uuid ids untouched)."""
    _v = getattr(user, "id", None)
    if _v is None and isinstance(user, dict):
        _v = user.get("id") or user.get("sub")
    if _v is None:
        _v = user
    try:
        return int(_v)
    except (TypeError, ValueError):
        return _v

Base.metadata.create_all(bind=engine)


def _ensure_temporal_alias_columns():
    """Fix #63 (outlook run-47, live): a lane authored RAW SQL against the _time
    naming (SELECT * / WHERE start_time / ORDER BY start_time / INSERT ... start_time)
    while the contract column is start_at → 'psycopg.errors.UndefinedColumn: column
    "start_time" does not exist' → every such raw-SQL read 500'd (the ORM #61 synonym
    can't reach a SQL string). For each temporal <x>_at/<x>_time column whose sibling
    name does NOT physically exist, add a Postgres GENERATED-ALWAYS-STORED mirror
    column so the lane's raw SQL works AS-WRITTEN for reads (SELECT * returns the
    sibling key too); the mirror is read-only, but raw INSERTs of the sibling are
    shadowed by the projected ORM write (which uses the real column). Postgres-only,
    idempotent (ADD COLUMN IF NOT EXISTS), best-effort — never blocks boot. Coexists
    with the ORM synonym (this is a DB column outside the ORM model)."""
    from sqlalchemy import text as _text
    try:
        if engine.dialect.name != "postgresql":
            return
    except Exception:
        return
    _TEMPORAL = ("timestamp", "timestamptz", "date", "time")
    try:
        with engine.begin() as _c:
            rows = _c.execute(_text(
                "SELECT table_name, column_name, data_type FROM information_schema.columns "
                "WHERE table_schema = 'public'")).fetchall()
            by_table = {}
            for t, col, dt in rows:
                by_table.setdefault(t, {})[col] = str(dt or "").lower()
            for t, cols in by_table.items():
                for col, dt in list(cols.items()):
                    if not any(k in dt for k in _TEMPORAL):
                        continue
                    low = col.lower()
                    if low.endswith("_at"):
                        sib = col[:-3] + "_time"
                    elif low.endswith("_time"):
                        sib = col[:-5] + "_at"
                    else:
                        continue
                    if sib.lower() in {c.lower() for c in cols}:
                        continue  # sibling already a real/mirror column
                    cols[sib] = dt  # don't double-add within this pass
                    try:
                        _c.execute(_text(
                            'ALTER TABLE "%s" ADD COLUMN IF NOT EXISTS "%s" %s '
                            'GENERATED ALWAYS AS ("%s") STORED' % (t, sib, dt, col)))
                    except Exception:
                        pass
    except Exception:
        pass  # best-effort; a missing mirror only re-surfaces the lane bug, never blocks boot


_ensure_temporal_alias_columns()

# Populate empty business tables with realistic demo data so the UI is not blank
# on first load (framework-owned; idempotent — skips tables that already have rows).
try:
    from seed_data import seed_if_empty
    seed_if_empty()
except Exception:
    pass  # seeding is best-effort; never block boot

# JSON serialization for RAW SQLAlchemy rows. A lane GET handler that returns the result of
# ``db.execute(text(...)).fetchall()`` yields raw ``Row`` objects; FastAPI's jsonable_encoder
# cannot serialize those — it falls back to ``dict(row)`` which raises "dictionary update
# sequence element #0 has length N; 2 is required" the moment a row value is a UUID/text (36
# chars) → 500 on EVERY such endpoint (outlook run-23: ALL authed GETs 500'd here). Register a
# Row/RowMapping encoder so those handlers serialise BY CONSTRUCTION — no handler rewrite, no
# risk to index/attr access. Best-effort (never blocks boot).
try:
    from fastapi.encoders import ENCODERS_BY_TYPE as _FW_ENCODERS
    from sqlalchemy.engine import Row as _FWRow
    _FW_ENCODERS[_FWRow] = lambda _r: dict(_r._mapping)
    try:
        from sqlalchemy.engine.row import RowMapping as _FWRowMapping
        _FW_ENCODERS[_FWRowMapping] = lambda _m: dict(_m)
    except Exception:
        pass
except Exception:
    pass

app = FastAPI(title="app")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])

# Framework OAuth2 AS — /oauth/*, /.well-known/*, /auth/register, /auth/login.
try:
    from oauth_store import OAuthStore
    from jwt_manager import JWTManager
    from oauth_routes import build_router as _as_build_router
    _as_router = _as_build_router(OAuthStore(), JWTManager())
    app.include_router(_as_router)
    # #64 (outlook run-48/49, live): the generated frontend api.js prepends /api
    # to EVERY call, so its login/register hit /api/auth/login|register. Mount the
    # SAME AS router a second time under /api so those entry points exist BY
    # CONSTRUCTION (include_router is the canonical mechanism — robust, unlike
    # reusing route objects). The extra /api/oauth/* copies are harmless: the auth
    # guard walls anything under /api/ that isn't explicitly public, and nothing
    # calls them. The guard marks /api/auth/login|register public so the UI login
    # works (it 401'd for hours: auth_ok=False + login-wall while /auth/login 200s).
    app.include_router(_as_router, prefix="/api")
except Exception:  # pragma: no cover
    pass


@app.get("/health")
def health():
    return {"status": "healthy"}
'''

# LANE-OVERRIDE HOOK: custom_routes.py is the ONE backend file the lane owns —
# genuinely custom business logic (beyond contract-projected CRUD) goes there.
# The framework NEVER writes or overwrites it.
#
# OVERRIDE SCOPE (outlook run #7): the custom router is included BEFORE the projected
# handlers so it OVERRIDES them (Starlette matches the first-registered route) — but
# ONLY for NON-STANDARD endpoints. The projected handlers for STANDARD CRUD (a bare
# collection GET/POST, an item GET/PATCH/PUT/DELETE by trailing {param}, and the /me
# singleton) are correct-by-construction over the real ORM columns AND wrapped in
# try/except. A lane custom CRUD handler, by contrast, routinely uses WRONG column
# names (run #7: POST /api/messages with sender/date/is_starred vs the model's
# from_name/sent_at/is_flagged) and has NO error handling → 500 → business_endpoints
# fails → the run wedges (the lane often can't even self-heal it). So for standard
# CRUD the SAFE projected handler must win; custom_routes overrides ONLY the endpoints
# the projector mis-handles — the /{id}/<action> verbs (rsvp/reply/forward/…) it
# treats as a wrong create. That keeps the run #2 fixes (/auth/me via the projector's
# own /me branch; /{id}/rsvp via custom) while removing the buggy-CRUD-handler 500s.
# custom_routes imports only database/models/auth_dependency (never main) → no
# circular-import risk from the early include.
_CUSTOM_ROUTES_INCLUDE = '''
# Registered business RESOURCE names (table names + singular/plural variants) — used to
# tell a NESTED child-resource route (/<parent>/{id}/tasks) the projector handles from a
# nested ACTION verb (/<parent>/{id}/like) it does not. Injected from the contract.
_NESTED_CHILD_RESOURCES = set(__NESTED_CHILD_RESOURCES__)
# #77 (outlook run-64): resources the framework POSITIVELY marked per-user-PRIVATE-TO-READ
# (a cross-user GET-denial chain proved it) AND whose model has a SINGLE, UNAMBIGUOUS owner
# FK — so the PROJECTED read is guaranteed correctly owner-scoped. For a GET on one of these
# the projected scoped read MUST win: a lane custom GET can only re-widen the leak (run-64: an
# unscoped lane GET /api/messages/{id} overrode the scoped projected read → cross-user leak →
# isolation depended on the LANE fixing its own read → 75-min wall). A PUBLIC feed (never
# flagged) and a multi-principal DM table (sender+recipient — the projected single-owner read
# would 404 the recipient) are DELIBERATELY excluded, so the lane still wins for them.
_OWNER_SCOPED_RESOURCES = set(__OWNER_SCOPED_RESOURCES__)


def _custom_route_overrides_projected(method, path):
    """A lane custom route may OVERRIDE the projected handler only for NON-standard-CRUD
    endpoints — i.e. an action verb after a path param (/x/{id}/rsvp), search, or any
    other novel shape. Standard CRUD (bare collection, item-by-{param}, /me, AND nested
    child-RESOURCE CRUD /<parent>/{id}/<child>[/{cid}]) keeps the safe projected handler,
    so a buggy lane CRUD handler can't 500-shadow it."""
    segs = [s for s in str(path).strip("/").split("/") if s]
    if segs and segs[0] == "api":
        segs = segs[1:]
    if not segs:
        return True
    last = segs[-1]
    n_params = sum(1 for s in segs if s.startswith("{") or s.startswith(":"))
    last_is_param = last.startswith("{") or last.startswith(":")
    # standard CRUD shapes → projected wins (return False = do NOT let custom override):
    # EXCEPT a GET on these shapes: the projected list / item-by-id handler is NOT owner-
    # scoped (owner_scoped_reads is an opt-in the lane often omits), so a per-user-PRIVATE
    # resource LEAKS other users' rows AND dropping the lane's custom GET discards its
    # isolation remediation (outlook run-9: GET /api/messages/{id} cross-user leak wedged 7
    # cycles — the lane's correct scoped read kept being dropped). Let the lane's GET WIN
    # here (it carries the domain-correct scoping; a public feed's lane GET is unscoped and
    # still wins -> behaviour unchanged for public resources). WRITES stay projected:
    # create/update/delete are already owner-safe + shape-consistent (the buggy-lane-CRUD
    # concern is for mutations), and projected NESTED reads keep their parent-owner isolation.
    _is_get = method.upper() == "GET"
    if len(segs) == 1 and not last_is_param:          # collection: /messages
        # #77: a framework-scoped PRIVATE resource keeps the PROJECTED scoped list — a lane
        # custom GET can only re-leak. Public/unflagged resources: lane still wins.
        if _is_get and segs[0].lower() in _OWNER_SCOPED_RESOURCES:
            return False
        return _is_get
    if last_is_param and n_params == 1:               # item by id: /messages/{id}
        # resource = the segment BEFORE the trailing {id} (segs[-2]) so a namespaced path
        # (/api/v1/messages/{id} → 'messages') is still covered, not the version prefix.
        _res = segs[-2].lower() if len(segs) >= 2 else segs[0].lower()
        if _is_get and _res in _OWNER_SCOPED_RESOURCES:
            return False                              # scoped projected read wins (no leak)
        return _is_get
    if last == "me":                                  # current-user singleton: /auth/me
        # The projector emits a /me handler (route_projector: path.endswith("/me")) ONLY for
        # endpoints it actually receives — and business_endpoints() EXCLUDES the auth/oauth
        # control surface (/auth/*, /api/auth/*, /oauth/*). So a /me UNDER that prefix (the
        # canonical /api/auth/me "current user") has NO projected handler; dropping the custom
        # one leaves the endpoint NOWHERE → 404, wedging every business_chain auth step + the
        # frontend's user-load (outlook run-27 M3, live-reproduced: GET /api/auth/me → 404 while
        # custom_routes defines it). Keep the custom route there; elsewhere (/api/users/me,
        # bare /me) the projector DID emit a handler, so projected still wins.
        return len(segs) >= 2 and segs[0] in ("auth", "oauth")
    # NESTED child-RESOURCE CRUD: /<parent>/{pid}/<child>  (list/create) or
    # /<parent>/{pid}/<child>/{cid}  (item) where <child> is a REAL registered resource —
    # the projector emits a functional parent-scoped handler, so projected wins. A nested
    # ACTION verb (<child> NOT a resource, e.g. /posts/{id}/like) falls through to custom.
    # (smoke-proj 2026-06-29: the lane's custom POST /api/projects/{id}/tasks called a
    # non-existent jwt_manager.verify_token → 500; the projected nested-create is correct.)
    if (len(segs) in (3, 4)
            and (segs[1].startswith("{") or segs[1].startswith(":"))
            and not (segs[2].startswith("{") or segs[2].startswith(":"))
            and ((len(segs) == 3 and not last_is_param)
                 or (len(segs) == 4 and last_is_param))
            and segs[2].lower() in _NESTED_CHILD_RESOURCES):
        return False
    return True                                       # actions / search / novel → custom wins

try:
    from custom_routes import router as _custom_router
    # Keep only the custom routes that legitimately override (or add) — drop the ones
    # duplicating a standard-CRUD endpoint so the safe projected handler serves those.
    _custom_router.routes = [
        _r for _r in list(getattr(_custom_router, "routes", []))
        if _custom_route_overrides_projected(
            next(iter(getattr(_r, "methods", []) or ["GET"])), getattr(_r, "path", ""))
    ]
    app.include_router(_custom_router)
except ImportError as _custom_imp:
    # ONLY "custom_routes does not exist" is benign. A NESTED broken import (the lane's
    # `import asyncpg` with the package missing) also lands here — and silently dropping
    # the WHOLE router 404'd every custom-only endpoint while chains stayed green on the
    # projected handlers (outlook run-29: auth/me 404 → login-wall, invisible for hours).
    if getattr(_custom_imp, "name", None) not in (None, "custom_routes"):
        import logging
        logging.getLogger("custom_routes").error(
            "custom_routes has a BROKEN IMPORT (%s) — ALL custom routes are disabled; "
            "add the missing package to pyproject dependencies", _custom_imp)
except Exception as _custom_exc:  # pragma: no cover — a broken override must not kill boot
    import logging
    logging.getLogger("custom_routes").warning("custom_routes failed to load: %s", _custom_exc)

# CURRENT-USER FILL-IN: the frontend's session restore (ProtectedRoute) calls the
# auth-prefixed "current user" endpoint, but NOTHING guarantees it exists — the projector
# EXCLUDES the /auth|/oauth control surface (business_endpoints), the coverage gate excludes
# it too, and the lane only sometimes writes it (outlook run-27 + run-29: /api/auth/me 404 →
# every protected page bounced to /login → hollow app / login-wall). If neither the lane nor
# the projector registered a /me under auth/oauth, register the canonical one here — the row
# is fully determined by the platform's own auth (get_current_user), so this is deterministic
# control-surface scaffolding, not business logic. Fill-in only; a lane-authored /me wins.
try:
    _fw_me_present = {getattr(_r, "path", "") for _r in app.routes}
    def _fw_auth_me(user=Depends(get_current_user)):
        if not hasattr(user, "__dict__") and not isinstance(user, dict):
            return {"item": {"id": user}}        # dependency returned a bare user id
        _item = {}
        for _c in ("id", "email", "name", "username", "display_name", "avatar_url",
                   "tenant_id", "created_at"):
            _v = user.get(_c) if isinstance(user, dict) else getattr(user, _c, None)
            if _v is not None:
                _item[_c] = _v.isoformat() if hasattr(_v, "isoformat") else _v
        return {"item": _item}
    for _fw_p in ("/api/auth/me", "/auth/me"):
        if _fw_p not in _fw_me_present:
            app.get(_fw_p)(_fw_auth_me)
    # (#64 login/register under /api are mounted at the AS-include site above via
    # include_router(prefix="/api") — the canonical, robust mechanism; a route-
    # object-reuse fill-in here silently failed to register in the full app,
    # run-49.)
    # TENANTS-LIST FILL-IN (outlook run-37, live): the login template's TenantPicker calls
    # GET /api/v1/tenants on MOUNT (pre-auth; /api/v1/* is public infra in the middleware) —
    # but the projector excludes the control surface and the lane rarely writes it → 404 on
    # every page with the picker, and a picker that can't validate its tenant can WEDGE the
    # whole login (auth_ok=False + login_wall at M1). Serve the tenants table (default-row
    # fallback) — deterministic control-surface scaffolding, only-if-absent.
    def _fw_tenants_list(db=Depends(get_db)):
        try:
            import models as _fw_m
            _T = getattr(_fw_m, "Tenant", None)
            if _T is not None:
                _rows = db.query(_T).limit(50).all()
                _items = [{"id": getattr(_r, "id", None),
                           "name": getattr(_r, "name", None) or getattr(_r, "id", None)}
                          for _r in _rows]
                if _items:
                    return {"items": _items, "tenants": _items}
        except Exception:
            pass
        _d = [{"id": "default", "name": "default"}]
        return {"items": _d, "tenants": _d}
    for _fw_p in ("/api/v1/tenants",):
        if _fw_p not in _fw_me_present:
            app.get(_fw_p)(_fw_tenants_list)
except Exception as _fw_me_exc:  # pragma: no cover — fill-in must never kill boot
    import logging
    logging.getLogger("custom_routes").warning("auth/me fill-in failed: %s", _fw_me_exc)
'''

_MAIN_FOOTER = '''

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("API_PORT", "8081")))
'''


def render_skeleton_main(endpoints: List[Mapping[str, Any]], tables: Dict[str, Any]) -> str:
    """Render the full ``main.py``: fixed skeleton + auth-enforcement middleware + ALL
    business handlers projected from the contract (static routes before param routes)."""
    from .route_projector import (_generate_handler, _norm_path, _resource_model, _truthy,
                                  _owner_fk, _TARGET_FK_NAMES)
    from .backend_scaffold import _AUTH_MIDDLEWARE

    meta = _models_meta(tables)
    # Per-user-PRIVATE tables (owner_scoped_reads in the contract metadata): their reads
    # are owner-scoped BY CONSTRUCTION here, exactly as route_projector + heal_pipeline do.
    # This skeleton is the PRIMARY main.py generator and runs FIRST — if it emitted an
    # unscoped read, the delivery-time projector would see the route already present and
    # skip its scoped re-projection (live: smoke-notes-exp3 leaked despite the table being
    # flagged). So BOTH projection sites must apply the same per-table decision. Keys are
    # lowercased to match _models_meta / _resource_model.
    scoped_read_tables = {
        str(name).lower()
        for name, t in (tables or {}).items()
        if isinstance(t, Mapping) and (
            _truthy((t.get("metadata") or {}).get("owner_scoped_reads"))
            or _truthy(t.get("owner_scoped_reads")))
    }
    seen: set = set()
    static_blocks: List[str] = []
    param_blocks: List[str] = []
    for i, ep in enumerate(endpoints or []):
        method = str(ep.get("method", "")).upper()
        path = str(ep.get("path", ""))
        if not method or not path.startswith("/api/"):
            continue
        if (method, _norm_path(path)) in seen:
            continue
        seen.add((method, _norm_path(path)))
        emeta = ep.get("metadata") if isinstance(ep.get("metadata"), Mapping) else {}
        auth = bool(ep.get("auth_required", emeta.get("auth_required", True)))
        # Pass the declared response_key through so single-item endpoints get {item}
        # (not the collection {items,total}); mirrors route_projector.project_missing_routes.
        _eschema = ep.get("schema") if isinstance(ep.get("schema"), Mapping) else {}
        response_key = str(ep.get("response_key") or _eschema.get("response_key")
                           or emeta.get("response_key") or "").strip()
        _rm = _resource_model(path, meta)
        _owner_scoped = bool(_rm and str(_rm[0]).lower() in scoped_read_tables)
        block = _generate_handler(method, path, auth, meta, i, response_key, _owner_scoped, owner_scoped_tables=scoped_read_tables)
        (param_blocks if "{" in path else static_blocks).append(block)

    # _AUTH_MIDDLEWARE references ``app`` + imports jwt/JSONResponse/jwt_manager; it is
    # inserted after the app is constructed and before the routes (static-first).
    mid = _AUTH_MIDDLEWARE.strip("\n")
    # Inject the registered resource names so the custom-route override filter can tell a
    # nested child-RESOURCE route (projector-handled → projected wins) from a nested ACTION
    # verb (lane custom wins). Names + singular/plural variants to match a path segment.
    _nested_resources: set = set()
    for _t in (tables or {}):
        _n = str(_t).strip().lower()
        if _n:
            _nested_resources |= {_n, _n + "s", _n.rstrip("s")}
    # #77: resources whose PROJECTED read is guaranteed correctly owner-scoped — the framework
    # flagged them private-to-read (scoped_read_tables) AND their model has a SINGLE, unambiguous
    # user principal. A table with a SECOND user-principal column (a DM's recipient_id/to_user_id
    # beside sender_id) has an OR privacy boundary the single-owner projected read can't express
    # (the recipient would 404), so it is EXCLUDED → the lane's OR-correct read still wins. Injected
    # so _custom_route_overrides_projected drops a lane GET that would re-widen the scoped read.
    _owner_scoped_resources: set = set()
    for _t in scoped_read_tables:
        _tm = meta.get(_t) or meta.get(str(_t).lower()) or {}
        if not _owner_fk(_tm):
            continue  # no owner FK → projected read can't scope → do not drop the lane read
        _fks = _tm.get("fks") or {}
        _cols = _tm.get("cols") or []
        _principals = {c for c, tgt in _fks.items() if str(tgt).lower() == "users"}
        _principals |= {c for c in _cols if str(c).lower() in _TARGET_FK_NAMES}
        if len(_principals) > 1:
            continue  # multi-principal (DM sender+recipient) → ambiguous → keep lane-wins
        _n = str(_t).strip().lower()
        if _n:
            _owner_scoped_resources |= {_n, _n + "s", _n.rstrip("s")}
    custom_include = _CUSTOM_ROUTES_INCLUDE.replace(
        "__NESTED_CHILD_RESOURCES__", repr(sorted(_nested_resources))
    ).replace(
        "__OWNER_SCOPED_RESOURCES__", repr(sorted(_owner_scoped_resources)))
    # _CUSTOM_ROUTES_INCLUDE precedes the projected blocks so a lane custom_routes
    # handler OVERRIDES the projected one for the same METHOD+path (first-registered
    # wins in Starlette) — the documented lane-override intent, which the old footer
    # placement silently inverted.
    body = (_MAIN_HEADER + "\n\n" + mid + "\n\n\n"
            + custom_include + "\n\n\n"
            + "\n\n\n".join(static_blocks + param_blocks) + _MAIN_FOOTER)
    return body


# ── fixed infra (no [build-system] → no hatchling wheel build; deps-only install) ──
_PYPROJECT = '''[project]
name = "app-backend"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
  "fastapi>=0.115",
  "uvicorn>=0.30",
  "sqlalchemy>=2.0",
  "psycopg[binary]>=3.1",
  "pyjwt[crypto]>=2.8",
  "cryptography>=42",
  "python-multipart>=0.0.9",
]
'''

# DEPENDENCY RECONCILIATION (outlook run-29, 2026-07-01): the lane wrote
# ``import asyncpg`` in custom_routes.py but the framework re-asserts _PYPROJECT
# byte-identically each skeleton pass → asyncpg never installed → the
# ``from custom_routes import router`` include raised ModuleNotFoundError → the
# except-ImportError swallow dropped ALL custom routes SILENTLY (auth/me 404 →
# login-wall/hollow verdict; chains stayed green on projected handlers so nothing
# noticed). Render pyproject from the base list UNIONED with the third-party
# modules the lane's backend source actually imports, so a lane picking its own
# driver/library is installable BY CONSTRUCTION. Unknown import names map to the
# same pip name (asyncpg/httpx/redis/...); known aliases are translated.
_IMPORT_TO_PIP = {
    "jwt": None, "psycopg": None, "fastapi": None, "uvicorn": None,   # already in base
    "sqlalchemy": None, "cryptography": None, "multipart": None,
    "psycopg2": "psycopg2-binary", "yaml": "pyyaml", "PIL": "pillow",
    "dotenv": "python-dotenv", "bs4": "beautifulsoup4", "Crypto": "pycryptodome",
    "dateutil": "python-dateutil", "OpenSSL": "pyopenssl", "jose": "python-jose",
    "passlib": "passlib[bcrypt]", "starlette": None, "pydantic": None,  # fastapi deps
}
_TOP_IMPORT_RE = re.compile(r"^\s*(?:import|from)\s+([A-Za-z_]\w*)", re.M)


def _lane_third_party_imports(be_dir: Any) -> List[str]:
    """pip requirement strings for third-party modules the backend source imports but the
    base _PYPROJECT does not carry. Local modules (sibling .py files) and stdlib are
    skipped; best-effort (empty on any failure)."""
    out: List[str] = []
    try:
        be = Path(be_dir)
        if not be.is_dir():
            return out
        local = {f.stem for f in be.glob("*.py")}
        stdlib = getattr(sys, "stdlib_module_names", frozenset())
        seen: set = set()
        for f in sorted(be.glob("*.py")):
            try:
                src = f.read_text(encoding="utf-8")
            except Exception:
                continue
            for name in _TOP_IMPORT_RE.findall(src):
                if name in seen or name in local or name in stdlib:
                    continue
                seen.add(name)
                if name in _IMPORT_TO_PIP:
                    pip = _IMPORT_TO_PIP[name]
                    if pip:                      # None → already in the base list
                        out.append(pip)
                else:
                    out.append(name)             # asyncpg / httpx / redis / aiohttp / ...
    except Exception:
        return []
    return sorted(set(out))


def render_pyproject(be_dir: Any) -> str:
    """_PYPROJECT + any lane-imported third-party deps (union, never removes)."""
    extras = _lane_third_party_imports(be_dir)
    if not extras:
        return _PYPROJECT
    lines = "".join(f'  "{d}",\n' for d in extras)
    # anchor on the dependencies-list terminator (`\n]\n`), NOT a bare `]\n` — that
    # would match the `[project]` table header first and corrupt the TOML.
    return _PYPROJECT.replace("\n]\n", "\n" + lines + "]\n", 1)

_DOCKERFILE = '''FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim
WORKDIR /app
COPY pyproject.toml ./
RUN uv pip install --system -r pyproject.toml
COPY *.py *.json ./
COPY reset.sh /reset.sh
RUN chmod +x /reset.sh
EXPOSE 8081
CMD ["python", "main.py"]
'''
# ``COPY *.py *.json ./`` ships the agent-authored seed_data.json into the image — with
# only ``*.py`` the DATA file NEVER reached the container, so the loader fell back to the
# embedded _SEED in every run regardless of what the lane authored (outlook run-31, live:
# authored demo@example.com JSON on disk, container had no seed_data.json → fallback users
# → demo login 401 + sparse screens). A .json glob with NO match fails the docker build, so
# the infra writers below guarantee a seed_data.json ALWAYS exists (empty ``{}`` if the
# lane hasn't authored one yet — falsy, so the loader still uses its fallback; written
# ONLY-IF-ABSENT so authored content is never clobbered and the agent isn't anchored).


def _ensure_seed_json(be: Path) -> None:
    p = be / "seed_data.json"
    if not p.exists():
        p.write_text("{}\n", encoding="utf-8")

_RESET_SH = '''#!/usr/bin/env bash
# Framework-generated business-data reset (best-effort; keeps tenancy/identity spine).
set -euo pipefail
python - <<'PY'
try:
    from database import SessionLocal, Base, engine
    from sqlalchemy import text
    keep = {"tenants", "users", "oauth_clients", "oauth_authorization_codes"}
    with SessionLocal() as db:
        for t in reversed(Base.metadata.sorted_tables):
            if t.name not in keep:
                db.execute(text(f'DELETE FROM "{t.name}"'))
        db.commit()
    print("reset: business tables cleared")
except Exception as exc:
    print(f"reset skipped: {exc}")
PY
'''

_SCHEMAS_PY = '''"""Framework-generated placeholder. The projected handlers return plain dicts;
Pydantic response models are not required for the standard-CRUD skeleton."""
'''


def write_backend_build_infra(output_dir: Any) -> Dict[str, Any]:
    """Write ONLY the STATIC, contract-independent backend build infra
    (Dockerfile / pyproject.toml / reset.sh).

    These are what `docker build` needs and they do NOT depend on the ORM /
    handlers, so they can be emitted UPFRONT (alongside docker-compose) — long
    before the full contract exists. Without this the backend build context is
    empty when validation first runs, and agents improvise a BROKEN Dockerfile
    (run #6: the orchestrator hand-wrote a `pip install poetry` Dockerfile →
    docker build exit 2, even though the project is uv/pyproject). The full
    `write_backend_skeleton` later re-asserts these byte-identically and adds
    models/handlers. Idempotent."""
    be = Path(output_dir) / "app" / "backend"
    be.mkdir(parents=True, exist_ok=True)
    written: Dict[str, str] = {}
    _ensure_seed_json(be)
    for name, content in (("pyproject.toml", render_pyproject(be)),
                          ("Dockerfile", _DOCKERFILE),
                          ("reset.sh", _RESET_SH)):
        (be / name).write_text(content, encoding="utf-8")
        written[name] = str(be / name)
    return {"written": list(written), "backend_dir": str(be)}


# ── Deterministic SEED DATA (by-construction populated UI on first load) ──────
# The spec asks for demo data so the home/feed/lists are populated on first load,
# but the lane rarely produces it and nothing enforced it → blank app. The
# framework owns the backend, so it owns the seed too: project a seed_data.py from
# the contract that, on startup, fills each EMPTY business table with FK-valid,
# realistic rows + login-able demo users. Domain-agnostic (value by column-name
# heuristic, never placeholder/sequential words the seed_audit flags).
import hashlib as _seed_hashlib

# MUST stay byte-identical to oauth_store.PASSWORD_SALT / _hash_password (a drift
# here silently breaks seeded logins). Seeded demo users log in with "password".
_SEED_PASSWORD = "password"
_SEED_PASSWORD_SALT = "app_sandbox_salt_2024"


def _seed_password_hash() -> str:
    return _seed_hashlib.sha256(
        (_SEED_PASSWORD + _SEED_PASSWORD_SALT).encode("utf-8")).hexdigest()


_SEED_PEOPLE = ["Ava Chen", "Liam Patel", "Noah Kim", "Mia Garcia", "Ethan Brooks", "Sofia Rossi"]
# Neutral, domain-agnostic labels for name/title columns — read fine as a task title, a
# document name, a board, a product, or a message subject (NOT video/media-platform shaped).
_SEED_TITLES = ["Getting Started", "Project Overview", "Weekly Summary",
                "Quarterly Plan", "Team Update", "Field Report"]
_SEED_SENTENCES = ["A short overview of what this is and how it works.",
                   "Everything you need to get started, one step at a time.",
                   "A few quick highlights and notes from this week.",
                   "Thanks for following along — more to come.",
                   "A brief walkthrough with notes you can follow."]
_SEED_OMIT = object()

# Tables/columns that denote a PERSON → their name/label seeds from _SEED_PEOPLE, not the
# generic _SEED_TITLES. Without this, a message ``from_name`` or a ``contacts.name`` reads
# "Getting Started" — an email from a project title (outlook MM, 2026-06-29). Domain-agnostic.
_PERSON_TABLES = frozenset({
    "users", "contacts", "members", "authors", "people", "persons", "customers",
    "attendees", "guests", "participants", "employees", "profiles", "friends",
    "followers", "senders", "recipients", "students", "teachers", "staff", "agents",
    "subscribers", "clients", "owners", "hosts", "organizers", "speakers", "leads"})
_PERSON_NAME_HINTS = (
    "from_name", "sender", "recipient", "to_name", "author", "contact", "customer",
    "member", "assignee", "guest", "attendee", "host", "organizer", "participant",
    "person", "full_name", "first_name", "last_name", "display_name", "given_name",
    "family_name", "owner_name", "user_name")


def _is_person_name(col: str, table: str) -> bool:
    """True if this name/label column should hold a PERSON name (people pool) rather than a
    neutral title (a sender, contact, author, attendee… or a plain name on a people table)."""
    n = (col or "").lower()
    if any(h in n for h in _PERSON_NAME_HINTS):
        return True
    return n in ("name", "display_name", "full_name") and (table or "").lower() in _PERSON_TABLES


def _seed_number(col: str, i: int):
    """A BELIEVABLE deterministic number for a numeric column, by name. The old single
    formula gave 42–9842 for EVERYTHING, so a folder shipped ``unread_count=1773`` (outlook
    MM). Engagement metrics stay large; ordinary counts/quantities are small; ratings 1–5;
    money/duration/year are shaped. Domain-agnostic; integers only (never floats — the
    column may be Integer and a float would coerce/truncate or error)."""
    n = (col or "").lower()
    if "rating" in n:
        return (i % 5) + 1                                  # 1..5
    if "year" in n:
        return 2018 + (i % 7)                               # 2018..2024
    if any(k in n for k in ("view", "like", "subscriber", "follower", "play", "stream",
                            "download", "impression", "share", "watch", "reach", "visit")):
        return (i + 1) * 137 % 4000 + 120                   # engagement: ~120..4100
    if any(k in n for k in ("price", "amount", "cost", "revenue", "balance", "fee", "salary", "budget")):
        return (i + 1) * 10 + 9                             # 19, 29, 39… (whole units)
    if any(k in n for k in ("duration", "seconds", "length", "runtime", "elapsed")):
        return (i + 1) * 53 % 600 + 30                      # 30..630
    if "score" in n:
        return (i * 17 + 30) % 100                          # 0..99
    if any(k in n for k in ("position", "rank", "order", "index", "priority", "page", "sort", "step")):
        return i + 1                                        # 1,2,3…
    return (i * 7 + 3) % 40                                 # generic count/qty/total/unread: 3..39
_SEED_PERSON_NAME = _is_person_name  # alias kept for readability at call sites


# Image/media column words. A string column whose name contains one of these holds a
# picture URL → the loader backfills a missing one with a deterministic placeholder so an
# agent-authored row that omits its avatar/photo still renders an image, not an empty box.
_IMAGE_WORDS = ("avatar", "thumbnail", "banner", "cover", "photo", "image",
                "picture", "headshot", "poster", "logo")


def _is_image_col(col: str) -> bool:
    """True if a STRING column name denotes an image URL (avatar/photo/thumbnail/…). Excludes
    numeric look-alikes (image_count, image_width) so a placeholder URL is never put in a
    number column (which would 500 the insert)."""
    n = (col or "").lower()
    if any(k in n for k in ("count", "total", "num", "width", "height", "size", "_id")):
        return False
    return any(w in n for w in _IMAGE_WORDS)


def _seed_slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(s).lower()) or "demo"


def _pk_type_cat(t: Optional[str]) -> str:
    """Coarse PK type category, domain-agnostic: integer (SERIAL) / uuid / text."""
    s = str(t or "").lower()
    if "uuid" in s or "guid" in s:
        return "uuid"
    if any(k in s for k in ("int", "serial", "bigint", "smallint", "number")):
        return "integer"
    if any(k in s for k in ("char", "text", "string", "str", "slug", "varchar", "clob")):
        return "text"
    return "integer"  # unknown → assume SERIAL (the common case)


def _seed_pk_value(table: str, n: int, pk_type: Optional[str]):
    """Deterministic PK value for parent row ``n`` (0-based) when its PK is NOT an integer
    SERIAL — so a child FK can reference the exact same key. Integer PKs return None (the
    caller leaves them to SERIAL / index+1)."""
    cat = _pk_type_cat(pk_type)
    if cat == "uuid":
        import uuid as _uuid
        return str(_uuid.uuid5(_uuid.NAMESPACE_DNS, f"{table}-{n + 1}"))
    if cat == "text":
        return f"{_seed_slug(table)[:12]}-{n + 1}"
    return None


# Owner-ish FK column bases (``user_id``/``owner_id``/``created_by``…) that, when no
# table of their own name exists, point at the ``users`` table — the row's owner.
_OWNER_FK_SYNONYMS = frozenset({
    "user", "owner", "author", "creator", "sender", "recipient", "account",
    "member", "assignee", "host", "organizer"})


def _owner_fk_vocabulary() -> frozenset:
    """The EXACT set of column names the READ side treats as the row's actor/owner or a
    user-target (route_projector._OWNER_FK_NAMES + _TARGET_FK_NAMES) — the single source
    of truth, imported so seed + owner-scoped reads can never drift apart. Falls back to
    a local copy only if the import fails (keeps seeding robust in isolation)."""
    try:
        from .route_projector import _OWNER_FK_NAMES, _TARGET_FK_NAMES
        return frozenset(_OWNER_FK_NAMES) | frozenset(_TARGET_FK_NAMES)
    except Exception:
        return frozenset({
            "user_id", "author_id", "owner_id", "creator_id", "created_by",
            "follower_id", "sender_id", "from_user_id", "actor_id", "uploaded_by",
            "posted_by", "account_id", "following_id", "followee_id", "followed_id",
            "recipient_id", "to_user_id", "target_user_id", "addressee_id"})


def _seed_infer_fk(col: str, known_tables) -> Optional[str]:
    """Infer the PARENT table for a conventionally-named FK column that carries NO
    explicit ``ForeignKey``. Lanes routinely write ``user_id = Column(Integer)`` with
    no FK constraint, so ``_models_meta`` records no fk for it → the seed generator
    omits the column → the owner is NULL → owner-scoped reads return ZERO rows → every
    authenticated page renders blank even though auth + endpoints work (outlook MM,
    2026-06-29: avachen logged in but saw 0 folders/messages/events).

    ★ Owner consistency is BY CONSTRUCTION, not heuristic ★ — step (1) recognises the
    owner/actor column using the SAME vocabulary the READ side scopes on
    (``route_projector._owner_fk`` → ``_OWNER_FK_NAMES``/``_TARGET_FK_NAMES``). So for
    EVERY table the reads owner-scope, the seed fills the very column the reads filter
    on → owner reads are never empty; and a table whose owner column the reads do NOT
    recognise is not owner-scoped at all (all rows visible) → also never empty. The seed
    thus fills a SUPERSET of what reads scope on, for any schema/new env.

    Remaining steps are domain-agnostic conventions for NON-owner FKs (so child data is
    valid/non-blank too): ``tenant_id`` → tenants; ``<x>_id`` → the table named <x>
    (singular OR plural); an owner-synonym base with no table of its own → users.
    The caller passes ``fks.get(c) or _seed_infer_fk(c, …)`` so an EXPLICIT ForeignKey
    always wins. Conservative: a base matching no table and no owner vocabulary
    (``external_id``, ``parent_id`` with no ``parents`` table) → None (DB default/NULL)."""
    n = (col or "").lower().strip()
    known = set(known_tables or ())
    # (1) actor/owner or user-target column — the canonical read-side vocabulary.
    if n in _owner_fk_vocabulary():
        return "users" if "users" in known else None
    # (2) tenant-scoping column → the implicit 'default' tenant.
    if n in ("tenant_id", "tenant"):
        return "tenants"
    if n in ("created_by", "updated_by", "owned_by"):
        return "users" if "users" in known else None
    if not n.endswith("_id"):
        return None
    base = n[:-3]
    if not base:
        return None
    # (3) plain parent FK by the <x>_id convention → the table named <x>.
    cands = [base, base + "s", base + "es"]
    if base.endswith("y"):
        cands.append(base[:-1] + "ies")
    if base.endswith("s"):
        cands.append(base[:-1])
    for c in cands:
        if c in known:
            return c
    # (4) owner-ish synonym base with no table of its own → users (belt & suspenders for
    # owner names not yet in the canonical list; harmless if reads don't scope on it).
    if base in _OWNER_FK_SYNONYMS and "users" in known:
        return "users"
    return None


def _seed_cell(col: str, table: str, i: int, fk_table: Optional[str], counts: Dict[str, int],
               pk_name: Optional[str] = None, pk_type: Optional[str] = None,
               pk_types: Optional[Dict[str, str]] = None):
    """A realistic, deterministic value for one column of seed row ``i`` — or
    ``_SEED_OMIT`` to leave it (PK/timestamp/unknown → DB default/null). Value is
    chosen by COLUMN NAME first (domain-agnostic), then type-ish fallbacks.
    ``pk_types`` maps each parent table to its PK type so a FK is seeded with the parent's
    ACTUAL key type (integer SERIAL 1..N, or a deterministic text/uuid key)."""
    n = col.lower()
    if fk_table:
        if fk_table == "tenants":
            return "default"
        m = max(1, int(counts.get(fk_table, 1)))
        idx = i % m
        _ppk = _seed_pk_value(fk_table, idx, (pk_types or {}).get(fk_table))
        return _ppk if _ppk is not None else idx + 1  # text/uuid parent key, else SERIAL 1..N
    if pk_name is not None and col == pk_name:
        _own = _seed_pk_value(table, i, pk_type)
        return _own if _own is not None else _SEED_OMIT  # deterministic text/uuid PK, else SERIAL
    if n in ("id",):
        return _SEED_OMIT  # PK → SERIAL (fallback when pk metadata isn't threaded)
    if n == "password_hash":
        return _seed_password_hash()
    if n in ("created_at", "updated_at") or n.endswith("_at"):
        return _SEED_OMIT  # DB default now()/nullable — avoid datetime coercion
    if n == "email" or n.endswith("_email"):  # email, from_email, sender_email, to_email…
        return _seed_slug(_SEED_PEOPLE[i % len(_SEED_PEOPLE)]) + "@example.com"
    if n in ("username", "handle") or n.endswith("_handle") or n.endswith("_username"):
        return "@" + _seed_slug(_SEED_PEOPLE[i % len(_SEED_PEOPLE)])
    if (n.endswith("_url") or n in ("url", "avatar", "thumbnail", "banner", "image", "photo")
            or any(k in n for k in ("avatar", "thumbnail", "banner", "image_url", "photo", "video_url", "audio_url"))):
        size = "200/200" if ("avatar" in n or "photo" in n) else "640/360"
        return f"https://picsum.photos/seed/{table}{i}/{size}"
    if any(k in n for k in ("description", "bio", "summary", "about", "caption",
                            "content", "body", "message", "text", "comment")):
        return _SEED_SENTENCES[i % len(_SEED_SENTENCES)]
    if (n in ("name", "title", "display_name", "full_name", "label", "subject",
              "headline", "topic", "heading") or n.endswith("_name") or n.endswith("_title")):
        # a person's name (sender/contact/author/attendee, or a name on a people table) reads
        # as a PERSON; everything else (folder/board/event/document titles) as a neutral title.
        pool = _SEED_PEOPLE if _is_person_name(n, table) else _SEED_TITLES
        return pool[i % len(pool)]
    if any(k in n for k in ("count", "total", "amount", "quantity", "number", "duration",
                            "seconds", "length", "runtime", "position", "rank", "order",
                            "index", "priority", "score", "rating", "price", "cost",
                            "revenue", "balance", "fee", "salary", "budget", "view", "like",
                            "subscriber", "follower", "play", "stream", "download",
                            "impression", "share", "watch", "reach", "visit", "year")):
        return _seed_number(n, i)
    if n in ("status", "state"):
        return "active"
    if n == "role":
        return "member"
    if n in ("kind", "type", "category"):
        # no enum/CHECK metadata in the contract → a NEUTRAL non-null token, never a
        # domain literal like 'video'/'short' (which is wrong for non-video apps).
        return "standard"
    if n == "visibility":
        return "public"
    if n.startswith("is_") or n.endswith("_flag") or n.endswith("_enabled") or n.startswith("has_") or n in ("active", "enabled", "is_read"):
        return (i % 2 == 0)
    return _SEED_OMIT


def _seed_topo_order(meta: Dict[str, Dict[str, Any]]) -> List[str]:
    """Order tables so every FK target is seeded before its referrers (Kahn);
    self-refs and unresolved cycles are broken by emitting remaining tables in a
    stable order (their back-edge FK rows reference earlier ids / 'default')."""
    names = [t for t in meta.keys() if t != "tenants"]  # tenants seeded implicitly
    deps = {t: set() for t in names}
    for t in names:
        for _col, ref in (meta[t].get("fks") or {}).items():
            if ref in deps and ref != t:
                deps[t].add(ref)
    order, placed = [], set()
    while len(placed) < len(names):
        ready = [t for t in names if t not in placed and deps[t] <= placed]
        if not ready:  # cycle — break by taking the lowest-unplaced-dep table
            remaining = [t for t in names if t not in placed]
            ready = [min(remaining, key=lambda x: len(deps[x] - placed))]
        for t in sorted(ready):
            order.append(t)
            placed.add(t)
    return order


def _build_seed_rows(tables: Dict[str, Any]):
    """Build the deterministic default seed ``{table: [rows]}`` + the metadata the loader
    needs (class map, per-table owner column, whether the user PK is integer). Shared by
    render_seed_data (embedded fallback) and render_seed_json (the agent-editable artifact)."""
    meta = _models_meta(tables)
    order = _seed_topo_order(meta)
    n_users = 5
    counts: Dict[str, int] = {"users": n_users, "tenants": 1}
    for t in order:
        counts.setdefault(t, 6)
    pk_types = {t: meta[t].get("pk_type") for t in meta}
    seed: Dict[str, List[Dict[str, Any]]] = {}
    full_order = (["users"] if "users" in meta else []) + [t for t in order if t != "users"]
    known_tables = set(meta.keys()) | {"tenants"}
    for t in full_order:
        cols = [c for c in (meta[t].get("cols") or []) if c]
        fks = meta[t].get("fks") or {}
        _pk_name, _pk_type = meta[t].get("pk"), meta[t].get("pk_type")
        rows: List[Dict[str, Any]] = []
        for i in range(counts.get(t, 6)):
            row: Dict[str, Any] = {}
            for c in cols:
                _fk = fks.get(c) or _seed_infer_fk(c, known_tables)
                v = _seed_cell(c, t, i, _fk, counts,
                               pk_name=_pk_name, pk_type=_pk_type, pk_types=pk_types)
                if v is not _SEED_OMIT:
                    row[c] = v
            if t == "users":
                row.setdefault("password_hash", _seed_password_hash())
                row.setdefault("tenant_id", "default")
            if row:
                rows.append(row)
        if rows:
            seed[t] = rows
    classmap = {t: meta[t]["cls"] for t in seed}
    # Per-table owner column via the SAME resolver the READ side scopes on, so the loader
    # can backfill a missing owner → owner-scoped reads are never empty even if an
    # agent-authored seed omits it. Only when the user PK is integer (SERIAL 1..N) — a
    # text/uuid owner can't be a cycled int, so the author must supply it there.
    owner_col: Dict[str, str] = {}
    owner_int = _pk_type_cat((meta.get("users") or {}).get("pk_type")) not in ("uuid", "text")
    if owner_int:
        try:
            from .route_projector import _owner_fk
            for t in seed:
                if t == "users":
                    continue
                ofk = _owner_fk(meta.get(t, {}))
                if ofk:
                    owner_col[t] = ofk
        except Exception:
            owner_col = {}
    # String image columns per table → the loader backfills a missing one with a
    # deterministic placeholder URL (multimodal safety net: an agent-authored row that
    # omits its avatar/photo still renders an image, not an empty box). Type-gated to
    # String/Text so a placeholder URL is never written into a number column.
    image_col: Dict[str, List[str]] = {}
    for t in seed:
        types = meta.get(t, {}).get("types") or {}
        imgs = [c for c in (meta[t].get("cols") or [])
                if _is_image_col(c) and str(types.get(c, "")) in ("String", "Text")]
        if imgs:
            image_col[t] = imgs
    # FIX #74 (DEMO-CONTENT CONCENTRATION) — metadata the loader's concentrator needs.
    # Owner-scoped CHILD FKs: a FK column on an owner-scoped table that points to ANOTHER
    # owner-scoped table (messages.folder_id -> folders). When a donor row is cloned into
    # the demo user, these MUST be remapped to the demo user's OWN child rows (the donor's
    # folder belongs to the donor). Baked from the CONTRACT (explicit fks + the SAME
    # name-inference the row builder uses), because a lane's ``folder_id = Column(Integer)``
    # carries no runtime ForeignKey, so ``__table__.foreign_keys`` is unreliable.
    owner_child_fk: Dict[str, Dict[str, str]] = {}
    if owner_int:
        owner_tables = set(owner_col.keys())
        for t in seed:
            if t == "users" or t not in owner_tables:
                continue
            my_owner = owner_col.get(t)
            resolved: Dict[str, str] = dict(meta.get(t, {}).get("fks") or {})
            for c in (meta.get(t, {}).get("cols") or []):
                if c not in resolved:
                    inf = _seed_infer_fk(c, known_tables)
                    if inf:
                        resolved[c] = inf
            child: Dict[str, str] = {}
            for col, tgt in resolved.items():
                if col == my_owner or tgt == t:
                    continue  # owner col itself / self-ref stays as the donor's value
                if tgt in owner_tables:
                    child[col] = tgt
            if child:
                owner_child_fk[t] = child
    # PK name + coarse category (integer/uuid/text) per table: the concentrator drops an
    # integer PK (SERIAL assigns) and MINTS a fresh unique value for a uuid/text PK.
    pk_meta: Dict[str, List[str]] = {
        t: [meta.get(t, {}).get("pk") or "id",
            _pk_type_cat(meta.get(t, {}).get("pk_type"))] for t in seed}
    # String/Text UNIQUE columns per table — de-duped on clone to dodge collisions.
    unique_cols: Dict[str, List[str]] = {}
    for t in seed:
        types = meta.get(t, {}).get("types") or {}
        us = [c for c in (meta.get(t, {}).get("unique") or [])
              if str(types.get(c, "")) in ("String", "Text")]
        if us:
            unique_cols[t] = us
    return seed, classmap, owner_col, image_col, owner_child_fk, pk_meta, unique_cols


def render_seed_json(tables: Dict[str, Any]) -> str:
    """The seed DATA as JSON (``{table: [rows]}``) — a SEPARATE artifact the backend agent
    OWNS and rewrites with domain-aware, semantically-consistent values (realistic names,
    real subjects, and derived counters like ``unread_count`` that MATCH the rows it wrote,
    rather than the framework's domain-blind defaults). The loader (seed_data.py) prefers
    this file; this default just guarantees the app is never blank before the agent runs."""
    import json as _json
    seed, *_rest = _build_seed_rows(tables)
    return _json.dumps(seed, indent=2, ensure_ascii=False)


def audit_agent_seed(backend_dir) -> Dict[str, Any]:
    """Quality-audit the AGENT-authored ``app/backend/seed_data.json`` (the data file the
    backend agent owns). A populated, REALISTIC preview is part of the deliverable, but the
    agent may (a) never author the file → the app falls back to the bland embedded ``_SEED``
    default, or (b) author it but leave the framework's PLACEHOLDER titles ("Getting
    Started"/…) instead of real domain values. Returns ``{authored, placeholder_tables,
    issues}`` so the heal pipeline can NUDGE the backend lane (P0 task) — the bland fallback
    keeps the app FUNCTIONAL, so this is never a hard delivery block. Best-effort; never raises."""
    import json as _json
    out: Dict[str, Any] = {"authored": False, "placeholder_tables": [], "issues": []}
    try:
        p = Path(backend_dir) / "seed_data.json"
        if not p.exists():
            out["issues"].append(
                "no app/backend/seed_data.json — the app is seeded by the bland framework "
                "default. AUTHOR realistic domain data per the SEED DATA instructions.")
            return out
        out["authored"] = True
        data = _json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return out
        _ph = {t.lower() for t in _SEED_TITLES}
        for table, rows in data.items():
            if not isinstance(rows, list) or not rows:
                continue
            hits = 0
            for r in rows:
                if isinstance(r, dict) and any(
                        isinstance(v, str) and v.strip().lower() in _ph for v in r.values()):
                    hits += 1
            # flag only a CLEAR majority of placeholder rows (the framework default is 100%),
            # so an occasional coincidental match in otherwise-real data is not flagged
            if hits >= 2 and hits * 2 > len(rows):
                out["placeholder_tables"].append(table)
        if out["placeholder_tables"]:
            out["issues"].append(
                "seed_data.json still uses the framework PLACEHOLDER titles in "
                f"{out['placeholder_tables']} — replace with realistic, domain-specific "
                "values (real email subjects, names, descriptions), not 'Getting Started' etc.")
    except Exception as exc:  # never raise into the pipeline
        out["issues"].append(f"seed audit error: {type(exc).__name__}: {exc}")
    return out


def render_seed_data(tables: Dict[str, Any], bootstrap_spec: Optional[List[Dict[str, Any]]] = None) -> str:
    """Project seed_data.py — the framework-owned LOADER. It loads the DATA from the
    sibling ``seed_data.json`` (authored by the backend agent) when present + non-empty,
    else the embedded deterministic ``_SEED`` (so the app is never blank). For each EMPTY
    table it inserts the rows in FK order, idempotently, hashing the demo password for
    users and backfilling a missing owner FK so owner-scoped reads are never empty. Demo
    users log in with 'password'.

    ``bootstrap_spec`` (FIX #72) is the canonical per-user named-row spec detected from the
    lane's handlers (``Folder.name == "Sent"``). After seeding, the loader ensures EVERY
    existing user has each such row — idempotent, so an agent seed that omits the canonical
    folder no longer 500s reply/forward/delete on a real, correct handler."""
    seed, classmap, owner_col, image_col, owner_child_fk, pk_meta, unique_cols = _build_seed_rows(tables)
    bootstrap_spec = list(bootstrap_spec or [])
    body = (
        '"""Seed LOADER (framework-owned). The DATA lives in the sibling seed_data.json,\n'
        'authored by the backend agent with domain-aware, FK-valid, semantically-consistent\n'
        'rows (derived counters match the data). This module reads that JSON (falling back\n'
        'to the embedded _SEED default so the UI is never blank), then for each EMPTY table\n'
        'inserts its rows in FK order — hashing the demo password for users, backfilling a\n'
        'missing owner FK so owner-scoped reads are never empty, and backfilling a missing\n'
        'image URL so media screens are not full of empty boxes. Demo users log in with\n'
        'password "password". Idempotent."""\n'
        "import json, hashlib\n"
        "from pathlib import Path\n"
        "from database import SessionLocal\n"
        "import models\n\n"
        f"_ORDER = {list(seed.keys())!r}\n"
        f"_CLASS = {classmap!r}\n"
        f"_OWNER_COL = {owner_col!r}\n"
        f"_IMAGE_COL = {image_col!r}\n"
        f"_OWNER_CHILD_FK = {owner_child_fk!r}\n"   # FIX #74: {{table: {{fk_col: child_table}}}}
        f"_PK = {pk_meta!r}\n"                       # FIX #74: {{table: [pk_name, category]}}
        f"_UNIQUE = {unique_cols!r}\n"               # FIX #74: {{table: [unique string cols]}}
        f"_DEMO_FLOOR = 8\n"                          # FIX #74: min rows the demo user owns
        f"_PASSWORD_SALT = {_SEED_PASSWORD_SALT!r}\n"
        f"_SEED = {seed!r}\n"
        f"_USER_BOOTSTRAP = {bootstrap_spec!r}\n\n\n"
        "def _ensure_canonical_rows():\n"
        "    # FIX #72: every user (seeded OR freshly-registered) must have the canonical\n"
        "    # per-user named rows the lane's handlers require (a 'Sent' folder / a\n"
        "    # kind=='trash' folder), or reply/forward/delete 500 on a correct handler and\n"
        "    # the business_chain gate wedges. Idempotent + best-effort: runs on EVERY boot\n"
        "    # (incl. the already-seeded fingerprint path) so an agent seed that omits the\n"
        "    # canonical row is healed; a per-row failure never breaks the app.\n"
        "    if not _USER_BOOTSTRAP:\n"
        "        return\n"
        "    users_cls = getattr(models, _CLASS.get('users') or 'User', None)\n"
        "    if users_cls is None:\n"
        "        return\n"
        "    db = SessionLocal()\n"
        "    try:\n"
        "        try:\n"
        "            uids = [u.id for u in db.query(users_cls).all()]\n"
        "        except Exception:\n"
        "            return\n"
        "        for s in _USER_BOOTSTRAP:\n"
        "            t = s.get('table'); owner = s.get('owner_col')\n"
        "            mcol = s.get('match_col'); lit = s.get('literal')\n"
        "            row = dict(s.get('row') or {})\n"
        "            cls = getattr(models, _CLASS.get(t) or '', None)\n"
        "            if cls is None or not owner or not mcol:\n"
        "                continue\n"
        "            ocol = getattr(cls, owner, None); mattr = getattr(cls, mcol, None)\n"
        "            if ocol is None or mattr is None:\n"
        "                continue\n"
        "            for uid in uids:\n"
        "                try:\n"
        "                    if db.query(cls).filter(ocol == uid, mattr == lit).first() is not None:\n"
        "                        continue\n"
        "                    vals = {owner: uid}; vals.update(row); vals[mcol] = lit\n"
        "                    db.add(cls(**{k: v for k, v in vals.items() if hasattr(cls, k)}))\n"
        "                    db.commit()\n"
        "                except Exception:\n"
        "                    db.rollback()\n"
        "    finally:\n"
        "        db.close()\n\n\n"
        "def _load_rows():\n"
        "    try:\n"
        "        data = json.loads(Path(__file__).with_name('seed_data.json').read_text(encoding='utf-8'))\n"
        "        if isinstance(data, dict) and any(data.values()):\n"
        "            return data\n"
        "    except Exception:\n"
        "        pass\n"
        "    return _SEED\n\n\n"
        "def _applied_fingerprint(db):\n"
        "    from sqlalchemy import text as _text\n"
        "    try:\n"
        "        db.execute(_text('CREATE TABLE IF NOT EXISTS _seed_meta (k TEXT PRIMARY KEY, v TEXT)'))\n"
        "        db.commit()\n"
        "        row = db.execute(_text(\"SELECT v FROM _seed_meta WHERE k = 'fingerprint'\")).fetchone()\n"
        "        return row[0] if row else None\n"
        "    except Exception:\n"
        "        db.rollback()\n"
        "        return None\n\n\n"
        "def _store_fingerprint(db, fp):\n"
        "    from sqlalchemy import text as _text\n"
        "    try:\n"
        "        db.execute(_text(\"DELETE FROM _seed_meta WHERE k = 'fingerprint'\"))\n"
        "        db.execute(_text(\"INSERT INTO _seed_meta (k, v) VALUES ('fingerprint', :v)\"), {'v': fp})\n"
        "        db.commit()\n"
        "    except Exception:\n"
        "        db.rollback()\n\n\n"
        "def _reset_seeded_tables(db):\n"
        "    # The seed SOURCE changed (the agent authored/updated seed_data.json after an\n"
        "    # earlier boot already seeded the fallback): re-apply it AUTHORITATIVELY. TRUNCATE\n"
        "    # ... RESTART IDENTITY CASCADE puts the tables back to first-boot state so the\n"
        "    # authored rows' explicit ids/FKs land exactly as written; runtime-created rows go\n"
        "    # with it (validation flows re-register/re-create per run, and the app's intended\n"
        "    # ship-state IS the seed). Falls back to child-first DELETE where TRUNCATE is\n"
        "    # unsupported (sqlite).\n"
        "    from sqlalchemy import text as _text\n"
        "    present = [t for t in _ORDER if getattr(models, _CLASS.get(t, ''), None) is not None]\n"
        "    if not present:\n"
        "        return\n"
        "    try:\n"
        "        db.execute(_text('TRUNCATE ' + ', '.join('\"%s\"' % t for t in present)\n"
        "                         + ' RESTART IDENTITY CASCADE'))\n"
        "        db.commit()\n"
        "    except Exception:\n"
        "        db.rollback()\n"
        "        for t in reversed(present):\n"
        "            try:\n"
        "                db.query(getattr(models, _CLASS[t])).delete()\n"
        "                db.commit()\n"
        "            except Exception:\n"
        "                db.rollback()\n\n\n"
        "def _sync_sequences(db):\n"
        "    # Fix #56 (outlook run-41, live): the seed inserts rows with EXPLICIT integer\n"
        "    # ids but the SERIAL/IDENTITY sequence still sits at its start — and the\n"
        "    # fingerprint re-seed's TRUNCATE ... RESTART IDENTITY resets it back to 1 —\n"
        "    # so EVERY post-seed INSERT collides with a seeded id ('duplicate key value\n"
        "    # violates unique constraint users_pkey' on /auth/register until the sequence\n"
        "    # crawls past the seeded range; api_smoke auth wedged 6/6). Advance each\n"
        "    # serial-backed PK sequence to MAX(col)+1. Postgres-only (sqlite's INTEGER\n"
        "    # PRIMARY KEY auto-assigns max+1 natively); text/uuid PKs have no sequence\n"
        "    # (pg_get_serial_sequence returns NULL -> the row filter skips). Idempotent,\n"
        "    # best-effort: a failure never blocks seeding.\n"
        "    from sqlalchemy import text as _text\n"
        "    try:\n"
        "        if db.get_bind().dialect.name != 'postgresql':\n"
        "            return\n"
        "    except Exception:\n"
        "        return\n"
        "    for t in _ORDER:\n"
        "        cls = getattr(models, _CLASS.get(t, ''), None)\n"
        "        if cls is None:\n"
        "            continue\n"
        "        try:\n"
        "            pk_cols = [c.name for c in cls.__table__.primary_key.columns]\n"
        "        except Exception:\n"
        "            continue\n"
        "        for c in pk_cols:\n"
        "            try:\n"
        "                db.execute(_text(\n"
        "                    'SELECT setval(seq, (SELECT COALESCE(MAX(' + '\"%s\"' % c + '), 0) + 1'\n"
        "                    ' FROM ' + '\"%s\"' % t + '), false)'\n"
        "                    ' FROM (SELECT pg_get_serial_sequence(:t, :c) AS seq) s'\n"
        "                    ' WHERE seq IS NOT NULL'), {'t': t, 'c': c})\n"
        "                db.commit()\n"
        "            except Exception:\n"
        "                db.rollback()\n\n\n"
        "def _concentrate_demo_content():\n"
        "    # FIX #74: the FIRST user (by id) is the DEMO identity every gate + the first\n"
        "    # page-load uses. Lanes routinely spread rows evenly across many users, so the\n"
        "    # demo owns only a few → inbox/feed/calendar look EMPTY on first load even though\n"
        "    # the app works. For each owner-scoped CONTENT table where the demo owns\n"
        "    # < _DEMO_FLOOR rows, CLONE existing rows INTO the demo (fresh PK, owner=demo,\n"
        "    # owner-scoped child FKs remapped to the demo's OWN child rows, unique string\n"
        "    # cols de-duped) until the floor is met. Never re-owns/removes a donor row, so\n"
        "    # cross-user tests keep their data. Runs AFTER _ensure_canonical_rows so the\n"
        "    # demo's canonical child rows exist for the remap. Floor-gated → idempotent\n"
        "    # across boots; FK-safe; per-row best-effort (a failed clone rolls back only\n"
        "    # itself). Skips text/uuid-user apps (no _OWNER_COL) and structural per-user\n"
        "    # tables (those with canonical bootstrap rows — folders/labels).\n"
        "    if not _OWNER_COL:\n"
        "        return\n"
        "    users_cls = getattr(models, _CLASS.get('users') or 'User', None)\n"
        "    if users_cls is None or not hasattr(users_cls, 'id'):\n"
        "        return\n"
        "    _structural = set(s.get('table') for s in (_USER_BOOTSTRAP or []) if s.get('table'))\n"
        "    def _discrim(ccls):\n"
        "        # the child's KIND/discriminator column (folders.kind='inbox'/'sent') so a\n"
        "        # cloned row is filed under the demo's SAME-KIND child, not round-robin.\n"
        "        try:\n"
        "            cols = [c.name for c in ccls.__table__.columns]\n"
        "        except Exception:\n"
        "            return None\n"
        "        for cand in ('kind', 'type', 'category', 'label', 'name'):\n"
        "            if cand in cols:\n"
        "                return cand\n"
        "        return None\n"
        "    db = SessionLocal()\n"
        "    try:\n"
        "        try:\n"
        "            demo = db.query(users_cls).order_by(users_cls.id.asc()).first()\n"
        "        except Exception:\n"
        "            return\n"
        "        demo_uid = getattr(demo, 'id', None) if demo is not None else None\n"
        "        if demo_uid is None:\n"
        "            return\n"
        "        for t in _ORDER:  # FK targets (child tables) first → parent remap can use them\n"
        "            owner = _OWNER_COL.get(t)\n"
        "            if not owner or t in _structural:\n"
        "                continue\n"
        "            cls = getattr(models, _CLASS.get(t, ''), None)\n"
        "            if cls is None:\n"
        "                continue\n"
        "            ocol = getattr(cls, owner, None)\n"
        "            pk_name, pk_cat = (_PK.get(t) or ['id', 'integer'])\n"
        "            if ocol is None or not pk_name or not hasattr(cls, pk_name):\n"
        "                continue\n"
        "            try:\n"
        "                demo_rows = db.query(cls).filter(ocol == demo_uid).all()\n"
        "                have = len(demo_rows)\n"
        "                if have >= _DEMO_FLOOR:\n"
        "                    continue\n"
        "                donors = db.query(cls).filter(ocol != demo_uid).all()\n"
        "            except Exception:\n"
        "                continue\n"
        "            if not donors:\n"
        "                continue  # single-user seed: demo already owns all there is\n"
        "            _per = dict()\n"
        "            for _d in donors:\n"
        "                _dk = getattr(_d, owner, None)\n"
        "                _per[_dk] = _per.get(_dk, 0) + 1\n"
        "            if not _per or max(_per.values()) <= 1:\n"
        "                # SINGLETON per-user table (settings/profile — <=1 row/user): NOT feed\n"
        "                # content. Cloning it makes look-alikes, or under UNIQUE(user_id) every\n"
        "                # clone collides → per-boot fail-churn. Leave it alone.\n"
        "                continue\n"
        "            child_map = _OWNER_CHILD_FK.get(t, {})\n"
        "            # per child table: kind->demo-PKs map, all-demo-PKs list, child-PK->kind map\n"
        "            demo_by_kind, demo_any, kind_of = dict(), dict(), dict()\n"
        "            for _fk, ctab in child_map.items():\n"
        "                ccls = getattr(models, _CLASS.get(ctab, ''), None)\n"
        "                cowner = _OWNER_COL.get(ctab)\n"
        "                cpk = (_PK.get(ctab) or [None])[0]\n"
        "                bykind, anyids, kof = dict(), [], dict()\n"
        "                if (ccls is not None and cowner and cpk\n"
        "                        and hasattr(ccls, cpk) and hasattr(ccls, cowner)):\n"
        "                    dcol = _discrim(ccls)\n"
        "                    try:\n"
        "                        for r in db.query(ccls).filter(getattr(ccls, cowner) == demo_uid).all():\n"
        "                            _p = getattr(r, cpk); anyids.append(_p)\n"
        "                            bykind.setdefault(getattr(r, dcol, None) if dcol else None, []).append(_p)\n"
        "                    except Exception:\n"
        "                        pass\n"
        "                    if dcol:\n"
        "                        try:\n"
        "                            for r in db.query(ccls).all():\n"
        "                                kof[getattr(r, cpk)] = getattr(r, dcol, None)\n"
        "                        except Exception:\n"
        "                            pass\n"
        "                demo_by_kind[ctab] = bykind; demo_any[ctab] = anyids; kind_of[ctab] = kof\n"
        "            col_names = [c.name for c in cls.__table__.columns]\n"
        "            uniq = set(_UNIQUE.get(t, []))\n"
        "            need = _DEMO_FLOOR - have\n"
        "            made, attempts = 0, 0\n"
        "            max_attempts = need * (len(donors) + 2) + 4\n"
        "            while made < need and attempts < max_attempts:\n"
        "                donor = donors[attempts % len(donors)]\n"
        "                attempts += 1\n"
        "                vals, skip = {}, False\n"
        "                for c in col_names:\n"
        "                    if c == pk_name:\n"
        "                        continue  # integer PK → SERIAL assigns; uuid/text minted below\n"
        "                    if c == owner:\n"
        "                        vals[c] = demo_uid\n"
        "                        continue\n"
        "                    if c in child_map:\n"
        "                        ctab = child_map[c]\n"
        "                        _dpk = getattr(donor, c, None)\n"
        "                        _dk = kind_of.get(ctab, {}).get(_dpk)\n"
        "                        # file the clone under the demo's SAME-KIND child (donor's\n"
        "                        # Inbox message → demo's Inbox), so received mail populates the\n"
        "                        # INBOX screen, not scattered round-robin into Sent/Trash.\n"
        "                        pool = demo_by_kind.get(ctab, {}).get(_dk) or demo_any.get(ctab) or []\n"
        "                        if pool:\n"
        "                            vals[c] = pool[made % len(pool)]\n"
        "                        elif _dpk is None:\n"
        "                            continue  # nullable/absent → leave NULL\n"
        "                        else:\n"
        "                            skip = True  # NOT-NULL child FK, no demo equivalent\n"
        "                            break\n"
        "                        continue\n"
        "                    v = getattr(donor, c, None)\n"
        "                    if v is None:\n"
        "                        continue\n"
        "                    if c in uniq and isinstance(v, str):\n"
        "                        v = v[:180] + ' (' + str(demo_uid) + '-' + str(made + 1) + ')'\n"
        "                    vals[c] = v\n"
        "                if skip:\n"
        "                    continue\n"
        "                if pk_cat == 'uuid':\n"
        "                    import uuid as _uuid\n"
        "                    vals[pk_name] = str(_uuid.uuid5(_uuid.NAMESPACE_DNS,\n"
        "                        t + '-demo-' + str(demo_uid) + '-' + str(made + 1)))\n"
        "                elif pk_cat == 'text':\n"
        "                    vals[pk_name] = str(t)[:12] + '-d' + str(demo_uid) + '-' + str(made + 1)\n"
        "                try:\n"
        "                    db.add(cls(**{k: v for k, v in vals.items() if hasattr(cls, k)}))\n"
        "                    db.commit()\n"
        "                    made += 1\n"
        "                except Exception:\n"
        "                    db.rollback()\n"
        "    finally:\n"
        "        db.close()\n\n\n"
        "def seed_if_empty():\n"
        "    data = _load_rows()\n"
        "    # SEED-SOURCE FINGERPRINT (outlook run-30, live): the loader used to fill only\n"
        "    # EMPTY tables, so the fallback _SEED applied at first boot PERMANENTLY shadowed\n"
        "    # the agent-authored seed_data.json written later — the delivered app carried the\n"
        "    # bland fallback (2-row inbox vs the spec's populated screens) and the authored\n"
        "    # demo user didn't exist (demo login 401 → QA/visual flows lost their populated\n"
        "    # session). Stamp a hash of the APPLIED source; when the source changes, reset the\n"
        "    # seed-managed tables and re-apply.\n"
        "    fp = hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode('utf-8')).hexdigest()\n"
        "    nu = max(1, len(data.get('users') or _SEED.get('users') or []) or 1)\n"
        "    db = SessionLocal()\n"
        "    try:\n"
        "        applied = _applied_fingerprint(db)\n"
        "        if applied == fp:\n"
        "            # Same source, already applied — but still heal the sequences: a\n"
        "            # container restarted on a pre-#56 database boots down this path\n"
        "            # with its sequences still inside the seeded id range (run-41).\n"
        "            _sync_sequences(db)\n"
        "            return\n"
        "        if applied is not None:\n"
        "            _reset_seeded_tables(db)\n"
        "        for t in _ORDER:\n"
        "            cls = getattr(models, _CLASS.get(t, ''), None)\n"
        "            if cls is None:\n"
        "                continue\n"
        "            try:\n"
        "                if db.query(cls).first() is not None:\n"
        "                    continue\n"
        "            except Exception:\n"
        "                continue\n"
        "            owner = _OWNER_COL.get(t)\n"
        "            for i, row in enumerate(data.get(t, [])):\n"
        "                row = dict(row)\n"
        "                if t == 'users':\n"
        "                    # ALWAYS hash the known seed password — the agent-authored\n"
        "                    # seed_data.json often carries a PLACEHOLDER password_hash\n"
        "                    # ('hashed_password') or a wrong-scheme hash (it can't know the\n"
        "                    # salt/scheme), which makes the demo/QA user UN-LOGINABLE\n"
        "                    # (auth_ok=False -> every page blank). Respect an explicit\n"
        "                    # plaintext `password`, else 'password'; OVERRIDE any agent hash.\n"
        "                    pw = row.pop('password', None) or 'password'\n"
        "                    row['password_hash'] = hashlib.sha256(\n"
        "                        (pw + _PASSWORD_SALT).encode('utf-8')).hexdigest()\n"
        "                    row.setdefault('tenant_id', 'default')\n"
        "                elif owner and not row.get(owner):\n"
        "                    row[owner] = (i % nu) + 1\n"
        "                for _ic in _IMAGE_COL.get(t, []):\n"
        "                    if not row.get(_ic):\n"
        "                        row[_ic] = 'https://picsum.photos/seed/' + t + str(i) + '/400/400'\n"
        "                try:\n"
        "                    db.add(cls(**{k: v for k, v in row.items() if hasattr(cls, k)}))\n"
        "                except Exception:\n"
        "                    pass\n"
        "            try:\n"
        "                db.commit()\n"
        "            except Exception:\n"
        "                db.rollback()\n"
        "        _sync_sequences(db)\n"
        "        _store_fingerprint(db, fp)\n"
        "    finally:\n"
        "        db.close()\n"
        "        _ensure_canonical_rows()\n"  # FIX #72: heal canonical rows on EVERY boot
        "        _concentrate_demo_content()\n"  # FIX #74: fill the demo user's screens
    )
    return body


def write_backend_skeleton(
    output_dir: Any,
    endpoints: List[Mapping[str, Any]],
    tables: Dict[str, Any],
) -> Dict[str, Any]:
    """Generate the ENTIRE backend deterministically from the contract: ORM models,
    fixed storage (database.py), all CRUD handlers (main.py), auth dependency, and fixed
    infra (Dockerfile/pyproject/reset.sh/schemas). Overwrites the lane's app code — the
    lane's job is authoring the contract, not the app structure. Returns written paths."""
    from .backend_scaffold import _AUTH_DEPENDENCY_PY

    be = Path(output_dir) / "app" / "backend"
    be.mkdir(parents=True, exist_ok=True)
    written: Dict[str, str] = {}

    def w(name: str, content: str) -> None:
        (be / name).write_text(content, encoding="utf-8")
        written[name] = str(be / name)

    # FIX #72: detect the canonical per-user named rows the lane's handlers REQUIRE
    # (``Folder.name == "Sent"`` / ``kind == "trash"`` guarded by a raise-on-absent) and
    # project the bootstrap spec BOTH the seed loader (seeded users) and create_user
    # (registered users — the verification chain's user) enforce. Best-effort; a detector
    # miss just yields an empty spec (the pre-#72 behaviour), never a crash.
    _bootstrap_spec: List[Dict[str, Any]] = []
    try:
        from .canonical_rows import detect_canonical_rows, build_bootstrap_spec
        _routes_src = ""
        _cr = be / "custom_routes.py"
        if _cr.exists():
            _routes_src = _cr.read_text(encoding="utf-8")
        if _routes_src:
            _canonical = detect_canonical_rows(_routes_src, render_models(tables))
            _bootstrap_spec = build_bootstrap_spec(_canonical, tables)
    except Exception:
        _bootstrap_spec = []

    w("database.py", _DATABASE_PY)
    w("models.py", render_models(tables))
    w("seed_data.py", render_seed_data(tables, _bootstrap_spec))  # framework LOADER (code; embeds _SEED fallback)
    import json as _json_bs
    w("user_bootstrap.json", _json_bs.dumps(_bootstrap_spec, indent=2, ensure_ascii=False))  # FIX #72: create_user reads this
    # The framework deliberately does NOT write seed_data.json — that DATA file is the
    # backend agent's to AUTHOR with domain-aware values. Shipping a COMPLETE default here
    # anchored the agent to placeholder content (live 2026-06-29: it kept the framework's
    # "Getting Started"/"Project Overview" subjects + generic bodies instead of authoring
    # real ones). So we ship only the LOADER, whose embedded _SEED is the runtime fallback
    # (the app is still never blank). render_seed_json stays for tooling/inspection.
    w("auth_dependency.py", _AUTH_DEPENDENCY_PY)
    w("main.py", render_skeleton_main(endpoints, tables))
    w("schemas.py", _SCHEMAS_PY)
    _ensure_seed_json(be)
    w("pyproject.toml", render_pyproject(be))
    w("Dockerfile", _DOCKERFILE)
    w("reset.sh", _RESET_SH)
    return {"written": list(written), "backend_dir": str(be)}
