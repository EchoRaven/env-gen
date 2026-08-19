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
    # #403 (ORM/DDL parity, extends #396): the ORM renderer maps ``money`` -> SQLAlchemy
    # Numeric, but the DDL used to pass ``money`` through as the native postgres MONEY type
    # -> an ORM(Numeric)/DDL(money) type divergence (the #393 class) on any currency column
    # (plausible in a streaming/billing app). Postgres MONEY is also discouraged (locale-
    # dependent formatting, lossy). Render it as NUMERIC so both renderers agree AND currency
    # is stored correctly.
    "money": "NUMERIC",
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
    # #969: drop the contract-only ``nullable`` marker before the alias lookup, so
    # ``"string nullable"`` resolves to TEXT instead of reaching the DDL verbatim. Only this
    # known modifier word is removed — legitimate MULTI-TOKEN types (``double precision``,
    # ``timestamp with time zone``, ``character varying``) must keep every token, so a
    # "first token wins" normalization would be wrong here.
    t = _INLINE_NULLABLE_RE.sub("", t).strip()
    # #988: the OPTIONAL suffix. Spec and TypeScript-ish contracts write `integer?` /
    # `text?` for "nullable", and rendering it verbatim gives postgres
    # `"duration_minutes" INTEGER?` -> `syntax error at or near "?" at character 255`,
    # initdb dies, docker_up fails, the run stalls in validation. Same family as this
    # function's `nullable` strip directly above — a type-position word that means
    # nullability, not a type.
    #
    # It took three sessions to name because the `?` never survives in an artifact (the
    # DDL is regenerated between validations) and the log truncated the STATEMENT before
    # reaching character 255. #973 printed the statement, #987 widened the cap to reach the
    # offset, and the column fell out by counting characters.
    t = _OPTIONAL_SUFFIX_988.sub("", t).strip()
    return _TYPE_ALIASES.get(t.lower(), t)


# SQL default values that are literals / keywords / functions and must pass through UNQUOTED.
_SQL_DEFAULT_KEYWORDS = frozenset({
    "true", "false", "null", "current_timestamp", "current_date", "current_time",
    "localtimestamp", "localtime", "current_user", "session_user",
})
_NUMERIC_DEFAULT_RE = re.compile(r"^-?\d+(\.\d+)?$")


def _quote_default(value: Any) -> str:
    """#404: render a column DEFAULT value as valid SQL. A numeric / already-quoted /
    boolean-or-NULL keyword / SQL-function (contains ``(`` — now(), gen_random_uuid()) /
    known-keyword default passes through; a BARE WORD text default (``status text default
    active``) is SINGLE-QUOTED — else postgres reads ``active`` as an identifier (``column
    "active" does not exist``) and initdb FAILS -> docker_up wedge (the #372/#382/#383
    initdb-failure class). Mirrors the ORM renderer's default quoting so create_all + the DDL
    agree."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    s = str(value).strip()
    if not s:
        return "''"
    if (s[0] in ("'", '"')                       # already quoted
            or s.lower() in _SQL_DEFAULT_KEYWORDS  # true/false/null/current_timestamp/...
            or "(" in s                          # a function call: now(), gen_random_uuid()
            or _NUMERIC_DEFAULT_RE.match(s)):    # a number (incl. negative/decimal)
        return s
    return "'" + s.replace("'", "''") + "'"


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
# #969: ``nullable`` is a CONTRACT word, not SQL. Kickoff/ORM contracts describe a column as
# ``{"logo_url": "string nullable"}``; postgres has no such keyword (nullability is the
# DEFAULT, expressed by the ABSENCE of NOT NULL). Left in the type string it defeats the
# alias lookup — ``"string nullable"`` misses the table that would have mapped ``string`` ->
# TEXT — and both tokens reach the DDL verbatim: ``"logo_url" string nullable,`` ->
# `syntax error at or near "nullable"` -> initdb fails -> the db container dies -> docker_up
# FAILS. Same class as the inline ``check`` handled in _sql_type and the four modifiers
# promoted below; ``\bnot\s+null\b`` deliberately does NOT match it, so the two cannot collide.
_INLINE_NULLABLE_RE = re.compile(r"\bnullable\b", re.IGNORECASE)
# #988: a trailing `?` in a TYPE position is the optional/nullable marker.
# The marker terminates the TYPE TOKEN, which is not always the end of the string:
# r160 shipped both `integer?` and `integer? DEFAULT 0`. Requires a word char before
# and whitespace-or-end after, so `varchar(3?)` is left alone.
_OPTIONAL_SUFFIX_988 = re.compile(r"(?<=\w)\s*\?(?=\s|$)")

# #989: `default_now` and friends — the underscore spelling `\bdefault\b` cannot see.
_DEFAULT_UNDERSCORE_MAP_989 = {
    "now": "NOW()", "current_timestamp": "CURRENT_TIMESTAMP",
    "utcnow": "NOW()", "uuid": "gen_random_uuid()",
}
_DEFAULT_UNDERSCORE_989 = re.compile(
    r"\bdefault_(" + "|".join(sorted(_DEFAULT_UNDERSCORE_MAP_989, key=len, reverse=True)) + r")\b",
    re.IGNORECASE)
_INLINE_REFERENCES_RE = re.compile(
    r"\breferences\s+(\w+)\s*(?:\(\s*(\w+)\s*\)|\.\s*(\w+))", re.IGNORECASE
)


def _promote_inline_modifiers(col: Dict[str, Any]) -> Dict[str, Any]:
    """#396: promote inline modifiers in a column dict's ``type`` string (``primary key`` /
    ``not null`` / ``unique`` / ``references x(y)``) to STRUCTURED flags, so the column
    projects IDENTICALLY through BOTH the DDL renderer (database_scaffold — honours the type
    string directly) and the ORM renderer (backend_skeleton — keys nullable/pk/unique/FK off
    STRUCTURED flags). Previously this promotion ran ONLY for the flat-map shape (via
    _column_from_flat), so a STRUCTURED dict whose ``type`` carried the constraint inline —
    the LLM routinely emits ``{"name":"name","type":"text not null"}`` — got ``TEXT NOT NULL``
    in the DDL but a NULLABLE ORM Column (the #393 root; likewise phantom-``id`` PK for a
    non-id inline PK, and dropped inline FKs). Copy-on-write (never mutates the caller's dict);
    idempotent; honours already-set structured flags; the full ``type`` string is preserved
    for the DDL renderer (which de-dups an already-structured NOT NULL/PK)."""
    if not isinstance(col, dict):
        return col
    spec = str(col.get("type") or "")
    if not spec:
        return col
    out = dict(col)
    if _INLINE_PK_RE.search(spec) and not (out.get("primary_key") or out.get("pk")):
        out["primary_key"] = True
    if (_INLINE_NOTNULL_RE.search(spec) and out.get("nullable") is not False
            and not out.get("not_null")):
        out["not_null"] = True
    if _INLINE_UNIQUE_RE.search(spec) and not out.get("unique"):
        out["unique"] = True
    # #969: an inline ``nullable`` states the column IS optional. Promote it so the ORM
    # renderer agrees with the DDL (the #393 parity rule), but never let it overrule an
    # explicit NOT NULL — a contradictory ``"text not null nullable"`` keeps the stricter read.
    if (_INLINE_NULLABLE_RE.search(spec) and "nullable" not in out
            and not out.get("not_null") and not _INLINE_NOTNULL_RE.search(spec)):
        out["nullable"] = True
    # #988: `integer?` means the same thing as `integer nullable`. Stripping the marker in
    # `_sql_type` alone would render valid SQL that says the OPPOSITE — a NOT NULL column
    # where the contract asked for an optional one — so promote it here too, under the same
    # guards: never overrule an explicit NOT NULL, never overwrite a stated `nullable`.
    if (_OPTIONAL_SUFFIX_988.search(spec) and "nullable" not in out
            and not out.get("not_null") and not _INLINE_NOTNULL_RE.search(spec)):
        out["nullable"] = True
    if not (out.get("references") or out.get("fk")):
        m = _INLINE_REFERENCES_RE.search(spec)
        if m:
            out["references"] = "{}({})".format(m.group(1), m.group(2) or m.group(3))
    return out


def _column_from_flat(name: str, type_spec: Any) -> Dict[str, Any]:
    """Build a canonical column dict from a flat-map ``name: "type string"`` entry,
    promoting inline modifiers to structured flags via _promote_inline_modifiers."""
    return _promote_inline_modifiers({"name": str(name), "type": str(type_spec or "").strip()})


def normalize_columns(schema: Any) -> List[Any]:
    """Coerce ANY accepted table-schema shape to a canonical column LIST:
      * a ``{"columns": [...]}`` dict           → its ``columns`` list (as-is)
      * a bare ``[{"name","type"}, ...]`` list  → itself (as-is)
      * a flat map ``{col: "type string"}``     → ``[{"name","type", …}]`` with
        inline modifiers promoted to structured flags (see _column_from_flat)
    Returns [] for anything unrecognized (an empty/None schema).

    #396: inline modifiers (``not null``/``primary key``/``unique``/``references``) in a
    column's ``type`` string are promoted to structured flags for EVERY shape (not just the
    flat map), so the ORM renderer's nullable/pk/unique/FK match the DDL — the #393 root."""
    if isinstance(schema, list):
        return [_promote_inline_modifiers(c) if isinstance(c, dict) else c for c in schema]
    if isinstance(schema, dict):
        cols = schema.get("columns")
        if isinstance(cols, list):
            return [_promote_inline_modifiers(c) if isinstance(c, dict) else c for c in cols]
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


# #853: was a fourth hand-listed copy of the fixed surface, identical to the three others and
# missing the same `control`/`control_plane`/`health`. Imported, not re-listed.
from .kickoff.contract import FIXED_ENDPOINT_KINDS as _MISSING_TABLE_FIXED_KINDS
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
    # Canonicalize table/resource names to snake_case for the "already tabled?" check:
    # an endpoint resource `my-list` (kebab, from POST /api/my-list) MUST recognize the
    # data-model table `my_list` (snake) as the same table. Without this a spurious
    # `my-list` table was synthesized → a SECOND `class MyList(Base)` in models.py that
    # `import *` shadowed (no profile_id) → GET/POST /api/my-list 500 → business_chain
    # wedge (netflix r1). Mirrors #367's projector-side hyphen normalization.
    def _canon(_s: Any) -> str:
        return str(_s).lower().replace("-", "_")
    have = {_canon(k) for k in out}
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
        resource = _canon(segs[-1])
        if resource in have or resource in _MISSING_TABLE_SPINE:
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
        if segs:  # #477: ONLY a DIRECT item mutation (PATCH/PUT/DELETE /<res>/{id}) proves the
            # resource is user-mutable ⇒ warrants a plain CREATE ("you can create X if you can
            # edit/delete X"). A POST SUB-ACTION (/<res>/{id}/<verb> — e.g. /titles/{id}/rating,
            # a rate/like/follow ACTION on a RELATED resource) does NOT imply the collection is
            # user-CREATABLE: it wrongly marked the READ-ONLY titles catalog 'writable' → a
            # spurious POST /api/titles the business_chain then tested → 400 → convergence churn
            # (r48/r51, never delivered). The outlook messages case is preserved — it has
            # PATCH/DELETE /messages/{id} (direct mutations), so it still gets its create.
            res = segs[0].lower()
            if method in ("PATCH", "PUT", "DELETE"):
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
    data, alternate location/shape, not an invented default.

    #396: inline modifiers in a column's ``type`` string (``not null`` / ``primary key`` /
    ``unique`` / ``references``) are promoted to structured flags for EVERY shape here — this
    is the single chokepoint BOTH the ORM renderer (render_models/_models_meta) and the DDL
    renderer read, so promoting here makes the ORM's nullable/pk/unique/FK match the DDL (the
    #393 root: a canonical ``{"columns":[{"type":"text not null"}]}`` used to return raw, so
    the ORM Column stayed nullable while the DDL emitted NOT NULL)."""
    schema = table.get("schema")
    if isinstance(schema, dict) and isinstance(schema.get("columns"), list):
        return [_promote_inline_modifiers(c) if isinstance(c, dict) else c
                for c in schema["columns"]]
    if isinstance(table.get("columns"), list):
        return [_promote_inline_modifiers(c) if isinstance(c, dict) else c
                for c in table["columns"]]
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


def _col_is_pk(col: Any) -> bool:
    """#517 — True if a real column is a PRIMARY KEY (flag or inline in its type string).
    Mirrors _render_column's _is_pk detection, for composite-PK grouping in render_schema_sql."""
    if not isinstance(col, dict):
        return False
    if col.get("primary_key") or col.get("pk"):
        return True
    t = str(col.get("type") or "")
    return bool(re.search(r"primary[\s_]+key", t, re.I) or re.search(r"\bpk\b", t, re.I))


def _render_column(table_name: str, col: Any, suppress_pk: bool = False) -> str:
    """#517: suppress_pk renders a PK-flagged column WITHOUT its own ``PRIMARY KEY`` (and without
    SERIAL promotion) so a COMPOSITE primary key can be emitted as one table-level constraint — a
    per-column PK on each of >=2 columns is invalid ("multiple primary keys not allowed")."""
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
    # Match both the SQL keyword form ("primary key" / "not null") AND the ORM/underscore
    # shorthand the LLM emits ("primary_key" / "not_null") — the latter is not valid SQL
    # ("id" int primary_key → postgres syntax error → initdb exit(3) → docker_up wedge,
    # netflix r1). ``[\s_]+`` covers both.
    # "primary key" / "primary_key" / the bare "PK" abbreviation (netflix r7:
    # `"id" Integer PK` → syntax error at "PK" → initdb exit(3)). `\bpk\b` catches the
    # abbreviation; postgres types never contain a standalone "pk" token.
    if re.search(r"primary[\s_]+key", _low) or re.search(r"\bpk\b", _low):
        _emb_pk = True
        _sqlt = re.sub(r"\s*primary[\s_]+key\s*", " ", _sqlt, flags=re.IGNORECASE)
        _sqlt = re.sub(r"\s*\bpk\b\s*", " ", _sqlt, flags=re.IGNORECASE).strip()
    if re.search(r"\bnot[\s_]+null\b", _sqlt, re.IGNORECASE):
        _emb_nn = True
        _sqlt = re.sub(r"\s*not[\s_]+null\s*", " ", _sqlt, flags=re.IGNORECASE).strip()
    if re.search(r"\bunique\b", _sqlt, re.IGNORECASE):
        _emb_uniq = True
        _sqlt = re.sub(r"\s*\bunique\b\s*", " ", _sqlt, flags=re.IGNORECASE).strip()
    # Shorthand FK in the TYPE string ("int fk users.id" / "int foreign_key users.id"):
    # postgres has no bare `fk` keyword → syntax error → initdb exit(3). Extract the
    # (table, col) and render a proper REFERENCES in the FK section below (that path only
    # recognizes `references` / the structured fk field). Accepts `.` or `(` separators.
    _emb_fk = None
    _m_fk = re.search(r"\b(?:fk|foreign[\s_]+key)\s+(\w+)\s*[.(]\s*(\w+)\s*\)?", _sqlt, re.IGNORECASE)
    if _m_fk:
        _emb_fk = (_m_fk.group(1), _m_fk.group(2))
        _sqlt = (_sqlt[:_m_fk.start()] + " " + _sqlt[_m_fk.end():]).strip()
    # (netflix docker_up killer) a column typed with an EMBEDDED default
    # ("integer default 0") DOUBLES when the `default` flag (or _counter_default's
    # forced 0) is also appended below → ``"view_count" INTEGER DEFAULT 0 DEFAULT 0``
    # → postgres "multiple default values specified for column" → docker_up wedge.
    # Mirror the #199 PK/NOT-NULL/UNIQUE handling: strip the embedded DEFAULT and
    # fold it into the flag so exactly one DEFAULT is emitted. Runs AFTER the
    # constraint strips above, so only the default value remains at the tail.
    # #989: the UNDERSCORE spelling. ORM-ish contracts write `timestamp default_now`, and
    # `\bdefault\b` cannot see it — `_` is a word character, so `default_now` is one token
    # and the extraction below never fires. It reaches postgres verbatim:
    # `syntax error at or near "default_now" at character 202` (r149, recovered from
    # git history at 33894f8 — "created_at" timestamp default_now).
    #
    # Third member of the same family as #969 (`nullable`) and #988 (`?`): a MODIFIER
    # sitting in the type position that is not SQL. Only the spellings whose intent is
    # unambiguous are translated; an unknown `default_<x>` is deliberately left to fail
    # loudly rather than be guessed into a silently wrong default value.
    _sqlt = _DEFAULT_UNDERSCORE_989.sub(
        lambda m: "default " + _DEFAULT_UNDERSCORE_MAP_989[m.group(1).lower()], _sqlt)
    _emb_default = None
    _m_def = re.search(r"\bdefault\b\s+(.+)$", _sqlt, re.IGNORECASE)
    if _m_def:
        _emb_default = _m_def.group(1).strip()
        _sqlt = _sqlt[:_m_def.start()].strip()
    _sqlt = _sqlt.strip() or "text"  # a bare "primary key" type leaves nothing
    # Re-alias the BASE type AFTER the embedded constraints were stripped: _sql_type
    # aliased the FULL string, so "string not null" missed the "string"→TEXT alias and,
    # once NOT NULL was stripped above, left a bare invalid `string` (netflix r8:
    # `type "string" does not exist` → initdb exit 3). Unknown types pass through.
    _sqlt = _TYPE_ALIASES.get(_sqlt.lower(), _sqlt)
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
    if _is_pk and not suppress_pk and _sqlt.upper() in ("INTEGER", "INT", "INT4"):
        _sqlt = "SERIAL"
    elif _is_pk and not suppress_pk and _sqlt.upper() in ("BIGINT", "INT8"):
        _sqlt = "BIGSERIAL"
    parts = [_quote_ident(cname), _sqlt]
    # Optional constraints — honored ONLY when explicitly declared.
    if _is_pk and not suppress_pk:
        parts.append("PRIMARY KEY")
    # #517: a composite-PK column (per-column PK suppressed) is still implicitly NOT NULL.
    if ((col.get("nullable") is False or col.get("not_null") or _emb_nn) and not _is_pk) \
            or (_is_pk and suppress_pk):
        parts.append("NOT NULL")
    if col.get("unique") or _emb_uniq:
        parts.append("UNIQUE")
    default = col.get("default")
    if default is None and _emb_default is not None:
        default = _emb_default  # type-only default (col carried it in the type string)
    # #407 (FW_DEBUG-surfaced on netflix r5): a NOT NULL column with NO default is a LANDMINE —
    # the agent seed, the projected create, and the profile autocreate routinely OMIT it, so
    # postgres NotNullViolations DROP the row (r5: all 7 profiles + episodes dropped on null
    # created_at -> no profiles -> per-profile chains 404 -> business_chain wedge) or 500 the
    # insert. For the types with an UNAMBIGUOUS safe default, supply it BY CONSTRUCTION (mirrors
    # _ddl_type_from_introspect): NOT NULL timestamp -> now(), date -> CURRENT_DATE, time ->
    # CURRENT_TIME, boolean -> false. Text/int/numeric are left alone (no universal default —
    # a required name/email must stay required; no data invented).
    _nn = (col.get("nullable") is False or col.get("not_null") or _emb_nn) and not _is_pk
    if default is None and _nn:
        _bt = _sqlt.upper()
        if "TIMESTAMP" in _bt:
            default = "now()"
        elif _bt == "DATE":
            default = "CURRENT_DATE"
        elif _bt == "TIME":
            default = "CURRENT_TIME"
        elif "BOOL" in _bt:
            default = "false"
    if default is not None:
        parts.append(f"DEFAULT {_quote_default(default)}")
    # Emit a STRUCTURED FK (``references``/``fk`` field) the same way the inline
    # form is rendered — but ONLY when the type string doesn't already carry an
    # inline ``references`` (which the passthrough above renders), so the two
    # sources never double-emit a duplicate REFERENCES clause.
    if not _FK_INLINE_IN_TYPE_RE.search(ctype):
        fk = _structured_fk_ref(col) or _emb_fk
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
# ``test_stated_invariants_have_an_enforcer_852`` so the manifest can never silently diverge
# from the DDL the AS actually reads/writes.
#
# #852: that sentence used to name ``test_database_scaffold``, and **no such gate existed** —
# no test file referenced `SPINE_TABLE_RECORDS` or `_TENANCY_SPINE_SQL`. #788's shape, sharpened
# by naming the enforcer: a named test stops the next reader from checking. The claim's CONTENT
# was true (0 of 4 tables had drifted); only its mechanism was fictional.
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
        # #517: a COMPOSITE primary key (>=2 columns flagged PK — e.g. a junction table
        # title_genres(title_id PK, genre_id PK)) must be ONE table-level `PRIMARY KEY (a, b)`,
        # not a per-column `SERIAL PRIMARY KEY` on each (postgres: "multiple primary keys for
        # table not allowed" → initdb exit 3 → docker_up wedge, netflix r89). Detect it and render
        # those columns WITHOUT their own PK (a composite-PK FK column stays a plain int FK), then
        # emit the composite constraint. If one of the PK-flagged columns is 'id', treat 'id' as
        # the sole PK and DEMOTE the others (mis-marked FKs) — the common id+FK mis-modeling.
        # Skip when an explicit table-level PRIMARY KEY pseudo-constraint already exists.
        # Generalizes to every M:N join table; no product literals.
        _real_cols = [c for c in cols if not _is_constraint_pseudo_column(c)]
        _pk_cols = [c for c in _real_cols if _col_is_pk(c)]
        _has_tablevel_pk = any(
            _is_constraint_pseudo_column(c)
            and "primary" in str(c.get("name") or "").lower()
            for c in cols)
        _composite_pk = False
        _suppress_ids = set()
        if len(_pk_cols) >= 2 and not _has_tablevel_pk:
            _id_pk = next((c for c in _pk_cols
                           if str(c.get("name") or "").strip().lower() == "id"), None)
            if _id_pk is not None:
                _suppress_ids = {id(c) for c in _pk_cols if c is not _id_pk}  # id is PK; demote rest
            else:
                _composite_pk = True
                _suppress_ids = {id(c) for c in _pk_cols}
        for c in cols:
            if _is_constraint_pseudo_column(c):
                clause = _render_table_constraint(c)
                if clause:
                    constraint_lines.append(clause)
                continue  # unparseable pseudo-constraint → drop (don't break DDL)
            rendered_cols.append(_render_column(name, c, suppress_pk=(id(c) in _suppress_ids)))
        if _composite_pk:
            _pk_names = [str(c.get("name") or "").strip() for c in _pk_cols]
            constraint_lines.append(
                "    PRIMARY KEY (" + ", ".join(_quote_ident(n) for n in _pk_names if n) + ")")
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
    # #896: verify the ARTIFACT, not the input.
    #
    # ★ The first cut checked `if not tables:` — the argument that came IN. r152 proved why that
    # is worthless: `write_database_scaffold` was called with 12 tables, returned normally, this
    # reported "ok", and **no .sql file exists anywhere in that run tree** (r151 has three). The
    # producer-side check said fine while the consumer-side one (#891, in the backend skeleton)
    # correctly reported the DDL missing five minutes later.
    #
    # A check that reads its own input and calls it an output is the silent-degradation class this
    # whole session has been mining — built, this time, by the instrumentation meant to catch it.
    try:
        from .stage_contract import require_stage_output_891
        _landed = schema_sql.is_file() and schema_sql.stat().st_size > 0
        if not (tables or {}):
            require_stage_output_891(
                "database scaffold", "any registered table", present=False,
                detail="01_init.sql was written with ZERO tables — the app will start with an "
                       "empty database and every query will fail at runtime.")
        elif not _landed:
            require_stage_output_891(
                "database scaffold", f"{schema_sql}", present=False,
                detail=f"write_text() returned for {len(tables)} table(s) and the file is not on "
                       "disk — this is the 'write that does not land' class (r152).")
    except Exception:
        pass
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
