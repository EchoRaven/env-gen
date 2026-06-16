"""Deterministic projection of registered SchemaHub tables → app/database/.

The compose file (``orchestrator._generate_docker``) unconditionally
declares a ``database`` service whose build context is ``../app/database``,
and the delivery gate (``_validate_delivery_gate``) requires
``app/database/*.sql`` to exist. No LLM lane reliably authors that
directory, so historically every ``docker_up`` failed on the missing
build context.

This module closes that gap **by construction**: the runtime is the SOLE
owner of ``app/database/``. The kickoff contract validator
(``roadmap_validator``) already guarantees every registered table carries
a non-empty ``columns: [{name, type}]`` list, and ``finalize_kickoff``
stores that verbatim under each table's ``schema``. So once kickoff
finalizes, the runtime holds everything needed to emit a faithful
``CREATE TABLE`` schema — no agent, no prompt, no variance.

Charter §8 ("fallback对系统不好 — no silent fallback paths"):
  * Unknown column types are NOT silently swapped for a default — the
    declared type is emitted verbatim as a literal SQL type. Postgres
    rejects genuine garbage at build time, which the verifier's
    ``sql_syntax`` check surfaces honestly.
  * A table with zero columns / a column missing name or type is a
    contract violation the kickoff validator should already have caught;
    here it raises loudly rather than emitting broken-but-silent SQL.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


# Known abstract → postgres type aliases. Anything not listed passes
# through verbatim (trusted as a literal SQL type — see module docstring).
_TYPE_ALIASES: Dict[str, str] = {
    "string": "TEXT", "str": "TEXT", "text": "TEXT",
    "int": "INTEGER", "integer": "INTEGER",
    "bigint": "BIGINT", "long": "BIGINT",
    "smallint": "SMALLINT",
    "float": "DOUBLE PRECISION", "double": "DOUBLE PRECISION",
    "number": "DOUBLE PRECISION", "real": "REAL",
    "decimal": "NUMERIC", "numeric": "NUMERIC",
    "bool": "BOOLEAN", "boolean": "BOOLEAN",
    "uuid": "UUID",
    "json": "JSONB", "jsonb": "JSONB",
    "timestamp": "TIMESTAMPTZ", "datetime": "TIMESTAMPTZ",
    "timestamptz": "TIMESTAMPTZ",
    "date": "DATE", "time": "TIME",
    "serial": "SERIAL", "bigserial": "BIGSERIAL",
}


def _sql_type(raw: str) -> str:
    t = (raw or "").strip()
    # LLM/ORM contracts sometimes cram a CHECK constraint INTO the column type
    # string, e.g. ``media_type = "text check in ('image','video')"``. Rendered
    # verbatim that's invalid SQL — a column CHECK must be ``CHECK (col IN (...))``,
    # not a bare ``check in (...)`` — so postgres initdb fails with a syntax error,
    # the DB never initializes, and docker_up FAILS (the whole run stalls in
    # validation). The real SQL type is the part BEFORE ``check``; drop the
    # malformed inline constraint (the app validates the enum in its Pydantic
    # schema, and an over-permissive column is harmless to the contract).
    m = re.search(r"\bcheck\b", t, re.IGNORECASE)
    if m:
        t = t[: m.start()].strip()
    return _TYPE_ALIASES.get(t.lower(), t)


# Postgres inline FK is ``REFERENCES table (col)``. Kickoff contracts
# routinely emit the dotted ``references table.col`` form (postgres parses
# that as schema=table/table=col → "schema ... does not exist", initdb
# fails and the db container exits(3); confirmed via manual docker). The
# referenced (table, col) is unambiguous, so rewrite to the valid
# parenthesized form. NOT a silent fallback (Charter §8) — it's a
# syntactic normalization of a known-invalid idiom, no data invented.
_FK_DOTTED_REF = re.compile(
    r'\breferences\s+("?\w+"?)\.("?\w+"?)', re.IGNORECASE
)


def _normalize_inline_fk(text: str) -> str:
    return _FK_DOTTED_REF.sub(r'references \1(\2)', text)


def _quote_ident(name: str) -> str:
    """Double-quote an identifier (protects reserved words like ``user`` /
    ``order``). Lowercase snake_case names round-trip unchanged for
    unquoted callers; embedded quotes are escaped per SQL rules."""
    return '"' + str(name).replace('"', '""') + '"'


# ── ONE canonical table-schema shape ────────────────────────────────────────
# The contract tools advertise a FLAT-MAP table schema (``{column: "type
# string"}`` — see hub_tools ``registryhub_register_table`` /
# ``registryhub_update_table_schema``), while kickoff_declare_table /
# finalize_kickoff emit ``{"columns": [{"name","type", …}]}``. Two shapes for
# one concept means every reader had to handle both — and the flat map never
# did (``_columns_of`` returned [] for it → an id-only ORM/DDL, silently
# dropping every other column on any RE-registered table). Collapse the
# variance to ONE canonical shape at the write boundary so the rest of the
# system reads a single representation.
#
# A flat-map value carries the column's modifiers inline in the type string
# (``"serial primary key"``, ``"integer references channels(id)"``,
# ``"text not null"`` …). The DDL renderer (``_render_column`` →
# ``_sql_type``/``_normalize_inline_fk``) already projects those verbatim, but
# the ORM renderer (``backend_skeleton._render_column``) keys PRIMARY KEY /
# UNIQUE / NOT NULL off STRUCTURED flags. So when flattening a flat-map column
# we PROMOTE those inline modifiers to structured flags (reusing the same
# parsing vocabulary the renderers already understand) — the column then
# projects faithfully through BOTH renderers. Already-structured inputs pass
# through untouched (idempotent — a ``{"columns":[…]}`` round-trips equal).
_INLINE_PK_RE = re.compile(r"\bprimary\s+key\b", re.IGNORECASE)
_INLINE_NOTNULL_RE = re.compile(r"\bnot\s+null\b", re.IGNORECASE)
_INLINE_UNIQUE_RE = re.compile(r"\bunique\b", re.IGNORECASE)
_INLINE_REFERENCES_RE = re.compile(
    r"\breferences\s+(\w+)\s*(?:\(\s*(\w+)\s*\)|\.\s*(\w+))", re.IGNORECASE
)


def _column_from_flat(name: str, type_spec: Any) -> Dict[str, Any]:
    """Build a canonical column dict from a flat-map ``name: "type string"``
    entry, promoting inline modifiers (``primary key`` / ``not null`` /
    ``unique`` / ``references x(y)``) to structured flags so the column
    projects correctly through BOTH the DDL and ORM renderers. The full type
    string (FK and all) is preserved verbatim as ``type`` for the DDL
    renderer, which honours inline ``references`` directly."""
    col: Dict[str, Any] = {"name": str(name), "type": str(type_spec or "").strip()}
    spec = col["type"]
    if _INLINE_PK_RE.search(spec):
        col["primary_key"] = True
    if _INLINE_NOTNULL_RE.search(spec):
        col["not_null"] = True
    if _INLINE_UNIQUE_RE.search(spec):
        col["unique"] = True
    m = _INLINE_REFERENCES_RE.search(spec)
    if m:
        col["references"] = "{}({})".format(m.group(1), m.group(2) or m.group(3))
    return col


def normalize_columns(schema: Any) -> List[Any]:
    """Coerce ANY accepted table-schema shape to a canonical column LIST:
      * a ``{"columns": [...]}`` dict           → its ``columns`` list (as-is)
      * a bare ``[{"name","type"}, ...]`` list  → itself (as-is)
      * a flat map ``{col: "type string"}``     → ``[{"name","type", …}]`` with
        inline modifiers promoted to structured flags (see _column_from_flat)
    Returns [] for anything unrecognized (an empty/None schema)."""
    if isinstance(schema, list):
        return schema
    if isinstance(schema, dict):
        cols = schema.get("columns")
        if isinstance(cols, list):
            return cols
        # Flat map {column_name: "type string"} — the contract-tool shape.
        return [_column_from_flat(k, v) for k, v in schema.items()]
    return []


def normalize_table_schema(schema: Any) -> Dict[str, Any]:
    """Coerce ANY accepted table-schema shape to the ONE canonical container
    ``{"columns": [{"name","type", …}]}`` — the shape ``kickoff_declare_table``
    /``finalize_kickoff`` already produce and every reader (via ``_columns_of``)
    already understands. Idempotent: a canonical ``{"columns":[…]}`` input is
    returned structurally unchanged."""
    if isinstance(schema, dict) and isinstance(schema.get("columns"), list):
        return schema
    return {"columns": normalize_columns(schema)}


def _columns_of(table: Dict[str, Any]) -> List[Any]:
    """Extract the column list from a SchemaHub table record.

    Canonical shape: ``table["schema"]["columns"]`` (finalize_kickoff
    stores the contract table minus ``name`` under ``schema``). Tolerant
    of a flattened ``table["columns"]`` list AND of a raw flat-map
    ``{column: "type string"}`` schema (defense in depth: a legacy/raw
    store row still projects correctly), via ``normalize_columns`` — same
    data, alternate location/shape, not an invented default."""
    schema = table.get("schema")
    if isinstance(schema, dict) and isinstance(schema.get("columns"), list):
        return schema["columns"]
    if isinstance(table.get("columns"), list):
        return table["columns"]
    # Flat-map schema (or a bare list under ``schema``) — normalize so a row
    # that bypassed the write-boundary normalizer still yields its columns.
    if isinstance(schema, (dict, list)) and schema:
        return normalize_columns(schema)
    return []


def _render_column(table_name: str, col: Any) -> str:
    if not isinstance(col, dict):
        raise ValueError(
            f"database_scaffold: table {table_name!r} has a non-mapping column: {col!r}"
        )
    cname = str(col.get("name") or "").strip()
    ctype = str(col.get("type") or "").strip()
    if not cname:
        raise ValueError(f"database_scaffold: table {table_name!r} has a column with no name")
    if not ctype:
        raise ValueError(
            f"database_scaffold: column {cname!r} in table {table_name!r} has no type"
        )
    parts = [_quote_ident(cname), _sql_type(ctype)]
    # Optional constraints — honored ONLY when explicitly declared.
    if col.get("primary_key") or col.get("pk"):
        parts.append("PRIMARY KEY")
    if col.get("nullable") is False or col.get("not_null"):
        parts.append("NOT NULL")
    if col.get("unique"):
        parts.append("UNIQUE")
    default = col.get("default")
    if default is not None:
        parts.append(f"DEFAULT {default}")
    # Fix dotted inline FKs (`references users.id` → `references users(id)`)
    # wherever they landed — contracts cram them into the `type` passthrough.
    return "    " + _normalize_inline_fk(" ".join(parts))


# FIX #32: LLMs frequently model a TABLE-LEVEL constraint as if it were a column
# in the data model — e.g. the `follows` table arrived with a pseudo-column
# ``{"name": "unique(follower_id,following_id)", "type": "constraint"}``. Rendered
# as a column that becomes ``"unique(follower_id,following_id)" constraint``, which
# is a SQL syntax error → postgres init aborts (exit 3) → the whole app fails to
# boot from a clean volume → api_smoke FAILS (docker_up) → no delivery. The DDL is
# the deterministic projection chokepoint, so reconcile it HERE: detect these
# pseudo-columns and emit them as proper table-level constraints instead.
_CONSTRAINT_PSEUDO_TYPES = {"constraint", "table_constraint", "table constraint"}
_CONSTRAINT_NAME_RE = re.compile(
    r"^\s*(unique|primary\s*key|foreign\s*key|check)\s*\((.*)\)\s*$", re.IGNORECASE
)


def _is_constraint_pseudo_column(col: Any) -> bool:
    """True if a 'column' entry is really a mis-modeled table constraint."""
    if not isinstance(col, dict):
        return False
    if str(col.get("type") or "").strip().lower() in _CONSTRAINT_PSEUDO_TYPES:
        return True
    cname = str(col.get("name") or "").strip()
    if cname.lower().startswith("constraint "):
        return True
    return bool(_CONSTRAINT_NAME_RE.match(cname))


def _render_table_constraint(col: Dict[str, Any]) -> Optional[str]:
    """Turn a constraint-pseudo-column into a valid table-constraint clause.

    Handles the common composite ``UNIQUE (...)`` / ``PRIMARY KEY (...)`` cases
    precisely; returns None (skip — better a dropped constraint than broken DDL)
    for FOREIGN KEY / CHECK / anything unparseable."""
    raw = str(col.get("name") or "").strip()
    m = _CONSTRAINT_NAME_RE.match(raw)
    if not m:
        return None
    kw = re.sub(r"\s+", " ", m.group(1).strip().upper())  # UNIQUE / PRIMARY KEY / ...
    cols = [c.strip().strip('"').strip("`").strip() for c in m.group(2).split(",")]
    cols = [c for c in cols if c]
    if not cols or kw not in ("UNIQUE", "PRIMARY KEY"):
        return None
    return "    " + kw + " (" + ", ".join(_quote_ident(c) for c in cols) + ")"


# FIX #34: the spine OWNS the `users` table NAME (the embedded OAuth AS reads
# id/email/password_hash/tenant_id off it), but apps legitimately EXTEND users
# with domain/profile columns — Instagram needs `username`, `avatar_url`, etc.
# The old projector dropped the app's `users` definition wholesale, so those
# columns never existed and the backend's own queries blew up at runtime
# (psycopg UndefinedColumn ``users.username`` → register 500 → no delivery).
# Merge the app's EXTRA columns into the spine table via idempotent ALTERs.
_SPINE_USERS_COLUMNS = frozenset(
    {"id", "email", "name", "password_hash", "tenant_id", "created_at"}
)


# FIX #43 (#2 — guaranteed handler↔schema consistency): the LLM's ORM models +
# handlers agree with EACH OTHER (e.g. both use ``posts.user_id``) but can drift
# from the description-derived DDL (which had ``posts.author_id``). The MODEL is
# the runtime truth — the handler queries through it — so derive the DDL FROM the
# app's actual SQLAlchemy models instead of the spec. Then DDL↔model↔handler can
# never drift: they share one source. Introspection (SQLAlchemy resolves types/
# FKs/uniques exactly) runs in a subprocess so the framework process stays clean.
_ORM_INTROSPECT_CODE = r"""
import sys, os, json
sys.path.insert(0, ".")
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://x:x@127.0.0.1:5432/x")
import models  # noqa: F401
md = models.Base.metadata
out = []
for t in md.sorted_tables:
    cols = []
    for c in t.columns:
        fk = None
        if c.foreign_keys:
            fk = list(c.foreign_keys)[0].target_fullname  # e.g. "users.id"
        cols.append({"name": c.name, "type": str(c.type), "pk": bool(c.primary_key),
                     "fk": fk, "unique": bool(c.unique)})
    uniques = []
    for con in t.constraints:
        cn = type(con).__name__
        if cn == "UniqueConstraint":
            uc = [col.name for col in getattr(con, "columns", [])]
            if len(uc) >= 2:
                uniques.append(uc)
    out.append({"name": t.name, "columns": cols, "composite_unique": uniques})
print(json.dumps(out))
"""


def _ddl_type_from_introspect(col: Dict[str, Any]) -> str:
    t = str(col.get("type") or "").upper()
    if col.get("pk") and "INT" in t:
        return "serial primary key"
    if col.get("fk"):
        tbl, _, tcol = str(col["fk"]).partition(".")
        return "integer references {}({}) on delete cascade".format(tbl, tcol or "id")
    if "INT" in t:
        return "integer"
    if "BOOL" in t:
        return "boolean default false"
    if "DATE" in t or "TIME" in t:
        return "timestamptz default now()"
    if "FLOAT" in t or "NUMERIC" in t or "DECIMAL" in t or "REAL" in t:
        return "numeric"
    return "text"


def introspect_orm_schema(backend_dir) -> Optional[Dict[str, Any]]:
    """Return a ``tables`` dict (render_schema_sql shape) introspected from the
    app's SQLAlchemy ``models.py``, or None if it can't be read. Best-effort: a
    subprocess import keeps the framework process clean and tolerates a missing/
    broken models.py (falls back to the spec-derived DDL)."""
    backend_dir = Path(backend_dir)
    if not (backend_dir / "models.py").exists():
        return None
    try:
        proc = subprocess.run(
            [sys.executable, "-c", _ORM_INTROSPECT_CODE],
            cwd=str(backend_dir), capture_output=True, text=True, timeout=60,
        )
    except Exception:
        return None
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    try:
        raw = json.loads(proc.stdout.strip().splitlines()[-1])
    except Exception:
        return None
    tables: Dict[str, Any] = {}
    for t in raw:
        name = str(t.get("name") or "").strip()
        if not name:
            continue
        cols: List[Dict[str, Any]] = []
        for c in t.get("columns") or []:
            cname = str(c.get("name") or "").strip()
            if not cname:
                continue
            cols.append({"name": cname, "type": _ddl_type_from_introspect(c),
                         "unique": bool(c.get("unique"))})
        for uc in t.get("composite_unique") or []:
            cols.append({"name": "unique({})".format(",".join(uc)), "type": "constraint"})
        if cols:
            tables[name] = {"name": name, "schema": {"columns": cols}}
    return tables or None


def _spine_extra_column_alters(
    table_name: str, cols: List[Any], spine_cols: frozenset
) -> List[str]:
    """``ALTER TABLE … ADD COLUMN IF NOT EXISTS`` for app columns not already in
    the spine table. NOT NULL is honored only with a DEFAULT (safe on a table
    that may already hold rows); UNIQUE / DEFAULT pass through."""
    out: List[str] = []
    seen = set()
    for col in cols:
        if not isinstance(col, dict) or _is_constraint_pseudo_column(col):
            continue
        cname = str(col.get("name") or "").strip()
        ctype = str(col.get("type") or "").strip()
        if not cname or not ctype:
            continue
        low = cname.lower()
        if low in spine_cols or low in seen:
            continue
        seen.add(low)
        parts = [_sql_type(ctype)]
        if col.get("unique"):
            parts.append("UNIQUE")
        default = col.get("default")
        if default is not None:
            parts.append(f"DEFAULT {default}")
            if col.get("nullable") is False or col.get("not_null"):
                parts.append("NOT NULL")
        clause = _normalize_inline_fk(" ".join(parts))
        out.append(
            f"ALTER TABLE {_quote_ident(table_name)} "
            f"ADD COLUMN IF NOT EXISTS {_quote_ident(cname)} {clause};"
        )
    return out


# Tenancy + identity + embedded-OAuth2-AS spine (forgingground model,
# deterministic / closed-by-construction): the env owns a tenants table + a
# users identity table + the embedded OAuth2 AS tables. The env IS the
# Authorization Server (zoom-style), so `users` carries a `password_hash` and
# the AS (jwt_manager/oauth_store/oauth_routes — runtime-emitted by
# runtime/oauth_scaffold.py) mints RS256 JWTs whose `sub` == str(users.id).
# Business tables FK to users(id) (the local SERIAL). This DDL is the SINGLE
# authoritative schema the AS reads/writes and is NEVER LLM-authored; the spine
# owns 'tenants'/'users'/'oauth_*' table names. The column shape here is locked
# to what oauth_store.py / oauth_routes.py / main.py expect — see
# docs/target_env_architecture.md §5 + §3a and runtime/oauth_scaffold.py.
_SPINE_OWNED_TABLES = frozenset({
    "tenants", "users", "oauth_clients", "oauth_authorization_codes",
})

_TENANCY_SPINE_SQL = """-- ── tenancy + identity + embedded OAuth2 AS spine (deterministic; target_env_architecture.md §5) ──
-- The env IS the OAuth2 Authorization Server (zoom-style): `users` carries a
-- password_hash; the AS mints RS256 access tokens whose `sub` == str(users.id).
-- Login/register scope every lookup by (email, tenant_id). The OAuth2 client
-- list columns (redirect_uris/grant_types/response_types) are JSON-encoded TEXT
-- (the store does json.dumps on write / json.loads on read), NOT native arrays.
-- FK order is load-bearing: tenants → users → oauth_authorization_codes.
CREATE TABLE IF NOT EXISTS tenants (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active',
    created_at TIMESTAMP DEFAULT NOW()
);
INSERT INTO tenants (id, name) VALUES ('default', 'Default Tenant') ON CONFLICT (id) DO NOTHING;

CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    email TEXT NOT NULL,
    -- FIX #35: spine display-name column is NOT essential to the AS (it keys on
    -- email/password_hash/id). Apps routinely carry their OWN display column
    -- (full_name, display_name, …) and their backend register never sets the
    -- spine `name`, which previously hit NotNullViolation → register 500 → no
    -- delivery. Default it so an insert that omits `name` still succeeds.
    name TEXT NOT NULL DEFAULT '',
    password_hash TEXT NOT NULL,
    tenant_id TEXT NOT NULL DEFAULT 'default' REFERENCES tenants(id) ON DELETE CASCADE,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE (email, tenant_id)
);
CREATE INDEX IF NOT EXISTS idx_users_tenant_id ON users(tenant_id);

CREATE TABLE IF NOT EXISTS oauth_clients (
    client_id TEXT PRIMARY KEY,
    client_secret TEXT,
    client_name TEXT NOT NULL DEFAULT '',
    redirect_uris TEXT NOT NULL DEFAULT '[]',
    grant_types TEXT NOT NULL DEFAULT '["authorization_code"]',
    response_types TEXT NOT NULL DEFAULT '["code"]',
    scope TEXT NOT NULL DEFAULT '',
    token_endpoint_auth_method TEXT NOT NULL DEFAULT 'none',
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS oauth_authorization_codes (
    code TEXT PRIMARY KEY,
    client_id TEXT NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    redirect_uri TEXT NOT NULL,
    scope TEXT NOT NULL DEFAULT '',
    code_challenge TEXT,
    code_challenge_method TEXT,
    resource TEXT,
    expires_at TIMESTAMP NOT NULL,
    used BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_oauth_codes_client_id ON oauth_authorization_codes(client_id);
"""


# Structured projection of the spine tables for RegistryHub/SchemaHub registration
# (consistency-by-construction): the orchestrator registers these so the
# contract is COMPLETE — a frontend/backend lane that queries the schema sees
# tenants/users/oauth_* as first-class registered tables, not implicit magic.
# These column names are drift-gated against ``_TENANCY_SPINE_SQL`` by
# ``test_database_scaffold`` so the manifest can never silently diverge from the
# DDL the AS actually reads/writes.
SPINE_TABLE_RECORDS = [
    {"name": "tenants", "columns": [
        {"name": "id", "type": "text", "primary_key": True},
        {"name": "name", "type": "text"},
        {"name": "status", "type": "text"},
        {"name": "created_at", "type": "timestamp"},
    ]},
    {"name": "users", "columns": [
        {"name": "id", "type": "serial", "primary_key": True},
        {"name": "email", "type": "text", "nullable": False},
        {"name": "name", "type": "text", "nullable": False},
        {"name": "password_hash", "type": "text", "nullable": False},
        {"name": "tenant_id", "type": "text", "nullable": False},
        {"name": "created_at", "type": "timestamp"},
    ]},
    {"name": "oauth_clients", "columns": [
        {"name": "client_id", "type": "text", "primary_key": True},
        {"name": "client_secret", "type": "text"},
        {"name": "client_name", "type": "text"},
        {"name": "redirect_uris", "type": "text"},
        {"name": "grant_types", "type": "text"},
        {"name": "response_types", "type": "text"},
        {"name": "scope", "type": "text"},
        {"name": "token_endpoint_auth_method", "type": "text"},
        {"name": "created_at", "type": "timestamp"},
    ]},
    {"name": "oauth_authorization_codes", "columns": [
        {"name": "code", "type": "text", "primary_key": True},
        {"name": "client_id", "type": "text", "nullable": False},
        {"name": "user_id", "type": "integer", "nullable": False},
        {"name": "redirect_uri", "type": "text", "nullable": False},
        {"name": "scope", "type": "text"},
        {"name": "code_challenge", "type": "text"},
        {"name": "code_challenge_method", "type": "text"},
        {"name": "resource", "type": "text"},
        {"name": "expires_at", "type": "timestamp", "nullable": False},
        {"name": "used", "type": "boolean"},
        {"name": "created_at", "type": "timestamp"},
    ]},
]


def render_schema_sql(tables: Dict[str, Any]) -> str:
    """Render ``init/01_init.sql``: the deterministic tenancy/identity spine
    followed by the registered SchemaHub business tables (the spine owns
    tenants/users/oauth_* — any contract table with those names is skipped)."""
    lines: List[str] = [
        "-- Auto-generated by orchestrator._generate_database — do not hand-edit.",
        "-- Deterministic projection: tenancy/identity spine + the kickoff contract.",
        "",
        _TENANCY_SPINE_SQL,
    ]
    if not tables:
        return "\n".join(lines) + "\n"

    for table_id, table in tables.items():
        if not isinstance(table, dict):
            raise ValueError(f"database_scaffold: table {table_id!r} is not a mapping")
        name = str(table.get("name") or table_id or "").strip()
        if not name:
            raise ValueError(f"database_scaffold: table {table_id!r} has no name")
        if name.lower() in _SPINE_OWNED_TABLES:
            # FIX #34: the spine owns the table NAME, but `users` is extensible —
            # merge the app's domain columns (username, avatar_url, …) in via
            # idempotent ALTERs so the backend's queries don't hit UndefinedColumn.
            # tenants/oauth_* are pure infra and stay untouched.
            if name.lower() == "users":
                alters = _spine_extra_column_alters(
                    name, _columns_of(table), _SPINE_USERS_COLUMNS)
                if alters:
                    lines.append("-- app-extended columns on the spine `users` table (FIX #34)")
                    lines.extend(alters)
                    lines.append("")
            continue  # spine owns the base table; extras merged above

        cols = _columns_of(table)
        if not cols:
            raise ValueError(f"database_scaffold: table {name!r} has no columns")
        # FIX #32: split real columns from mis-modeled table constraints so a
        # pseudo-column like {"name":"unique(a,b)","type":"constraint"} renders as
        # a trailing ``UNIQUE (a, b)`` clause, not a broken column definition.
        rendered_cols: List[str] = []
        constraint_lines: List[str] = []
        for c in cols:
            if _is_constraint_pseudo_column(c):
                clause = _render_table_constraint(c)
                if clause:
                    constraint_lines.append(clause)
                continue  # unparseable pseudo-constraint → drop (don't break DDL)
            rendered_cols.append(_render_column(name, c))
        if not rendered_cols:
            raise ValueError(f"database_scaffold: table {name!r} has no real columns")
        lines.append(f"CREATE TABLE IF NOT EXISTS {_quote_ident(name)} (")
        lines.append(",\n".join(rendered_cols + constraint_lines))
        lines.append(");")
        lines.append("")
    return "\n".join(lines) + "\n"


def write_database_scaffold(output_dir: Path, tables: Dict[str, Any]) -> Dict[str, Any]:
    """Author ``<output_dir>/app/database/init/01_init.sql``.

    Target = forgingground/agentsuite env: the DB is a **stock `postgres:16`
    image** with this DDL mounted into ``/docker-entrypoint-initdb.d`` (see
    ``docs/target_env_architecture.md``). There is NO custom database
    Dockerfile — postgres runs the mounted ``*.sql`` once on first init.

    Returns ``{"schema_sql": path, "table_count": int}``. Idempotent —
    overwrites on every call so the scaffold always reflects the current
    registered contract."""
    output_dir = Path(output_dir)
    init_dir = output_dir / "app" / "database" / "init"
    init_dir.mkdir(parents=True, exist_ok=True)

    schema_sql = init_dir / "01_init.sql"
    schema_sql.write_text(render_schema_sql(tables), encoding="utf-8")
    return {
        "schema_sql": schema_sql,
        "table_count": len(tables or {}),
    }


__all__ = [
    "render_schema_sql",
    "write_database_scaffold",
    "normalize_table_schema",
    "normalize_columns",
    "SPINE_TABLE_RECORDS",
    "_SPINE_OWNED_TABLES",
]
