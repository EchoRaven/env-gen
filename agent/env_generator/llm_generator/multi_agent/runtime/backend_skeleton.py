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
    if col.get("nullable") is False or col.get("not_null"):
        kw.append("nullable=False")
    if col.get("unique"):
        kw.append("unique=True")
    default = col.get("default")
    if default is not None:
        d = str(default).strip()
        if d.lower() in ("now()", "current_timestamp"):
            args.append("default=datetime.utcnow")
        elif not (col.get("primary_key") or col.get("pk")):
            lit = d if (d.startswith(("'", '"')) or d.replace(".", "").isdigit()
                        or d.lower() in ("true", "false")) else repr(d)
            kw.append(f"default={lit}")
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
            if tt not in by_name:  # spine/external target → skip (tenants/users exempt)
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
        "from datetime import datetime\n\n"
        "from sqlalchemy import (Column, Integer, BigInteger, String, Text, Boolean,\n"
        "                        DateTime, Date, Time, Float, Numeric, JSON, ForeignKey)\n"
        "from database import Base\n\n\n"
    )
    return header + "\n\n\n".join(blocks) + "\n"


# ── database.py (fixed storage layer) ───────────────────────────────────────
_DATABASE_PY = '''"""Framework-generated storage layer — engine + session + Base. Fixed by
construction (the DATABASE_URL is the SQLAlchemy psycopg3 URL from the env)."""
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://sandbox:sandbox@database:5432/app")
engine = create_engine(_URL, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
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
        names, fks = [], {}
        have_pk = False
        for c in cols:
            if _is_constraint_pseudo_column(c):
                continue
            n = str(c.get("name") or "").strip()
            if not n:
                continue
            names.append(n)
            if c.get("primary_key") or c.get("pk"):
                have_pk = True
            tgt = _fk_target(c)
            if tgt:
                fks[n] = tgt.split(".")[0]
        if not have_pk and "id" not in names:
            names.insert(0, "id")
        meta[table] = {"cls": _class_name(table), "cols": names, "fks": fks}

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

Base.metadata.create_all(bind=engine)

# Populate empty business tables with realistic demo data so the UI is not blank
# on first load (framework-owned; idempotent — skips tables that already have rows).
try:
    from seed_data import seed_if_empty
    seed_if_empty()
except Exception:
    pass  # seeding is best-effort; never block boot

app = FastAPI(title="app")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])

# Framework OAuth2 AS — /oauth/*, /.well-known/*, /auth/register, /auth/login.
try:
    from oauth_store import OAuthStore
    from jwt_manager import JWTManager
    from oauth_routes import build_router as _as_build_router
    app.include_router(_as_build_router(OAuthStore(), JWTManager()))
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
def _custom_route_overrides_projected(method, path):
    """A lane custom route may OVERRIDE the projected handler only for NON-standard-CRUD
    endpoints — i.e. an action verb after a path param (/x/{id}/rsvp), search, or any
    other novel shape. Standard CRUD (bare collection, item-by-{param}, /me) keeps the
    safe projected handler, so a buggy lane CRUD handler can't 500-shadow it."""
    segs = [s for s in str(path).strip("/").split("/") if s]
    if segs and segs[0] == "api":
        segs = segs[1:]
    if not segs:
        return True
    last = segs[-1]
    n_params = sum(1 for s in segs if s.startswith("{") or s.startswith(":"))
    last_is_param = last.startswith("{") or last.startswith(":")
    # standard CRUD shapes → projected wins (return False = do NOT let custom override):
    if len(segs) == 1 and not last_is_param:          # collection: /messages
        return False
    if last_is_param and n_params == 1:               # item by id: /messages/{id}
        return False
    if last == "me":                                  # current-user singleton: /auth/me
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
except ImportError:
    pass
except Exception as _custom_exc:  # pragma: no cover — a broken override must not kill boot
    import logging
    logging.getLogger("custom_routes").warning("custom_routes failed to load: %s", _custom_exc)
'''

_MAIN_FOOTER = '''

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("API_PORT", "8081")))
'''


def render_skeleton_main(endpoints: List[Mapping[str, Any]], tables: Dict[str, Any]) -> str:
    """Render the full ``main.py``: fixed skeleton + auth-enforcement middleware + ALL
    business handlers projected from the contract (static routes before param routes)."""
    from .route_projector import _generate_handler, _norm_path
    from .backend_scaffold import _AUTH_MIDDLEWARE

    meta = _models_meta(tables)
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
        block = _generate_handler(method, path, auth, meta, i)
        (param_blocks if "{" in path else static_blocks).append(block)

    # _AUTH_MIDDLEWARE references ``app`` + imports jwt/JSONResponse/jwt_manager; it is
    # inserted after the app is constructed and before the routes (static-first).
    mid = _AUTH_MIDDLEWARE.strip("\n")
    # _CUSTOM_ROUTES_INCLUDE precedes the projected blocks so a lane custom_routes
    # handler OVERRIDES the projected one for the same METHOD+path (first-registered
    # wins in Starlette) — the documented lane-override intent, which the old footer
    # placement silently inverted.
    body = (_MAIN_HEADER + "\n\n" + mid + "\n\n\n"
            + _CUSTOM_ROUTES_INCLUDE + "\n\n\n"
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

_DOCKERFILE = '''FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim
WORKDIR /app
COPY pyproject.toml ./
RUN uv pip install --system -r pyproject.toml
COPY *.py ./
COPY reset.sh /reset.sh
RUN chmod +x /reset.sh
EXPOSE 8081
CMD ["python", "main.py"]
'''

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
    for name, content in (("pyproject.toml", _PYPROJECT),
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
_SEED_TITLES = ["Sunrise Timelapse over the Bay", "How We Built It in a Weekend",
                "A Calm Morning Routine", "Deep Dive: Getting Started",
                "Field Notes from the Road", "Behind the Scenes"]
_SEED_BRANDS = ["Pixel Forge", "Trailhead Studio", "North Loop", "Quiet Harbor", "Bright Atlas", "Cedar & Co"]
_SEED_SENTENCES = ["A behind-the-scenes look at how it all came together.",
                   "Everything you need to get started, one step at a time.",
                   "Quick highlights and a few things we learned this week.",
                   "Thanks for following along — much more on the way.",
                   "A relaxed walkthrough with notes you can follow."]
_SEED_GENRES = ["Ambient", "Lo-fi", "Cinematic", "Acoustic", "Electronic"]
_SEED_OMIT = object()


def _seed_slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(s).lower()) or "demo"


def _seed_cell(col: str, table: str, i: int, fk_table: Optional[str], counts: Dict[str, int]):
    """A realistic, deterministic value for one column of seed row ``i`` — or
    ``_SEED_OMIT`` to leave it (PK/timestamp/unknown → DB default/null). Value is
    chosen by COLUMN NAME first (domain-agnostic), then type-ish fallbacks."""
    n = col.lower()
    if fk_table:
        if fk_table == "tenants":
            return "default"
        m = max(1, int(counts.get(fk_table, 1)))
        return (i % m) + 1  # reference an existing parent row (SERIAL 1..N)
    if n in ("id",):
        return _SEED_OMIT  # PK → SERIAL
    if n == "password_hash":
        return _seed_password_hash()
    if n in ("created_at", "updated_at", "published_at", "watched_at") or n.endswith("_at"):
        return _SEED_OMIT  # DB default now()/nullable — avoid datetime coercion
    if n == "email":
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
    if n == "genre":
        return _SEED_GENRES[i % len(_SEED_GENRES)]
    if n == "artist":
        return _SEED_PEOPLE[i % len(_SEED_PEOPLE)]
    if n in ("name", "title", "display_name", "full_name", "label") or n.endswith("_name") or n.endswith("_title"):
        pool = _SEED_PEOPLE if table in ("users",) else (_SEED_BRANDS if table in ("channels", "tenants") else _SEED_TITLES)
        return pool[i % len(pool)]
    if any(k in n for k in ("views", "count", "subscriber", "likes", "total",
                            "watch_time", "revenue", "quantity", "duration", "seconds", "position")):
        return (i + 1) * 1731 % 9800 + 42
    if n in ("kind", "type"):
        return ["video", "short"][i % 2]
    if n == "visibility":
        return ["public", "unlisted", "public"][i % 3]
    if n in ("status", "state"):
        return "active"
    if n in ("value", "role"):
        return ["like", "dislike"][i % 2] if n == "value" else "member"
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


def render_seed_data(tables: Dict[str, Any]) -> str:
    """Project a seed_data.py that fills each EMPTY table with realistic, FK-valid
    rows on startup (idempotent — skips a table that already has rows). Users get a
    real auth hash so they log in with 'password'. Domain-agnostic + deterministic."""
    meta = _models_meta(tables)
    order = _seed_topo_order(meta)
    n_users = 5
    counts: Dict[str, int] = {"users": n_users, "tenants": 1}
    for t in order:
        counts.setdefault(t, 6)
    # users first (login-able), then business tables in FK order.
    seed: Dict[str, List[Dict[str, Any]]] = {}
    full_order = (["users"] if "users" in meta else []) + [t for t in order if t != "users"]
    for t in full_order:
        cols = [c for c in (meta[t].get("cols") or []) if c]
        fks = meta[t].get("fks") or {}
        rows: List[Dict[str, Any]] = []
        for i in range(counts.get(t, 6)):
            row: Dict[str, Any] = {}
            for c in cols:
                v = _seed_cell(c, t, i, fks.get(c), counts)
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
    # repr() (NOT json.dumps) — this is a PYTHON module, so booleans must be
    # True/False not JSON true/false (else NameError at import).
    body = (
        '"""Framework-generated deterministic seed data — every business table is\n'
        'populated with realistic, FK-valid demo rows on first boot so the UI is not\n'
        'blank. Idempotent: a table that already has rows is left untouched. Demo\n'
        'users log in with password "password"."""\n'
        "from database import SessionLocal\n"
        "import models\n\n"
        f"_ORDER = {list(seed.keys())!r}\n"
        f"_CLASS = {classmap!r}\n"
        f"_SEED = {seed!r}\n\n\n"
        "def seed_if_empty():\n"
        "    db = SessionLocal()\n"
        "    try:\n"
        "        for t in _ORDER:\n"
        "            cls = getattr(models, _CLASS.get(t, ''), None)\n"
        "            if cls is None:\n"
        "                continue\n"
        "            try:\n"
        "                if db.query(cls).first() is not None:\n"
        "                    continue\n"
        "            except Exception:\n"
        "                continue\n"
        "            for row in _SEED.get(t, []):\n"
        "                try:\n"
        "                    db.add(cls(**{k: v for k, v in row.items() if hasattr(cls, k)}))\n"
        "                except Exception:\n"
        "                    pass\n"
        "            try:\n"
        "                db.commit()\n"
        "            except Exception:\n"
        "                db.rollback()\n"
        "    finally:\n"
        "        db.close()\n"
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

    w("database.py", _DATABASE_PY)
    w("models.py", render_models(tables))
    w("seed_data.py", render_seed_data(tables))
    w("auth_dependency.py", _AUTH_DEPENDENCY_PY)
    w("main.py", render_skeleton_main(endpoints, tables))
    w("schemas.py", _SCHEMAS_PY)
    w("pyproject.toml", _PYPROJECT)
    w("Dockerfile", _DOCKERFILE)
    w("reset.sh", _RESET_SH)
    return {"written": list(written), "backend_dir": str(be)}
