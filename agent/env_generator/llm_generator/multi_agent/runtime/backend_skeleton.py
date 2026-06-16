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


def render_models(tables: Dict[str, Any]) -> str:
    """Render ``models.py`` (SQLAlchemy ORM) from the SchemaHub ``tables`` contract.
    Always emits the spine ``User``/``Tenant``; app tables generate one model each."""
    by_name: Dict[str, List[Dict[str, Any]]] = {}
    for name, table in (tables or {}).items():
        if isinstance(table, dict):
            by_name[str(name).lower()] = _columns_of(table)

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

_MAIN_FOOTER = '''

# LANE-OVERRIDE HOOK: custom_routes.py is the ONE backend file the lane owns —
# genuinely custom business logic (beyond contract-projected CRUD) goes there.
# The framework NEVER writes or overwrites it. Routes registered there take
# effect on top of the projected handlers (FastAPI matches them as defined).
try:
    from custom_routes import router as _custom_router
    app.include_router(_custom_router)
except ImportError:
    pass
except Exception as _custom_exc:  # pragma: no cover — a broken override must not kill boot
    import logging
    logging.getLogger("custom_routes").warning("custom_routes failed to load: %s", _custom_exc)

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
    body = (_MAIN_HEADER + "\n\n" + mid + "\n\n\n"
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
    w("auth_dependency.py", _AUTH_DEPENDENCY_PY)
    w("main.py", render_skeleton_main(endpoints, tables))
    w("schemas.py", _SCHEMAS_PY)
    w("pyproject.toml", _PYPROJECT)
    w("Dockerfile", _DOCKERFILE)
    w("reset.sh", _RESET_SH)
    return {"written": list(written), "backend_dir": str(be)}
