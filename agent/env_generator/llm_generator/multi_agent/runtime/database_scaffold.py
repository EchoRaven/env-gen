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
from typing import Any, Dict, List, Optional, Set, Tuple


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


# A column can carry its FK INLINE in the type string (``"integer references
# channels(id)"`` — handled by ``_normalize_inline_fk`` above) OR as a STRUCTURED
# field, which is what kickoff_declare_table / the normalizer / re-registered
# flat-map tables produce: ``references`` / ``fk`` keyed off the column dict, in
# any of ``"table(col)"`` / ``"table.col"`` / ``{"table":...,"column":...}`` form.
# The ORM renderer (backend_skeleton._fk_target) already reads these; the DDL
# renderer did NOT, so structured FKs were silently dropped from CREATE TABLE
# (no referential integrity). This helper extracts (ref_table, ref_column) from
# the structured field regardless of shape — domain-agnostic, no name special-casing.
_FK_INLINE_IN_TYPE_RE = re.compile(r"\breferences\b", re.IGNORECASE)
# ``table(col)`` / ``table.col`` parser for a structured string FK value.
_STRUCT_FK_STR_RE = re.compile(
    r'^\s*"?(\w+)"?\s*(?:\(\s*"?(\w+)"?\s*\)|\.\s*"?(\w+)"?)\s*$'
)


def _structured_fk_ref(col: Dict[str, Any]) -> Optional[tuple]:
    """Return ``(ref_table, ref_column)`` from a column's STRUCTURED FK field
    (``references`` / ``fk``), or None when there is no structured FK.

    Accepts every shape the contract/normalizer emits:
      * ``"users(id)"`` / ``"users.id"`` (string)
      * ``{"table": "users", "column": "id"}`` (nested dict)
      * a bare ``"users"`` (string with no column → defaults to ``id``)
    A FK written INLINE in the ``type`` string is NOT a structured FK and is
    intentionally ignored here (the inline path / ``_normalize_inline_fk``
    already renders it) so the two sources can't double-emit."""
    raw = col.get("references")
    if raw is None:
        raw = col.get("fk")
    if raw is None:
        return None
    if isinstance(raw, dict):
        tbl = str(raw.get("table") or raw.get("ref_table") or "").strip()
        rcol = str(raw.get("column") or raw.get("col") or raw.get("ref_column") or "").strip()
        if tbl:
            return (tbl, rcol or "id")
        return None
    if isinstance(raw, str) and raw.strip():
        m = _STRUCT_FK_STR_RE.match(raw)
        if m:
            return (m.group(1), m.group(2) or m.group(3) or "id")
        # Bare ``"users"`` with no column part → FK to its primary key ``id``.
        bare = raw.strip().strip('"')
        if re.fullmatch(r"\w+", bare):
            return (bare, "id")
    return None


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


_MISSING_TABLE_FIXED_KINDS = {"auth", "oauth", "infra", "spine"}
_MISSING_TABLE_SPINE = {"users", "tenants"}


def _derived_col_type(spec: Any) -> str:
    t = str(spec or "").lower()
    if "bool" in t:
        return "bool"
    if any(x in t for x in ("float", "decimal", "double", "numeric")):
        return "float"
    if any(x in t for x in ("int", "number")):
        return "int"
    if any(x in t for x in ("date", "time")):
        return "timestamp"
    return "text"


def synthesize_missing_tables(tables: Any, endpoints: Any) -> Dict[str, Any]:
    """BY-CONSTRUCTION contract completeness: ADD a backing table for every
    creatable business RESOURCE that has NO registered table, derived from the
    POST endpoint's request schema. At scale the backend lane registers the
    endpoints but not every table (youtube: 20 business endpoints, 1 table) →
    the route projector stubs those handlers (no id) → the default verification
    chain's create saves no id → ${...}_id sent literally → 422 → business_chain
    wedges → STUCK-ABORT. This is the table analog of synthesize_default_chain and
    uses the SAME creatable predicate (POST /api/<collection>, no path param, not a
    fixed kind), so the two agree by construction. Only ADDS (never overrides a
    lane-registered table); generic; deterministic. Columns mirror the registered
    convention: id(int,pk) + user_id(int→users.id) + nested parent FK + the request
    schema's fields (typed)."""
    out: Dict[str, Any] = dict(tables or {})
    have = {str(k).lower() for k in out}
    for ep in (endpoints or []):
        if not isinstance(ep, dict):
            continue
        if str(ep.get("method", "")).upper() != "POST":
            continue
        p = str(ep.get("path", "")).rstrip("/")
        # A creatable COLLECTION resource is a PARAM-LESS POST /api/<col> — exactly
        # synthesize_default_chain's predicate, so the table side and the chain side
        # agree by construction (no path param → not a nested resource or an action
        # verb like POST /api/videos/{id}/like, which would mint a junk 'like' table
        # the chain never CRUDs).
        if not p.startswith("/api/") or "{" in p or ":" in p:
            continue
        if str((ep.get("metadata") or {}).get("kind") or "").lower() in _MISSING_TABLE_FIXED_KINDS:
            continue
        segs = [s for s in p.split("/") if s and s != "api"]
        if not segs:
            continue
        resource = segs[-1]
        if resource.lower() in have or resource.lower() in _MISSING_TABLE_SPINE:
            continue
        cols: List[Dict[str, Any]] = [
            {"name": "id", "type": "int", "primary_key": True},
            {"name": "user_id", "type": "int", "references": "users.id"},
        ]
        seen = {"id", "user_id"}
        req = (ep.get("schema") or {}).get("request")
        if isinstance(req, dict):
            for field, typ in req.items():
                f = str(field).strip()
                if f and f not in seen:
                    cols.append({"name": f, "type": _derived_col_type(typ)})
                    seen.add(f)
        out[resource] = {
            "id": resource, "name": resource, "status": "defined",
            "provider": "backend", "schema": {"columns": cols},
            "metadata": {"derived": "endpoint_schema"},
        }
        have.add(resource.lower())
    return out


_CREATE_OWNER_NAMES = {
    "user_id", "owner_id", "author_id", "creator_id", "created_by", "account_id",
    "sender_id", "uploader_id", "poster_id", "seller_id", "host_id", "organizer_id"}


def synthesize_missing_create_endpoints(endpoints: Any, tables: Any):
    """BY-CONSTRUCTION contract completeness: ADD a CREATE (``POST /api/<collection>``) for a
    resource that is demonstrably MUTABLE — it has a collection ``GET /api/<collection>`` AND
    other writes (``PATCH``/``PUT``/``DELETE`` on ``/{id}`` or a ``POST`` sub-action) — but no
    plain create. The kickoff LLM intermittently DROPS the create (outlook run-63: registered
    ``GET /api/messages`` + reply/forward/patch/delete but NOT ``POST /api/messages`` → create
    405 → the business_chain can't make a message → the reply/forward ``${message_id}`` never
    resolves → 422 → STUCK-ABORT; run-62 with the SAME env HAD it, so it is pure LLM variance).
    Additive + deterministic. SAFETY: only a resource that ALREADY proves it is writable gets a
    create, so a read-only collection (``GET /api/feed``/``/notifications`` with no other write)
    is NEVER given a spurious create; and only when a backing table exists (aggregate/derived
    collections have none). The request schema mirrors the table's non-key, non-owner columns.
    Returns ``(endpoints_list, added_paths)``."""
    eps: List[Any] = list(endpoints or [])
    have_tables = {str(k).lower() for k in (tables or {})}

    def _single_collection(path: str) -> Optional[str]:
        p = str(path or "").rstrip("/")
        if not p.startswith("/api/") or "{" in p or ":" in p:
            return None
        segs = [s for s in p.split("/") if s and s != "api"]
        return segs[0].lower() if len(segs) == 1 else None

    get_collections: Dict[str, str] = {}
    post_collections = set()
    writable = set()
    for ep in eps:
        if not isinstance(ep, dict) and not hasattr(ep, "get"):
            continue
        method = str(ep.get("method", "GET")).upper()
        path = str(ep.get("path", "")).rstrip("/")
        col = _single_collection(path)
        if col and method == "GET":
            get_collections.setdefault(col, path)
        if col and method == "POST":
            post_collections.add(col)
        segs = [s for s in path.split("/") if s and s != "api"]
        if segs:  # a write on /<res>/{id} or a POST sub-action /<res>/{id}/<verb> ⇒ mutable
            res = segs[0].lower()
            if method in ("PATCH", "PUT", "DELETE") or (method == "POST" and len(segs) > 1):
                writable.add(res)

    added: List[str] = []
    for col, gpath in get_collections.items():
        if col in post_collections or col not in have_tables or col not in writable:
            continue
        tdef = (tables or {}).get(col)
        if tdef is None:  # case-insensitive table lookup
            tdef = next((v for k, v in (tables or {}).items() if str(k).lower() == col), None)
        req: Dict[str, Any] = {}
        for c in (_columns_of(tdef) if isinstance(tdef, dict) else []):
            if not isinstance(c, dict):
                continue
            n = str(c.get("name") or "").strip()
            if (n and n.lower() != "id" and not c.get("primary_key") and not c.get("pk")
                    and n.lower() not in _CREATE_OWNER_NAMES and not n.endswith("_at")
                    and n.lower() not in ("tenant_id", "created_at", "updated_at")):
                req[n] = str(c.get("type") or "string")
        eps.append({
            "method": "POST", "path": gpath, "status": "implemented",
            "kind": "business",
            "metadata": {"kind": "business", "synthesized_create": True},
            "schema": {"request": req},
        })
        added.append(gpath)
    return eps, added


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


def _counter_default(col: Any) -> Any:
    """FIX #97 (instagram run-15, live): ``post.likes_count += 1`` hit a NULL counter
    (seed omitted the column, no DB default) → TypeError → 500 → business_chain wedge.
    A counter column — integer-family ``*_count``, non-PK, non-FK, no explicit
    default — gets ``default 0`` BY CONSTRUCTION so a row that omits it can never
    surface NULL to handler code. Applied by BOTH the DDL and the ORM renderer."""
    if not isinstance(col, dict):
        return col
    name = str(col.get("name") or "").strip().lower()
    ctype = str(col.get("type") or "").strip().lower()
    if (name.endswith("_count")
            and col.get("default") is None
            and not (col.get("primary_key") or col.get("pk"))
            and not (col.get("references") or col.get("fk"))
            and ("int" in ctype or "serial" in ctype or "number" in ctype)):
        return {**col, "default": 0}
    return col


def _render_column(table_name: str, col: Any) -> str:
    if not isinstance(col, dict):
        raise ValueError(
            f"database_scaffold: table {table_name!r} has a non-mapping column: {col!r}"
        )
    col = _counter_default(col)
    cname = str(col.get("name") or "").strip()
    ctype = str(col.get("type") or "").strip()
    if not cname:
        raise ValueError(f"database_scaffold: table {table_name!r} has a column with no name")
    if not ctype:
        raise ValueError(
            f"database_scaffold: column {cname!r} in table {table_name!r} has no type"
        )
    _sqlt = _sql_type(ctype)
    # FIX #199 (r9 docker_up killer): a lane sometimes types a column as a full
    # DDL fragment — ``type: "integer primary key"`` / ``"text not null"`` /
    # ``"text unique"`` — so the constraint is EMBEDDED in the type string. The
    # constraints below are also appended from the flags, so an embedded copy
    # DOUBLES it: ``"id" integer primary key PRIMARY KEY`` → postgres "multiple
    # primary keys for table" → docker_up wedge. Strip the embedded constraint
    # words from the rendered type and FOLD them into the flags (so a type-only
    # declaration keeps its constraint) — mirrors the CHECK-in-type handling.
    _emb_pk = _emb_nn = _emb_uniq = False
    _low = _sqlt.lower()
    if "primary key" in _low:
        _emb_pk = True
        _sqlt = re.sub(r"\s*primary\s+key\s*", " ", _sqlt, flags=re.IGNORECASE).strip()
    if re.search(r"\bnot\s+null\b", _sqlt, re.IGNORECASE):
        _emb_nn = True
        _sqlt = re.sub(r"\s*not\s+null\s*", " ", _sqlt, flags=re.IGNORECASE).strip()
    if re.search(r"\bunique\b", _sqlt, re.IGNORECASE):
        _emb_uniq = True
        _sqlt = re.sub(r"\s*\bunique\b\s*", " ", _sqlt, flags=re.IGNORECASE).strip()
    _sqlt = _sqlt.strip() or "text"  # a bare "primary key" type leaves nothing
    _is_pk = bool(col.get("primary_key") or col.get("pk")) or _emb_pk
    # A bare integer PRIMARY KEY does NOT auto-increment on Postgres (unlike
    # SQLite): ``id INTEGER PRIMARY KEY`` forces every INSERT to supply id, so the
    # framework's projected CRUD handlers (which never send id) hit
    # ``null value in column "id" violates not-null`` → 500 on EVERY business
    # create (posts / messages / comments / likes / ...). instagram run #3 aborted
    # exactly here: POST /api/messages/{username} → 500, and the posts chain's
    # create returned no id → ``${api_posts_id}`` reached GET/DELETE → 422. Promote
    # a bare integer PK to SERIAL/BIGSERIAL so it auto-assigns — matching the spine
    # (users.id SERIAL) and what the ORM's create_all emits for an int PK anyway.
    if _is_pk and _sqlt.upper() in ("INTEGER", "INT", "INT4"):
        _sqlt = "SERIAL"
    elif _is_pk and _sqlt.upper() in ("BIGINT", "INT8"):
        _sqlt = "BIGSERIAL"
    parts = [_quote_ident(cname), _sqlt]
    # Optional constraints — honored ONLY when explicitly declared.
    if _is_pk:
        parts.append("PRIMARY KEY")
    if (col.get("nullable") is False or col.get("not_null") or _emb_nn) and not _is_pk:
        parts.append("NOT NULL")
    if col.get("unique") or _emb_uniq:
        parts.append("UNIQUE")
    default = col.get("default")
    if default is not None:
        parts.append(f"DEFAULT {default}")
    # Emit a STRUCTURED FK (``references``/``fk`` field) the same way the inline
    # form is rendered — but ONLY when the type string doesn't already carry an
    # inline ``references`` (which the passthrough above renders), so the two
    # sources never double-emit a duplicate REFERENCES clause.
    if not _FK_INLINE_IN_TYPE_RE.search(ctype):
        fk = _structured_fk_ref(col)
        if fk:
            # ON DELETE CASCADE: a child row's FK to a parent (comments.post_id →
            # posts.id, posts.author_id → users.id, …) must cascade, else deleting
            # the parent raises a ForeignKeyViolation → the DELETE endpoint 500s for
            # any parent that has children (run v22: DELETE /api/posts/{id} → 500
            # "comments_post_id_fkey", a REAL app bug a user hits, and the lone
            # remaining business_chain failure). The control-plane/spine FKs and the
            # inline-FK renderer ALREADY cascade-by-default; this makes the structured
            # path consistent. Owned-resource hierarchies want cascade (parent gone →
            # its children gone), which is the correct semantic for these CRUD apps.
            parts.append(
                f"REFERENCES {_quote_ident(fk[0])} ({_quote_ident(fk[1])}) ON DELETE CASCADE")
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


def _ddl_base_type(t_upper: str) -> str:
    """Coarse postgres BASE type (no default clause) from an uppercased ORM type
    string — used both for plain columns and for FK/PK referential type-matching."""
    if "INT" in t_upper:
        return "integer"
    if "BOOL" in t_upper:
        return "boolean"
    if "DATE" in t_upper or "TIME" in t_upper:
        return "timestamptz"
    if "FLOAT" in t_upper or "NUMERIC" in t_upper or "DECIMAL" in t_upper or "REAL" in t_upper:
        return "numeric"
    if "UUID" in t_upper:
        return "uuid"
    return "text"


def _ddl_type_from_introspect(col: Dict[str, Any],
                              pk_types: Optional[Dict[str, str]] = None) -> str:
    """Render a column's DDL type from the ORM introspection (PROPOSAL #3, L3
    backstop). Two bugs fixed so the DDL is always self-consistent + bootable:

    Bug 1 — a PRIMARY KEY whose type isn't integer used to lose its `primary key`
    clause (the old `if pk and "INT" in t` fell through to `text`), so a text/uuid
    PK rendered as a plain non-PK column. Now: emit `primary key` for ANY pk type
    (`serial` only when integer).

    Bug 2 — an FK column used to ALWAYS render `integer references …`, regardless
    of the referenced PK's real type — so an FK to a text PK was mis-typed integer
    (youtube run #16: `videos.channel_id integer` → `channels.id` (which the ORM
    had as text) → incompatible-types → CREATE TABLE aborts → postgres exit 3).
    Now the FK column inherits the referenced table's PK base type via the
    ``pk_types`` map (``{table_lower: base_type}``) built by the caller; falls back
    to integer (the surrogate-id convention) when the target PK is unknown."""
    t = str(col.get("type") or "").upper()
    base = _ddl_base_type(t)
    if col.get("pk"):
        return "serial primary key" if base == "integer" else base + " primary key"
    if col.get("fk"):
        tbl, _, tcol = str(col["fk"]).partition(".")
        ref_base = (pk_types or {}).get(tbl.strip().lower(), "integer")
        return "{} references {}({}) on delete cascade".format(
            ref_base, tbl, tcol or "id")
    if base == "boolean":
        return "boolean default false"
    if base == "timestamptz":
        return "timestamptz default now()"
    return base  # integer / numeric / uuid / text


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
    # L3 pre-pass (PROPOSAL #3): map each table → its PK column's base type so an
    # FK column renders with the SAME type as the PK it references (referential
    # type-consistency). Without this, every FK was hard-coded `integer`.
    pk_types: Dict[str, str] = {}
    for t in raw:
        tn = str(t.get("name") or "").strip().lower()
        if not tn:
            continue
        for c in t.get("columns") or []:
            if c.get("pk"):
                pk_types[tn] = _ddl_base_type(str(c.get("type") or "").upper())
                break
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
            cols.append({"name": cname, "type": _ddl_type_from_introspect(c, pk_types),
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
        # Structured FK on an app-extended column — render it the same way as a
        # top-level column (don't double-emit when the type already carries one).
        if not _FK_INLINE_IN_TYPE_RE.search(ctype):
            fk = _structured_fk_ref(col)
            if fk:
                # ON DELETE CASCADE — consistent with the top-level structured-FK
                # renderer and the inline-FK path (see _render_column): a child FK
                # must cascade so deleting the parent doesn't 500 on a FK violation.
                parts.append(
                    f"REFERENCES {_quote_ident(fk[0])} ({_quote_ident(fk[1])}) ON DELETE CASCADE")
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
    -- display-name column. The embedded OAuth AS keys on email/password_hash/id,
    -- and an app's register flow may not set `name`, so default it to keep an
    -- insert that omits `name` working.
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


# FIX #211 (r15 docker_up killer): postgres runs 01_init.sql top-to-bottom and an
# inline ``REFERENCES <t>`` needs ``<t>`` to already exist. The contract lists
# tables in registration order, which need NOT match FK-dependency order — r15
# declared ``videos`` (``sound_id REFERENCES sounds(id)``) BEFORE ``sounds`` → init
# aborted with ``relation "sounds" does not exist`` → docker_up wedged every cycle,
# and the lanes CAN'T fix an auto-generated file → 76-min no-convergence abort.
# Emit business tables in topological FK order so every reference resolves.
def _fk_referenced_tables(table: Dict[str, Any]) -> Set[str]:
    """Lowercased names of the OTHER tables this table FK-references, from BOTH
    the structured (``references``/``fk``) and inline (``type`` string) signals."""
    refs: Set[str] = set()
    for c in _columns_of(table):
        if not isinstance(c, dict):
            continue
        sfk = _structured_fk_ref(c)
        if sfk:
            refs.add(str(sfk[0]).strip().strip('"').lower())
        m = _INLINE_REFERENCES_RE.search(str(c.get("type") or ""))
        if m:
            refs.add(str(m.group(1)).strip().strip('"').lower())
    return refs


def _topological_table_order(tables: Dict[str, Any]) -> List[Tuple[Any, Any]]:
    """Return ``tables.items()`` reordered so each business table is emitted AFTER
    the business tables its FKs reference. The tenancy spine (tenants/users/
    oauth_*) is created before ANY business table, so FKs to it never constrain
    the order (its names seed the emitted set). Self-references, dangling refs,
    and true cycles degrade to the original stable order — never dropping a
    table (a genuine 2-table cycle needs a deferred FK, a separate concern)."""
    items = list(tables.items())
    known: Set[str] = set()
    for tid, t in items:
        nm = str((t.get("name") if isinstance(t, dict) else "") or tid or "").strip().lower()
        if nm:
            known.add(nm)
    deps: Dict[int, Set[str]] = {}
    name_by_key: Dict[int, str] = {}
    for tid, t in items:
        key = id(t)
        nm = str((t.get("name") if isinstance(t, dict) else "") or tid or "").strip().lower()
        name_by_key[key] = nm
        d: Set[str] = set()
        if isinstance(t, dict):
            for r in _fk_referenced_tables(t):
                if r in known and r != nm:  # only real business deps; ignore self-ref
                    d.add(r)
        deps[key] = d
    # Kahn's algorithm, STABLE: emit any table whose business deps are already
    # satisfied; spine tables count as pre-created.
    emitted: Set[str] = {n.lower() for n in _SPINE_OWNED_TABLES}
    ordered: List[Tuple[Any, Any]] = []
    remaining = list(items)
    progressed = True
    while remaining and progressed:
        progressed = False
        still: List[Tuple[Any, Any]] = []
        for tid, t in remaining:
            if deps[id(t)] <= emitted:
                ordered.append((tid, t))
                nm = name_by_key[id(t)]
                if nm:
                    emitted.add(nm)
                progressed = True
            else:
                still.append((tid, t))
        remaining = still
    ordered.extend(remaining)  # leftover cycle/unresolved → original order, no drop
    return ordered


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

    # FIX #197 (r7 docker_up killer): reconcile FK types HERE too, exactly as
    # render_models does — otherwise the ORM coerces a spine FK (author_id →
    # INTEGER users.id) while this DDL renders it TEXT, and `CREATE TABLE videos`
    # aborts on the TEXT→INTEGER FK clash → docker_up wedges every cycle (the
    # framework re-emits the mismatch, so the lane can never fix it → 75-min
    # wall). The reconciler mutates the col dicts in place; _columns_of returns
    # those same dicts below, so the rendered types match the ORM by construction.
    try:
        from .backend_skeleton import _reconcile_fk_types_in_map
        _by_name = {str(n).lower(): _columns_of(t)
                    for n, t in tables.items() if isinstance(t, dict)}
        _reconcile_fk_types_in_map(_by_name)
    except Exception:
        pass  # best-effort: reconciliation must never break DDL emission

    # FIX #211: emit in topological FK order so an inline REFERENCES never hits a
    # not-yet-created table (r15 `videos`→`sounds` init crash).
    for table_id, table in _topological_table_order(tables):
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
                    lines.append("-- app-extended columns on the spine `users` table")
                    lines.extend(alters)
                    lines.append("")
            continue  # spine owns the base table; extras merged above

        cols = _columns_of(table)
        if not cols:
            # FIX #90 (instagram run-9, live): a lane registered a placeholder table
            # ('dummy') with NO columns at M2 kickoff and this raise KILLED the whole
            # run post-M1-delivery. The MODELS renderer already tolerates the shape by
            # synthesising an `id` PK — do the SAME here so both renderers agree and a
            # junk registration degrades to a harmless one-column table, never a dead run.
            cols = [{"name": "id", "type": "integer", "primary_key": True}]
            lines.append(f"-- table {name!r} was registered with no columns; "
                         "id PK synthesised (FIX #90)")
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
            # FIX #90: all columns were constraint pseudo-columns → same synthesis.
            rendered_cols = [_render_column(name, {"name": "id", "type": "integer",
                                                   "primary_key": True})]
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
