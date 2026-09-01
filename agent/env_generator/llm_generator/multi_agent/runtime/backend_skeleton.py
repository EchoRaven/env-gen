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

import keyword
import re
from urllib.parse import quote as _quote
import sys
from pathlib import Path
from typing import Iterable, Any, Dict, List, Mapping, Optional, Tuple

from .database_scaffold import _columns_of, _is_constraint_pseudo_column


def safe_column_name(name: str) -> str:
    """FIX #158 (gmrun6): map a column name to a valid, non-keyword Python IDENTIFIER
    usable as an ORM attribute — the single sanitize the whole dataset channel shares
    (render + requirements-binding + seed-key assembly), so the ORM attribute, the DB
    column, and the seed-dataset key stay equal and data still lands.

    A real dataset can carry a column named after a Python keyword (transit_lines.``from``
    = the OSM line origin) or a non-identifier (``2019``, ``a-b``). Rendered verbatim as an
    attribute (``from = Column(Text)``) it is a SyntaxError that breaks ``import models`` →
    the backend crashes on every boot (gmrun6 backend_health wedge). Rule: a hard keyword
    gets a trailing underscore (PEP 8: ``from``→``from_``, ``class``→``class_``); a non-
    identifier has its illegal characters replaced with ``_`` and a leading digit prefixed
    (``col_``); empty → ``col``. IDEMPOTENT (``from_`` stays ``from_``) so applying it at
    several stages never double-mangles."""
    s = str(name or "").strip()
    if not s:
        return "col"
    if s.isidentifier():
        return s + "_" if _needs_attr_suffix(s) else s
    s2 = re.sub(r"\W", "_", s)
    if s2 and s2[0].isdigit():
        s2 = "col_" + s2
    if not s2 or not s2.isidentifier():
        return "col"
    return s2 + "_" if _needs_attr_suffix(s2) else s2


# FIX #216: SQLAlchemy's Declarative API RESERVES a few instance-attribute names on a
# mapped class (``metadata`` = the MetaData object, ``registry`` = the mapper registry).
# A contract column named ``metadata`` renders ``metadata = Column(Text)`` and the mapper
# raises ``InvalidRequestError: Attribute name 'metadata' is reserved`` at class-body time
# → ``import models`` crashes → the backend never boots (found by a codegen stress-audit;
# ``metadata`` is a common column on posts/files/events). Treat these like keywords: suffix
# the ATTRIBUTE with ``_`` (the DB column keeps its real name, pinned positionally by
# render — see the ``attr != name`` branch), so the model maps and data still lands.
_SA_RESERVED_ATTRS = frozenset({"metadata", "registry"})


def _needs_attr_suffix(s: str) -> bool:
    return keyword.iskeyword(s) or s in _SA_RESERVED_ATTRS

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

# #1022: the identifiers may be QUOTED. `REFERENCES "users" ("id")` is valid SQL and is what
# a contract author writes about as often as the bare form — netflix r122 shipped
# `"user_id" TEXT REFERENCES "users" ("id")` against an integer `users.id`. Without the
# optional quotes this returned None, so `_fk_target` saw no FK, `_reconcile_fk_types_in_map`
# skipped the column, and the unbootable type survived to initdb. The quotes are optional, so
# every previously-matching form still matches unchanged.
_FK_RE = re.compile(
    r'references\s+"?([A-Za-z_]\w*)"?\s*(?:\(\s*"?(\w+)"?\s*\)|\.\s*"?(\w+)"?)',
    re.IGNORECASE)


def _class_name(table: str) -> str:
    """``user_posts`` → ``UserPosts``; singularise a trailing plural ``s``."""
    base = re.sub(r"[^A-Za-z0-9]+", "_", str(table)).strip("_")
    parts = [p for p in base.split("_") if p]
    if parts and parts[-1].endswith("s") and not parts[-1].endswith("ss"):
        parts[-1] = parts[-1][:-1]
    return "".join(p[:1].upper() + p[1:] for p in parts) or "Model"


# --- #1202: a sub-entity that OWNS other rows is per-user, whatever its shape ------------
# #1200 learns from the lane's own read filter, so it cannot help a run where the lane never
# wrote one — r1 and r27 ship `profiles` unscoped with no signal to learn from. A third
# source is needed that asks nothing of any agent.
#
# #598 declined to scope a table carrying a user FK and nothing else, because
# `profiles(user_id, name)` is shape-identical to a public `posts(user_id, title, body)`, and
# scoping by that shape would break every public feed. True — but there is a second shape that
# separates them, and the framework already names it: `_NARROW_OWNER_FK_NAMES`, the owner
# columns that attribute a row to a SUB-ENTITY rather than to a user. A table other rows are
# OWNED BY is an identity table, not content:
#
#     netflix    my_list.profile_id -> profiles     `profile_id` IS an owner name  -> private
#     instagram  comments.post_id   -> posts        `post_id` is NOT               -> public
#     tiktok     (nothing owns videos by video_id)                                 -> public
#
# Measured over the 94 generated backends that carry models: 14 ship an unscoped projected
# read on a table with an owner column, and this rule separates them 9/9 — netflix's
# `profiles` in r1/r2/r23/r27 private, instagram's `posts`/`comments` and tiktok's
# `videos`/`live_streams` public, which is what those apps mean.
#
# The vocabulary is IMPORTED, never re-listed: #908 wrote "a second hand-written copy of this
# vocabulary is how one member goes missing from one of them" while deriving its own.
def _sub_entity_owner_tables_1202(tables: Any) -> set:
    """Tables that other tables are owned BY — per-user identity, so reads are scoped. (#1202)"""
    found: set = set()
    try:
        from .route_projector import _NARROW_OWNER_FK_NAMES
    except Exception:
        return found
    try:
        cols_by_table = {}
        for name, rec in (tables or {}).items():
            cols = []
            if isinstance(rec, dict):
                cols = [c.get("name") if isinstance(c, dict) else c
                        for c in ((rec.get("schema") or {}).get("columns") or [])]
            cols_by_table[name] = {c for c in cols if c}
        for name in cols_by_table:
            singular = name[:-1] if name.endswith("s") else name
            owner_col = singular + "_id"
            if owner_col not in _NARROW_OWNER_FK_NAMES:
                continue
            # Some OTHER table must actually be owned by it. Without that, nothing in the app
            # treats this as an owner, and a public directory of profiles stays public.
            if any(owner_col in c for t, c in cols_by_table.items() if t != name):
                found.add(name)
    except Exception:
        return set()
    return found


# --- #1200: the lane's own READ filter is evidence that a read is per-user -------------
# r23 shipped a cross-user leak and delivered with every gate green. Live on the delivered
# artifact: `GET /api/profiles` returned all 33 profiles, spanning eight users, to ava.chen
# AND to sofia.martinez. r22/r24/r26 return one profile each — the same generator, the same
# schema, a different outcome.
#
# It is not an API-only abstraction. Driven in a real browser, r23's "Who's watching?" picker
# renders the SAME list to both accounts:
#
#     ava.chen        Ava | Family Room | Kids | Marcus | Weekend | Nina | Owen | Sofia | ...
#     sofia.martinez  Ava | Family Room | Kids | Marcus | Weekend | Nina | Owen | Sofia | ...
#
# Every account's profile names, on the screen the product opens with.
#
# The chain: `owner_scoped_reads` is set only for tables a verifier chain happens to probe
# for cross-user isolation (`_isolation_scoped_tables_from_chains`). r23 had no such chain
# for `profiles`, so the projected read shipped as `db.query(Profile).limit(100).all()`. And
# `_is_user_content_relation` (#598) deliberately does NOT cover it: a table with a user FK
# and nothing else is shape-identical to a public feed (`posts(user_id, title, body)`), so
# scoping it by shape would break every such feed. That reasoning is sound; the gap is that
# the opt-in's only source is an agent remembering to write a probe.
#
# There is a second source, and r23 had it all along: the lane's OWN handler for that path,
# which the framework then dropped as "duplicate standard CRUD ... schema-safe by
# construction" — a claim that is false exactly when the projection is unscoped:
#
#     custom_routes.py:  db.query(Profile).filter(Profile.user_id == _user_id(user))
#     main.py (won):     db.query(Profile).limit(100).all()
#
# So take the lane's filter as the judgment it is, and scope the PROJECTION with it. The
# alternative — restoring the lane's route — is the r130 wedge in the other direction (a
# buggy lane GET oscillating 403-own/200-cross-user until the run died), and "projected wins"
# stays untouched here.
#
# #77's caution applies and is honoured: only a READ handler counts. A write handler that
# checks ownership proves write authz only, which is true of public resources too, and using
# it as a read signal once scoped a world-readable feed to its caller.
_OWNERISH_COLS_1200 = ("user_id", "owner_id", "account_id", "profile_id", "author_id")
_ROUTE_DECOR_1200 = re.compile(r"@\w+\.(get|post|put|patch|delete)\s*\(", re.I)


def _lane_owner_scoped_read_tables_1200(backend_dir: Any, tables: Any) -> set:
    """Tables whose own lane READ handler filters by an owner column. (#1200)

    Best-effort and read-only; any failure yields an empty set, which reproduces the
    behaviour that existed before this signal.
    """
    found: set = set()
    try:
        src_p = Path(backend_dir) / "custom_routes.py"
        if not src_p.is_file():
            return found
        src = src_p.read_text(encoding="utf-8")
    except Exception:
        return found
    try:
        names = {t: _class_name(t) for t in (tables or {})}
        # Split on route decorators so each handler body is bounded by the NEXT one — a
        # landmark, not a byte window (#943).
        marks = [(m.start(), m.group(1).lower()) for m in _ROUTE_DECOR_1200.finditer(src)]
        for idx, (start, verb) in enumerate(marks):
            if verb != "get":
                continue                     # #77: only a READ filter is read evidence
            end = marks[idx + 1][0] if idx + 1 < len(marks) else len(src)
            body = src[start:end]
            for table, cls in names.items():
                if not cls or ("query(%s)" % cls) not in body:
                    continue
                for col in _OWNERISH_COLS_1200:
                    if re.search(r"\b%s\s*\.\s*%s\s*==" % (re.escape(cls), re.escape(col)),
                                 body):
                        found.add(table)
                        break
    except Exception as _e1201:
        from .message_format import warn_once_1201
        warn_once_1201("lane_owner_scoped_read_1200",
                       "the lane-read owner-scoping signal (#1200)", _e1201)
        return set()
    return found


def _class_names_1096(tables: Any) -> Dict[str, str]:
    """``{table: ClassName}`` with collisions resolved — two tables may never share a class.

    #1096: `_class_name` singularises a trailing plural, so a contract carrying BOTH `messages`
    and `message` (tiktok-r35 carries three such pairs) emitted `class Message(Base)` twice.
    Python keeps the SECOND, so every handler projected against `messages` — the table marked
    `owner_scoped_reads`, whose read filters on `Message.user_id` — resolved to the class
    WITHOUT `user_id` and 500'd:

        AttributeError: type object 'Message' has no attribute 'user_id'

    The models.py compiled and the collision was reported nowhere; it surfaced only at request
    time, on three resources at once (Message/Notification/LiveStream).

    Both emitters must agree: `render_models` writes the `class` lines and `_models_meta` hands
    `route_projector` the `cls` it generates handlers against. They called `_class_name`
    independently and collapsed identically, which is exactly why nothing caught it — so the
    mapping is computed ONCE from the whole table set and shared.

    The singular table keeps the singular name (`message` -> `Message`) and the plural one
    takes its plural CamelCase (`messages` -> `Messages`): stable, readable, and derived from
    the contract rather than from an ordinal. A numeric suffix is the last resort."""
    out: Dict[str, str] = {}
    used: Dict[str, str] = {}
    for table in sorted({str(t) for t in (tables or {})}):
        name = _class_name(table)
        if name not in used:
            out[table] = name
            used[name] = table
            continue
        parts = [p for p in re.sub(r"[^A-Za-z0-9]+", "_", table).strip("_").split("_") if p]
        alt = "".join(p[:1].upper() + p[1:] for p in parts) or (name + "Table")
        if alt not in used:
            out[table] = alt
            used[alt] = table
            continue
        i = 2
        while f"{name}{i}" in used:
            i += 1
        out[table] = f"{name}{i}"
        used[out[table]] = table
    return out


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


def _infer_fk_target_1162(col_name: str, known_tables: Iterable[str]) -> Optional[str]:
    """``<x>_id`` -> ``<x>s.id`` when a table by that name exists, else None.

    Structural only: what does this column REFERENCE. Deliberately NOT
    `_seed_infer_fk`, which answers "what should the seed put here" and therefore maps
    `profile_id` -> users; see the note in `_render_column`. The owner vocabulary is a
    LAST resort here, so a `<x>_id` that names a real table always wins over it.
    """
    n = str(col_name or "").lower().strip()
    if not n.endswith("_id"):
        return None
    known = {str(t).lower() for t in (known_tables or ())}
    base = n[:-3]
    if not base:
        return None
    for cand in (base, base + "s", base + "es", base[:-1] if base.endswith("s") else base):
        if cand and cand in known:
            return "%s.id" % cand
    # only now: a conventional actor column with no table of its own (`author_id`,
    # `posted_by_id`) points at the identity spine.
    try:
        if n in _owner_fk_vocabulary() and "users" in known:
            return "users.id"
    except Exception:
        pass
    return None


def _render_column(col: Dict[str, Any],
                   infer_fk_tables: Optional[Iterable[str]] = None) -> Optional[str]:
    from .database_scaffold import _counter_default
    col = _counter_default(col)   # FIX #97: *_count integers default 0 by construction
    name = str(col.get("name") or "").strip()
    if not name or _is_constraint_pseudo_column(col):
        return None
    args = [_sa_type(str(col.get("type") or "text"))]
    fk = _fk_target(col)
    # #1162: A CONVENTIONAL FK COLUMN THE CONTRACT DID NOT DECLARE IS STILL AN FK.
    #
    # `_fk_target` only sees an EXPLICIT `fk`/`references`, and lanes routinely register
    # `profile_id` as a bare integer — netflix-local-r13's whole models.py carries TWO
    # ForeignKeys. Everything that introspects `column.foreign_keys` is then blind, which
    # is one root with three separate symptoms already patched at the consumers:
    # #1158 (_fw_owns 403'd a caller's OWN sub-entity), #1158b (and fail-opened on
    # another user's once the target resolved), #1160 (_fw_owner_val wrote the USER id
    # into a PROFILE column, so every my_list row pointed at a row that does not exist).
    #
    # NOT `_seed_infer_fk`, though it looks like the same question. That one answers
    # "what should the SEED put here", so it checks the owner vocabulary FIRST and maps
    # `profile_id` -> users (fill the owner column with a user). As an ORM FK target that
    # is wrong and actively harmful: `my_list.profile_id` references `profiles.id`, and
    # declaring `ForeignKey("users.id")` would send `_fw_owns` straight back down its
    # "target is the users table -> the value must equal the caller's uid" branch — the
    # exact 403 #1158 fixed. Caught by rendering r13's real contract before shipping.
    # The structural question is different: what does this column REFERENCE. Table name
    # first; the owner fallback only when no such table exists.
    #
    # Callers pass `infer_fk_tables` for APP tables ONLY. The spine (users/tenants) is
    # excluded on purpose: those two are absent from `01_init.sql` in every measured run
    # (r13 models 11 / DDL 9, r14 10 / 8 — the diff is exactly users+tenants), so
    # `Base.metadata.create_all` actually CREATES them and any FK on them would become a
    # real DDL constraint. App tables all exist in the DDL, so create_all skips them and
    # the inferred FK stays ORM metadata — which is all the introspection needs.
    if not fk and infer_fk_tables:
        try:
            fk = _infer_fk_target_1162(name, infer_fk_tables)
        except Exception:
            fk = None
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
    # #497 (netflix r67, live): mirror database_scaffold's #407 NOT-NULL-no-default heuristic so
    # models.py and 01_init.sql AGREE on the DB default. The DDL scaffolder synthesizes
    # now()/CURRENT_DATE/CURRENT_TIME/false for a NOT-NULL timestamp/date/time/bool column that
    # carries NO explicit default — but it does so at DDL-render time, so that value never enters
    # this shared col dict; the ORM Column here saw default=None and emitted NO server_default.
    # Result: 01_init.sql had ``created_at TIMESTAMPTZ NOT NULL DEFAULT now()`` while models.py
    # declared a bare NOT NULL, forcing EVERY create handler to hand-set created_at=datetime.utcnow();
    # any path that OMITTED it 400'd ``null value in column "created_at"`` and wedged business_chain
    # (r67 burned 6+ lane dispatches on this exact divergence). Synthesize the SAME default here so
    # an insert that omits the column is safe BY CONSTRUCTION and #411's "handlers must OMIT
    # db-defaulted columns" finally holds end-to-end. SAFE + IDENTICAL to the DDL: only fires when
    # default is None AND NOT NULL AND not a PK, for the four types with an UNAMBIGUOUS default;
    # text/int/numeric stay required (no data invented). DB behavior is unchanged (the DDL already
    # shipped this default) — only the ORM catches up, so no create path can regress.
    if default is None and (col.get("nullable") is False or col.get("not_null")) \
            and not (col.get("primary_key") or col.get("pk")):
        _bt = str(col.get("type") or "").lower()
        if "timestamp" in _bt or "datetime" in _bt:
            default = "now()"
        elif "date" in _bt:
            default = "CURRENT_DATE"
        elif "time" in _bt:
            default = "CURRENT_TIME"
        elif "bool" in _bt:
            default = "false"
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
            kw.append("server_default=_sa_text('now()')")
        elif d.lower() in ("current_date", "current_time"):
            # #497: a SQL-function default (not a literal). Emit it as a bare server_default
            # SQL function so the DB fills it on any insert that omits the column; no ORM-side
            # python default — SQLAlchemy omits the unset column and the server_default fires.
            # (The generic elif below would wrongly wrap the bare word as a quoted string
            # literal → ``DEFAULT 'CURRENT_DATE'``, which is not a date.)
            kw.append(f"server_default=_sa_text({d.lower()!r})")
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
            kw.append(f"server_default=_sa_text({_sd_sql!r})")
    # FIX #158: the ORM ATTRIBUTE must be a valid, non-keyword identifier. When the DB
    # column name is a keyword/non-identifier (a real dataset column like ``from``), use a
    # safe attribute AND pin the original DB column name as Column's first positional arg,
    # so the table's DDL column keeps the contract name while ``import models`` stays valid.
    attr = safe_column_name(name)
    if attr != name:
        return f"    {attr} = Column({', '.join([repr(name)] + args + kw)})"
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
        # #1022: keep whatever FOLLOWS the reference too. This rebuilt the clause from its
        # two captured groups and silently dropped the rest, so coercing
        # `TEXT REFERENCES "users" ("id") ON DELETE CASCADE` produced
        # `integer references users(id)` — the FK survived, the cascade did not, and a
        # parent delete would start raising instead of cascading. Harmless while #197 was
        # dead (nothing was ever coerced in the DDL); live the moment it works.
        _tail = cur[m.end():].strip()
        col["type"] = "{} references {}({}){}".format(
            category, m.group(1), m.group(2) or m.group(3),
            (" " + _tail) if _tail else "")
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


# #1164: AN ORDINAL COLUMN DECLARED text SORTS LEXICOGRAPHICALLY.
#
# Same shape as PROPOSAL #3 above, one column class over: the framework already
# overrides a declared type when leaving it would produce something that cannot work.
#
# Two framework components disagree about these columns and one of them is right. The
# SEED vocabulary lists "seconds"/"count"/"rank"/"position"/"index" and routes them to
# `_seed_number`, so the framework writes INTEGERS into them (r13's seed:
# progress_seconds 83, 136, 189, 242) — while the contract said `text`, so the column is
# TEXT and the API hands the client back "83".
#
# Measured consequence, on a feature shipped this session: r13 declared `top10_rank` TEXT
# and r14 declared it INTEGER, for the same concept in the same env. #1155 now emits
# ORDER BY top10_rank, which on r13's TEXT column orders 1, 10, 11, 12, 2, 3 — a top-10
# that is not the top 10. Arithmetic and range filters on a text number are wrong the
# same way.
#
# DELIBERATELY NARROW — suffix-anchored names that can only be ordinals/counters. `value`,
# `rating`, `score` and `price` are excluded on purpose even though the seed vocabulary
# covers them: a lane can legitimately mean text there, and #566t saw exactly that
# ({"rating": "thumbs_up"}). A column carrying an FK is never touched.
_ORDINAL_SUFFIXES_1164 = ("_rank", "_index", "_position", "_seconds", "_count")


def _reconcile_ordinal_types_1164(by_name: Dict[str, List[Dict[str, Any]]]) -> None:
    """In-place: retype text ordinal columns to integer. Never raises."""
    try:
        for _cols in (by_name or {}).values():
            for c in _cols or []:
                if not isinstance(c, dict):
                    continue
                n = str(c.get("name") or "").lower()
                t = str(c.get("type") or "").lower()
                if not n.endswith(_ORDINAL_SUFFIXES_1164):
                    continue
                if c.get("primary_key") or c.get("pk") or _fk_target(c):
                    continue
                if "text" in t or "varchar" in t or "char" in t or "string" in t:
                    c["type"] = "integer"
    except Exception:
        return


def render_models(tables: Dict[str, Any]) -> str:
    """Render ``models.py`` (SQLAlchemy ORM) from the SchemaHub ``tables`` contract.
    Always emits the spine ``User``/``Tenant``; app tables generate one model each."""
    by_name: Dict[str, List[Dict[str, Any]]] = {}
    for name, table in (tables or {}).items():
        if isinstance(table, dict):
            by_name[str(name).lower()] = _columns_of(table)
    # #1096: ONE mapping for the whole table set, shared by both emitters — see
    # _class_names_1096. Includes the spine names, which are emitted here too.
    _cls_map_1096 = _class_names_1096(set(by_name) | {"tenants", "users"})
    # PROPOSAL #3 (L1): make FK column types agree with the PK they reference BEFORE
    # rendering the ORM, so the models — and the DDL introspected from them — never
    # carry an unbootable integer→text FK (run #16 channels.id).
    _reconcile_fk_types_in_map(by_name)
    _reconcile_ordinal_types_1164(by_name)

    blocks: List[str] = []

    _infer_tables_1162 = set(by_name) | {"tenants", "users"}

    def emit(table: str, cols: List[Dict[str, Any]],
             infer_fks: bool = False) -> None:
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
        lines = [c for c in (
            _render_column(col, _infer_tables_1162 if infer_fks else None)
            for col in real) if c]
        lines += _temporal_synonym_lines(real)   # #61: _at↔_time drift aliases
        body = "\n".join(lines) or "    pass"
        blocks.append(f'class {_cls_map_1096.get(table) or _class_name(table)}(Base):\n'
                      f'    __tablename__ = "{table}"\n{body}')

    emit("tenants", _merge_cols(_SPINE_TENANT_COLS, by_name.get("tenants", [])))
    emit("users", _merge_cols(_SPINE_USER_COLS, by_name.get("users", [])))
    for name, cols in by_name.items():
        if name in ("users", "tenants") or name in _SKIP_TABLES:
            continue
        emit(name, cols, infer_fks=True)

    header = (
        '"""Framework-generated SQLAlchemy ORM models — by-construction from the\n'
        'SchemaHub contract. The spine (Tenant/User) mirrors the tenancy+identity tables\n'
        'the embedded OAuth2 AS owns; app models come from the declared tables. Do not\n'
        'hand-edit: this is regenerated deterministically from the contract."""\n'
        "import uuid as _uuid\n"
        "from datetime import datetime\n\n"
        "from sqlalchemy import (Column, Integer, BigInteger, String, Text, Boolean,\n"
        "                        DateTime, Date, Time, Float, Numeric, JSON, ForeignKey)\n"
        "# FIX #215: alias text() so a column named `text` (comments/messages/posts all\n"
        "# have one) can't shadow the function inside the class body — a bare\n"
        "# `server_default=text(...)` after `text = Column(Text)` calls the Column\n"
        "# object → TypeError: 'Column' object is not callable → the backend won't boot.\n"
        "from sqlalchemy import text as _sa_text\n"
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
# #276: the connection pool MUST cover the request thread pool. FastAPI runs SYNC handlers
# (all projected/custom handlers are `def`) on a thread pool of 40 by default, and each holds
# a DB connection for its request. SQLAlchemy's DEFAULT pool is only pool_size=5 +
# max_overflow=10 = 15, with pool_timeout=30 — so under load ~25 of 40 concurrent handlers
# block up to 30s waiting for a connection and then raise TimeoutError, the health check
# among them (r60, live: the container flipped `unhealthy`, /health stopped answering, and
# api_smoke reported TimeoutError across the whole surface while the process sat idle at ~0%
# CPU — an intermittent wedge that recovered when load dropped, then recurred). Size the pool
# to 40 + a little headroom so a connection is always available and no handler starves.
# QueuePool sizing applies to Postgres (the real target); SQLite uses SingletonThreadPool
# and rejects max_overflow/pool_timeout, so gate the pool kwargs on the driver.
_pool_kwargs = ({} if _URL.startswith("sqlite")
                else {"pool_size": 20, "max_overflow": 30,
                      "pool_timeout": 30, "pool_recycle": 1800})
engine = create_engine(_URL, pool_pre_ping=True, future=True, **_pool_kwargs)


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
        # FIX #131 (instagram run-53 M1, live): a lane hand-writes EITHER driver's dict-
        # cursor idiom -- psycopg2 ``cursor(cursor_factory=RealDictCursor)`` OR psycopg3
        # ``cursor(row_factory=dict_row)`` -- but this connection speaks only ONE driver;
        # forwarding the FOREIGN kwarg verbatim raises "Connection.cursor() got an
        # unexpected keyword argument 'cursor_factory'" -> 500 (GET /api/feed, business_chain
        # wedge). Translate the mismatched factory to the kwarg THIS driver accepts, then
        # DROP any foreign leftover so it never reaches raw.cursor() (psycopg3 connection
        # module is "psycopg"; psycopg2 is "psycopg2").
        _drv = type(raw).__module__.split(".", 1)[0]
        if _drv == "psycopg" and "cursor_factory" in kwargs:
            kwargs.pop("cursor_factory", None)
            try:
                from psycopg.rows import dict_row
                kwargs.setdefault("row_factory", dict_row)
            except Exception:
                pass
        elif _drv == "psycopg2" and "row_factory" in kwargs:
            kwargs.pop("row_factory", None)
            try:
                from psycopg2.extras import RealDictCursor
                kwargs.setdefault("cursor_factory", RealDictCursor)
            except Exception:
                pass
        return raw.cursor(*args, **kwargs)

    def execute(self, statement, params=None, *args, **kwargs):
        """FIX #86: ALSO accept RAW-string SQL in the psycopg style (instagram run-7 M3:
        a lane get_db yielded a raw psycopg connection while its handlers mixed
        ``execute(text(...)).mappings()`` with ``execute("... %s", (v,))`` — no single
        handle type served both, and the TextClause reaching psycopg raised
        ``TypeError: TextClause has no len()`` -> 500 -> validation wedge). A plain-str
        statement is coerced to text(); %s positional params become named binds; rows
        come back DICT-LIKE (``row["col"]``) matching the dict_row habit. TextClause /
        ORM statements take the native path untouched."""
        if isinstance(statement, str):
            from sqlalchemy import text as _text
            if isinstance(params, (list, tuple)) and ("%s" in statement or "?" in statement):
                # #977: accept the qmark style too. FIX #86 taught the shim psycopg's `%s`;
                # a lane writing the sqlite habit `execute("... WHERE id = ?", (v,))` still
                # reached postgres verbatim as `syntax error at or near "?"` — 4 of those in
                # r158, each failing docker_up, and undiagnosable from the log until #973
                # started printing the STATEMENT beside the ERROR. `%s` keeps priority so
                # existing behaviour is byte-identical whenever it appears.
                marker = "%s" if "%s" in statement else "?"
                parts = statement.split(marker)
                stmt = parts[0]
                bound = {}
                for i, chunk in enumerate(parts[1:]):
                    stmt += f":p{i}" + chunk
                    if i < len(params):
                        bound[f"p{i}"] = params[i]
                return super().execute(_text(stmt), bound, *args, **kwargs).mappings()
            return super().execute(_text(statement), params, *args, **kwargs).mappings()
        return super().execute(statement, params, *args, **kwargs)


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
    # #1096: ONE mapping for the whole table set, shared by both emitters — see
    # _class_names_1096. Includes the spine names, which are emitted here too.
    _cls_map_1096 = _class_names_1096(set(by_name) | {"tenants", "users"})
    meta: Dict[str, Dict[str, Any]] = {}

    def add(table: str, cols: List[Dict[str, Any]]) -> None:
        names, fks, types, uniq = [], {}, {}, []
        required: List[str] = []          # #599
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
            # #599: NOT NULL with no default of any kind — the seed MUST provide a value or
            # the whole row is dropped at load. Carried here because `_build_seed_rows` has
            # only this meta to work from.
            elif (c.get("nullable") is False
                    and c.get("default") in (None, "")
                    and c.get("server_default") in (None, "")):
                required.append(n)
            tgt = _fk_target(c)
            if tgt:
                fks[n] = tgt.split(".")[0]
        if not have_pk and "id" not in names:
            names.insert(0, "id")
            types.setdefault("id", "Integer")   # synthesized SERIAL id
        if pk_name is None:
            pk_name = "id"  # synthesized SERIAL id
        meta[table] = {"cls": _cls_map_1096.get(table) or _class_name(table),
                       "cols": names, "fks": fks,
                       "pk": pk_name, "pk_type": pk_type, "types": types,
                       "unique": uniq, "required": required}

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
from sqlalchemy.exc import IntegrityError, DataError
from sqlalchemy.orm import Session

from database import Base, engine, get_db, SessionLocal
from auth_dependency import get_current_user
import models  # noqa: F401  (registers all ORM tables on Base.metadata)
from models import *  # noqa: F401,F403

# Audit rank-1 (whack-a-mole eradication): the best-effort fallbacks below are correct by
# construction, but SILENT — each swallowed exception hid one real bug that then surfaced
# only one-per-50-min-run (the rating saga #392->#393->#394->#395 was four bugs stacked
# under one ``except``). ``_fw_dbg`` makes them LOUD when FW_DEBUG is set: it prints the
# swallowed exception (repr + traceback + where) to stderr, which lands in
# ``docker logs backend``, so ONE validation run surfaces ALL layered failures instead of
# one-per-run. No-op by default (FW_DEBUG unset) — zero behaviour change.
_FW_DEBUG = os.environ.get("FW_DEBUG", "").strip().lower() in ("1", "true", "yes", "on")


def _fw_dbg(where, exc=None):
    if not _FW_DEBUG:
        return
    try:
        import sys as _sys
        import traceback as _tb
        print("[FW_DEBUG] %s: %r" % (where, exc), file=_sys.stderr, flush=True)
        if exc is not None:
            _tb.print_exception(type(exc), exc, exc.__traceback__, file=_sys.stderr)
    except Exception:
        pass


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


# #1190: THE ACTIVE SUB-ENTITY THE CALLER IS ACTING AS.
#
# The frontend already tells the backend which profile is in use — api.js sends
# `X-Profile-ID` on every call — and nothing on the server has ever read it. Measured on
# netflix-r22's DELIVERED release 1.0.0: `X-Profile-ID` appears 0 times in main.py and 0
# times in custom_routes.py. `_fw_owner_val` resolves "the caller's FIRST row in T", so
# every profile of one account resolves to the same value and they all read each other's
# rows. On that release, with one account and two profiles, a title added under profile 12
# came back verbatim to profile 13, and continue-watching behaved the same. The run's own
# description asks for the opposite in as many words: "Each profile sees only its own My
# List, ratings and Continue Watching (per-profile private data)."
#
# NOT a cross-account leak — profiles, my_list and continue_watching are user-scoped
# already and a second account sees none of it. This is the boundary INSIDE one account.
# Self-contained: the import sits with the definition rather than at the top of the module,
# because callers exec SLICES of this header (the #1158/#1160/owner-val test harnesses do),
# and a slice that carries the definition must carry what it needs to evaluate.
try:
    import contextvars as _cv1190
    _FW_PROFILE_CTX_1190 = _cv1190.ContextVar("fw_active_profile_1190", default=None)
except Exception:          # pragma: no cover - contextvars is stdlib since 3.7
    _FW_PROFILE_CTX_1190 = None


def _fw_owner_val(cls, col, user):
    """FIX #134 (instagram run-57, live): _fw_uid coerced to THIS owner column's TYPE.
    _fw_uid int-coerces a digit sub (the run-39 fix for INTEGER owner columns) — but a
    lane may declare the owner column TEXT (messages.sender_id was), and then the SQL
    bind is `text = integer` -> psycopg UndefinedFunction -> every scoped read 500s,
    while a PYTHON-level ownership check ("16" != 16) silently denies every owner.
    Look at the ORM column's python_type and coerce to match; unknown -> _fw_uid as-is."""
    _v = _fw_uid(user)
    # N-P0-2 (generalized #391 from netflix "who's watching"): some apps scope per-user
    # data through a SUB-ENTITY of the account, not the account itself — the owner column
    # FK-targets a table that is ITSELF owned by the user (netflix `profiles`; equally a
    # game's `characters`, a workspace's `members`, a SaaS `sub_accounts`). The owner value
    # is then the caller's SUB-ENTITY id, NOT their user id — a plain user id NOT-NULL-
    # satisfies but FK-VIOLATEs (no sub-entity with that id). Detected by SHAPE, not by
    # name: the owner col references table T, and T has its OWN foreign key to the
    # users/accounts table. Resolve (and, if absent, auto-create) the caller's first row in
    # T. Every failure — and any app that scopes directly by user_id (T has no user FK, so
    # the pattern doesn't match) — falls back to the user id, completely unaffected.
    try:
        _Sub = None       # the sub-entity ORM class (e.g. Profile)
        _sub_ufk = None   # the sub-entity's column that FKs to users (e.g. "user_id")
        _tgt_col = None   # the column the owner FK references (usually the PK, "id")
        _tgt_table = None
        for _fk in getattr(cls, col).property.columns[0].foreign_keys:
            _tgt_table = _fk.column.table
            _tgt_col = _fk.column.name
            break
        # #1160: the same missing-ForeignKey blindness #1158 fixed on the VALIDATION
        # side, here on the AUTO-FILL side. render_models emits plain Column(Integer),
        # so this loop finds nothing, the sub-entity branch below is skipped, and the
        # function falls back to the caller's USER id — which is then written into a
        # PROFILE column. Measured on r13's delivered stack: user id 15 owned profile
        # id 19, and POSTing {"title_id": 5} with no profile_id stored
        # {"profile_id": 15}. Every my_list / ratings / continue_watching row points at
        # a profile that does not exist, and per-profile scoping is meaningless — the
        # reads only agree because they filter on the same wrong value.
        if _tgt_table is None and str(col).endswith("_id"):
            _stem = str(col)[:-3]
            for _m in Base.registry.mappers:
                _t = getattr(_m, "local_table", None)
                _tn = getattr(_t, "name", None)
                if _tn and _tn in (_stem, _stem + "s", _stem + "es"):
                    _tgt_table = _t
                    _tgt_col = "id"
                    break
        if _tgt_table is not None and _tgt_table.name != cls.__table__.name:
            _USER_TABLES = ("users", "user", "accounts", "account")
            for _tc in _tgt_table.columns:            # is T a per-user sub-entity?
                for _tfk in _tc.foreign_keys:
                    if _tfk.column.table.name in _USER_TABLES:
                        _sub_ufk = _tc.name
                        break
                if _sub_ufk:
                    break
            if _sub_ufk is None:
                # #1160: and T's own user column is a bare Column(Integer) too.
                for _tc in _tgt_table.columns:
                    _cn = str(getattr(_tc, "name", "") or "")
                    if _cn in ("user_id", "account_id", "owner_id", "owner_user_id"):
                        _sub_ufk = _cn
                        break
            if _sub_ufk is not None:
                for _m in Base.registry.mappers:
                    _t = getattr(_m, "local_table", None)
                    if _t is not None and getattr(_t, "name", None) == _tgt_table.name:
                        _Sub = _m.class_
                        break
        if _Sub is not None and _sub_ufk is not None and _tgt_col is not None:
            with SessionLocal() as _s:
                _p = (_s.query(_Sub)
                        .filter(getattr(_Sub, _sub_ufk) == _fw_uid(user))
                        .order_by(getattr(_Sub, _tgt_col)).first())
                if _p is None:
                    # #390/#391 (netflix r14): the caller has NO sub-entity row yet — a
                    # freshly-registered business_chain user, or a chain that never created
                    # one. Falling back to the user id (below) makes a per-sub-entity write
                    # (rating / my_list / continue_watching) FK-VIOLATE → 404 "referenced
                    # resource not found", and because the verifier authors chains non-
                    # deterministically this wedges business_chain INTERMITTENTLY. Auto-
                    # create a default sub-entity for the caller (only when none exists),
                    # filling every NOT-NULL, no-default, non-FK column with a typed default
                    # so the INSERT can't fail; then per-sub-entity writes always resolve.
                    try:
                        _row = {_sub_ufk: _fw_uid(user)}
                        for _c in _Sub.__table__.columns:
                            if _c.name in _row or _c.primary_key:
                                continue
                            # #393: fill regardless of the ORM Column's ``nullable`` — it can
                            # DISAGREE with the DB DDL (render_models sometimes emits a
                            # NOT-NULL DDL column as a nullable ORM Column), and that mismatch
                            # is inconsistent across renders. Trusting ORM ``nullable`` skipped
                            # a column the DB requires (netflix: profiles.name) → the auto-
                            # create INSERT NotNullViolation'd → the whole #390 fell back to
                            # the user id → intermittent rating 404. Only skip columns with a
                            # real default (the DB supplies those) or FKs (can't invent a ref);
                            # filling a genuinely-nullable column with a typed default is
                            # harmless for a throwaway default sub-entity.
                            if _c.default is not None or _c.server_default is not None:
                                continue
                            if _c.foreign_keys:
                                continue
                            try:
                                _pt2 = _c.type.python_type
                            except Exception:
                                _pt2 = str
                            # #394: produce a value of the column's ACTUAL python type — a
                            # blanket "default" string broke a non-string column (netflix:
                            # a timestamp column got "default" → InvalidDatetimeFormat → the
                            # auto-create INSERT failed → #390 fell back → rating 404 again).
                            # Unknown/exotic types are SKIPPED (left NULL) rather than fed a
                            # wrong-typed string.
                            import datetime as _dtm
                            from decimal import Decimal as _Dec
                            if _c.name in ("name", "display_name", "title", "label", "nickname") and _pt2 is str:
                                _row[_c.name] = "Me"
                            elif _pt2 is bool:
                                _row[_c.name] = False
                            elif _pt2 is int:
                                _row[_c.name] = 0
                            elif _pt2 in (float, _Dec):
                                _row[_c.name] = _pt2(0)
                            elif _pt2 is str:
                                _row[_c.name] = "default"
                            elif _pt2 is _dtm.datetime:
                                _row[_c.name] = _dtm.datetime(2000, 1, 1)
                            elif _pt2 is _dtm.date:
                                _row[_c.name] = _dtm.date(2000, 1, 1)
                            elif _pt2 is _dtm.time:
                                _row[_c.name] = _dtm.time(0, 0, 0)
                            else:
                                continue  # unknown type → leave NULL rather than mis-type it
                        _np = _Sub(**_row)
                        _s.add(_np)
                        _s.commit()
                        _s.refresh(_np)
                        _p = _np
                    except Exception as _e:
                        _fw_dbg("fw_owner_val.autocreate_sub_entity", _e)
                        _s.rollback()
                        _p = None
                if _p is not None and getattr(_p, _tgt_col, None) is not None:
                    _v = getattr(_p, _tgt_col)
                else:
                    # #692: WHEN THE SUB-ENTITY CANNOT BE RESOLVED, READS MUST MATCH NOTHING.
                    # Reaching here means the SHAPE said this column owns via a per-user
                    # sub-entity (profiles / characters / members), the caller has no row in
                    # it, and #390's auto-create could not make one. `_v` is then still the
                    # user id from the top of this function — an id from a DIFFERENT
                    # namespace — and the two call sites diverge sharply:
                    #
                    #   WRITE  binds owner=user_id  -> FK violation -> 404. Loud. This is the
                    #          only consequence #390/#391/#393/#394 ever discuss, and it is
                    #          why those four fixes exist.
                    #   READ   filters `owner_col == user_id` -> silently returns the rows of
                    #          the SUB-ENTITY whose id happens to equal the caller's user id,
                    #          which generally belongs to somebody else. No FK protects a
                    #          read. Nothing fails. The caller is served another user's data.
                    #
                    # route_projector emits that filter at four sites (list, scoped list,
                    # parent-scoped and single-row reads), so every projected scoped read in
                    # every generated app inherits it. The asymmetry, not the frequency, is
                    # the defect: an unresolvable owner is not "fall back to something", it is
                    # "this caller owns nothing yet".
                    #
                    # -1 is chosen because it cannot collide with an autoincrement PK, and it
                    # keeps the WRITE behaviour intact — an FK violation either way, still a
                    # 404, just no longer pointing at a real other-user row. Only this branch
                    # changes: a shape that never matched (apps scoping directly by user_id)
                    # and a detection that raised both keep the old fallback below, because
                    # there the user id is either correct or the best guess available.
                    _fw_dbg("fw_owner_val.unresolved_sub_entity", {
                        "table": getattr(getattr(cls, "__table__", None), "name", None),
                        "col": col, "uid": _fw_uid(user),
                        "note": "no sub-entity row and auto-create failed; scoping to no rows "
                                "rather than to the sub-entity whose id equals the user id"})
                    _v = -1
    except Exception as _e:
        _fw_dbg("fw_owner_val.resolve", _e)
        _v = _fw_uid(user)
    # #566h (r119 instrument): log the RESOLVED owner value per call so a read-after-write
    # mismatch (POST binds profile_id=X, GET filters profile_id=Y → created row absent from
    # the list) is pinnable from the backend container log under FW_DEBUG. Best-effort;
    # runs AFTER resolution so it can never affect the resolved value.
    try:
        _fw_dbg("fw_owner_val.resolved", {
            "table": getattr(getattr(cls, "__table__", None), "name", None),
            "col": col, "uid": _fw_uid(user), "resolved": _v})
    except Exception:
        pass
    # #1190: the caller's ACTIVE sub-entity overrides the first-row default — but only
    # after `_fw_owns` confirms the caller owns it. The header can therefore only ever
    # NARROW to another of the caller's OWN profiles; an absent, unparseable or not-owned
    # value falls through to exactly today's resolution. That ownership gate is the
    # difference from the earlier attempt at this, which fail-opened and was reverted. It
    # runs last, so the existing resolution (and its auto-create) is untouched, and the
    # coercion below still normalises the header's string to the column's type.
    try:
        _act1190 = _FW_PROFILE_CTX_1190.get() if _FW_PROFILE_CTX_1190 is not None else None
        if _act1190 not in (None, "") and _fw_owns(cls, col, _act1190, user):
            _v = _act1190
    except Exception as _e1190:
        _fw_dbg("fw_owner_val.active_profile_1190", _e1190)
    try:
        _pt = getattr(cls, col).type.python_type
    except Exception as _e:
        _fw_dbg("fw_owner_val.python_type", _e)
        return _v
    try:
        if _pt is str and not isinstance(_v, str):
            return str(_v)
        if _pt is int and not isinstance(_v, int):
            return int(_v)
    except (TypeError, ValueError):
        pass
    return _v


def _fw_owns(cls, col, fk_val, user):
    """#566s (netflix r127 cross-user IDOR): True iff the CLIENT-SUPPLIED owner FK ``fk_val`` for
    ``cls.col`` belongs to the caller — the caller's own user id for a direct user-owned FK, or a
    sub-entity (profile / member / character / sub_account) the caller owns for a per-user
    sub-entity FK. Lets an owner-scoped create REJECT (403) a cross-user write (userB POSTing a
    body ``profile_id`` that is userA's) WHILE still honoring the caller's own NON-default
    sub-entity (multi-profile). Reuses _fw_owner_val's proven FK introspection. Fail-OPEN only on
    an introspection/query FAULT (a framework bug must never block a legitimate write); a clean
    "not owned" returns False → the handler 403s."""
    try:
        if fk_val is None or fk_val == "":
            return True   # absent → the handler resolves the caller's own via _fw_owner_val
        _uid = _fw_uid(user)
        _tgt_table = None
        _tgt_col = None
        for _fk in getattr(cls, col).property.columns[0].foreign_keys:
            _tgt_table = _fk.column.table
            _tgt_col = _fk.column.name
            break
        # #1158: RESOLVE THE TARGET BY NAME WHEN THE MODEL DOES NOT DECLARE IT.
        # render_models emits plain ``Column(Integer)`` for FKs — netflix-local-r13's whole
        # models.py declares TWO ForeignKeys — so ``foreign_keys`` is empty for
        # ``my_list.profile_id`` and every FK like it, ``_tgt_table`` stays None, and the
        # branch below then compares a PROFILE id against the caller's USER id. Measured on
        # r13's delivered stack: POST /api/my-list carrying the caller's OWN profile_id
        # (created seconds earlier, its user_id verified through the owner-scoped list)
        # answered 403 "profile_id does not belong to the caller". So the per-user
        # SUB-ENTITY path this function exists for (#566s) is unreachable in the normal
        # case, and the only writes that work are the ones that omit the FK entirely.
        # ``<x>_id`` -> a mapped table named ``<x>``/``<x>s``/``<x>es`` is the same
        # singular/plural resolution the projector already uses for nested resources.
        if _tgt_table is None:
            _stem = str(col)[:-3] if str(col).endswith("_id") else ""
            if _stem:
                for _m in Base.registry.mappers:
                    _t = getattr(_m, "local_table", None)
                    _tn = getattr(_t, "name", None)
                    if _tn and _tn in (_stem, _stem + "s", _stem + "es"):
                        _tgt_table = _t
                        _tgt_col = "id"
                        break
        _USER_TABLES = ("users", "user", "accounts", "account")
        # direct user-owned FK (or self / unknown target) → the value must be the caller's own uid
        if (_tgt_table is None or _tgt_table.name in _USER_TABLES
                or _tgt_table.name == cls.__table__.name):
            try:
                return str(fk_val) == str(_uid)
            except Exception:
                return True
        # per-user SUB-ENTITY FK → the value must be a row in T owned by the caller
        _sub_ufk = None
        for _tc in _tgt_table.columns:
            for _tfk in _tc.foreign_keys:
                if _tfk.column.table.name in _USER_TABLES:
                    _sub_ufk = _tc.name
                    break
            if _sub_ufk:
                break
        if _sub_ufk is None:
            # #1158b: the SAME missing-ForeignKey root, one level down. Resolving the
            # target table by name is not enough — judging ownership needs the target's
            # own user column, and `profiles.user_id` is a bare Column(Integer) too, so
            # this stayed None and fell through to fail-open. Live proof that the half
            # fix is WORSE than the bug: on r13, POSTing another user's profile_id=1
            # answered 201 where it had answered 403. That is the cross-user IDOR #566s
            # exists to stop (netflix r127). Resolve the user column by name as well,
            # and only fail open when the target really carries none.
            for _tc in _tgt_table.columns:
                _cn = str(getattr(_tc, "name", "") or "")
                if _cn in ("user_id", "account_id", "owner_id", "owner_user_id"):
                    _sub_ufk = _cn
                    break
        if _sub_ufk is None:
            return True   # T is not a per-user sub-entity → cannot assert ownership → fail-open
        _Sub = None
        for _m in Base.registry.mappers:
            _t = getattr(_m, "local_table", None)
            if _t is not None and getattr(_t, "name", None) == _tgt_table.name:
                _Sub = _m.class_
                break
        if _Sub is None:
            return True
        # #1160c: COERCE THE SUPPLIED VALUE TO THE TARGET COLUMN'S TYPE BEFORE QUERYING.
        # A client-supplied FK can arrive as a JSON string rather than a number, and
        # a JSON string, and binding "23" against an INTEGER pk makes postgres raise
        # `operator does not exist: integer = character varying` — LINE 3: WHERE
        # profiles.id = $1::VARCHAR. This function's except returns True (fail-open, so a
        # framework bug never blocks a legitimate write), so the type error did not 500:
        # it silently ACCEPTED every id, including another user's. Caught on r13's live
        # stack while probing the owner path, before it could ship.
        _fkv = fk_val
        try:
            _pt = getattr(_Sub, _tgt_col).type.python_type
            if _pt is int and not isinstance(_fkv, int):
                _fkv = int(_fkv)
            elif _pt is str and not isinstance(_fkv, str):
                _fkv = str(_fkv)
        except (TypeError, ValueError):
            return False   # a value that cannot BE the column's type owns nothing
        except Exception:
            pass
        with SessionLocal() as _s:
            _row = (_s.query(_Sub)
                      .filter(getattr(_Sub, _tgt_col) == _fkv)
                      .filter(getattr(_Sub, _sub_ufk) == _uid).first())
            return _row is not None
    except Exception as _e:
        _fw_dbg("fw_owns", _e)
        return True


def _fw_fill_required_defaults(cls, valid, db):
    """#566t (netflix r128): a create body may DROP a NOT-NULL column — the verifier authored the
    WRONG key ({"rating":"thumbs_up"} instead of {"value":"up"}), so the unknown field is filtered
    out and the ORM INSERTs NULL → NOT-NULL 400, EVEN when the column has a DB DEFAULT (the lane's
    ALTER … SET DEFAULT 'up'), because SQLAlchemy emits an explicit NULL for the unset non-null
    column instead of omitting it (so the DB default never fires). For each NOT-NULL, no-MODEL-
    default column ABSENT from the body, read the column's DB default from information_schema and
    apply it EXPLICITLY, so the row lands the intended default instead of 400ing. Best-effort; never
    raises; a well-formed body (column already present) is untouched."""
    try:
        import re as _re
        from sqlalchemy import text as _text
        _tbl = getattr(cls.__table__, "name", None)
        if not _tbl:
            return valid
        for _c in cls.__table__.columns:
            if (_c.primary_key or _c.nullable or _c.name in valid
                    or _c.default is not None or _c.server_default is not None):
                continue
            try:
                _d = db.execute(_text(
                    "SELECT column_default FROM information_schema.columns "
                    "WHERE table_name = :t AND column_name = :c"),
                    {"t": _tbl, "c": _c.name}).scalar()
            except Exception:
                _d = None
            if _d is None:
                # #1045 (netflix r176, live): NOT-NULL with NO DB default. Everything below only
                # rescues a column that HAS a default; with none, the ORM still emits an explicit
                # NULL and the insert 400s. On a FRAMEWORK-PROJECTED route no lane can repair
                # that — r176 spent its last gate on
                #   POST /api/continue-watching -> 400
                #   {"detail":"null value in column \\"progress_seconds\\" violates not-null"}
                # tagged [FRAMEWORK-PROJECTED route]. 20 recent runs hit a not-null violation.
                #
                # Fill ONLY types whose zero is unambiguous. Text is deliberately excluded: ""
                # for `synopsis`/`poster_url` (the other observed violators) would invent
                # content, which is precisely what the fabricated-fallback gate exists to stop —
                # and a missing synopsis is a real contract gap the lane SHOULD see as a 400.
                try:
                    _pt = _c.type.python_type
                except Exception:
                    continue
                if _pt is bool:
                    valid[_c.name] = False
                elif _pt is int:
                    valid[_c.name] = 0
                elif _pt is float:
                    valid[_c.name] = 0.0
                elif _pt.__name__ in ("datetime", "date"):
                    from datetime import datetime as _dt0, timezone as _tz0
                    _now = _dt0.now(_tz0.utc)
                    valid[_c.name] = _now.date() if _pt.__name__ == "date" else _now
                else:
                    _fw_dbg("fill_required_no_default",
                            Exception("%s.%s is NOT NULL with no default and type %s — declining "
                                      "to invent a value; the 400 is the correct signal"
                                      % (_tbl, _c.name, _pt.__name__)))
                continue
            _ds = str(_d).strip()
            if _ds.lower().startswith(("nextval(", "null")):
                continue   # serial PK / explicit null default — leave to the DB
            _m = _re.match(r"^'(.*?)'::", _ds) or _re.match(r"^'(.*)'$", _ds)
            if _m:
                valid[_c.name] = _m.group(1)
            elif _ds.lstrip("-").replace(".", "", 1).isdigit():
                valid[_c.name] = int(_ds) if _ds.lstrip("-").isdigit() else float(_ds)
            elif _ds.lower() in ("true", "false"):
                valid[_c.name] = (_ds.lower() == "true")
    except Exception as _e:
        _fw_dbg("fw_fill_required_defaults", _e)
    return valid


def _fw_upsert_on_conflict(db, cls, valid, user, owner_fk, subject_fks):
    """#566u (netflix r129): an owner-scoped STATE-WRITE (rating / my_list / continue_watching) that is
    re-created with the SAME (owner, subject) natural key hits a UNIQUE constraint → 409, but a re-write
    should UPSERT (re-rating updates; toggling a list is idempotent). REACTIVE: called only AFTER an
    IntegrityError, it loads the caller's existing row by owner_fk + subject_fks and UPDATEs it,
    returning the row; returns None when no such row exists (a DIFFERENT unique violation → the caller
    re-raises → 409). Because it fires only on a real conflict AND requires an owner+subject match, a
    non-unique / non-state-write resource is never wrongly upserted."""
    try:
        if not owner_fk or not subject_fks:
            return None
        try:
            db.rollback()
        except Exception:
            pass
        _own = valid.get(owner_fk)
        if _own is None:
            _own = _fw_owner_val(cls, owner_fk, user)
        _q = db.query(cls).filter(getattr(cls, owner_fk) == _own)
        for _sf in subject_fks:
            if valid.get(_sf) is None:
                return None
            _q = _q.filter(getattr(cls, _sf) == valid.get(_sf))
        _row = _q.first()
        if _row is None:
            return None
        for _k, _v in valid.items():
            if _k == owner_fk or _k in subject_fks:
                continue
            try:
                setattr(_row, _k, _v)
            except Exception:
                pass
        db.commit()
        db.refresh(_row)
        return _row
    except Exception as _e:
        _fw_dbg("fw_upsert_on_conflict", _e)
        try:
            db.rollback()
        except Exception:
            pass
        return None


def _coerce_body(cls, valid):
    """#395: coerce a create/update body's scalar values to each column's ACTUAL type
    before the INSERT. Verification chains send loosely-typed values — netflix: a thumbs
    rating {"value": "up"} / {"value": "thumbs_up"} POSTed into the INTEGER ratings.value
    column — and the raw INSERT then errors, so the rating chain 400s and business_chain
    wedges. Mirror the seed loader: a numeric string -> the number; a NON-numeric string in
    a numeric column -> 0 (so the row survives); a non-string scalar in a String/Text column
    -> its str; a bool-ish string ('true'/'1'/'on' / 'false'/'0'/'off') OR 1/0 in a Boolean
    column -> the bool (rank-4). Nested list/dict, datetime/date/time, and unknown types are
    left untouched (a bad datetime is caught by the global DataError->400 handler rather than
    mis-coerced). Best-effort; never raises, so a normal well-typed body is unaffected."""
    try:
        from sqlalchemy import (String as _SAStr, Integer as _SAInt,
                                Numeric as _SANum, Float as _SAFloat,
                                Boolean as _SABool)
        cols = cls.__table__.columns
    except Exception:
        return valid
    out = dict(valid)
    for k, v in valid.items():
        if k not in cols:
            continue
        if v is None:
            # #420 (netflix r14, live): an EXPLICIT None OVERRIDES a column's DB
            # default → NOT-NULL violation on INSERT. POST /api/my-list sent
            # created_at=None (a Pydantic optional field defaulting to None) →
            # 'null value in column "created_at" violates not-null constraint',
            # regressing business_chain on re-validation despite DEFAULT now() in the
            # DDL + server_default on the ORM column. Drop a None-valued key whose
            # column can supply its OWN value (server_default / Python default /
            # autoincrement PK) so the default/serial applies — the runtime twin of
            # the #409 seed None-strip, on the create/update handler path, and the
            # same "DB supplies it" signal used for the #390 sub-entity fill (line
            # ~711). A None for a column WITHOUT a default STAYS → the #411
            # IntegrityError handler 400s with the column name (correct
            # required-field feedback, not a silent drop). Best-effort; generalizable
            # (no product/column literals).
            try:
                _c = cols[k]
                if (_c.server_default is not None or _c.default is not None
                        or (_c.primary_key and _c.autoincrement)):
                    out.pop(k, None)
            except Exception:
                pass
            continue
        if isinstance(v, (list, dict)):
            continue
        try:
            ct = cols[k].type
            if isinstance(ct, _SABool) and not isinstance(v, bool):
                # rank-4: chains send "true"/"1"/"on" (or 1/0) for a Boolean column; the
                # SQLAlchemy bind wants a real bool -> coerce it, else leave the value for
                # the global DataError->400 handler.
                _bs = str(v).strip().lower()
                if _bs in ("true", "t", "1", "yes", "y", "on"):
                    out[k] = True
                elif _bs in ("false", "f", "0", "no", "n", "off"):
                    out[k] = False
            elif isinstance(ct, _SABool):
                continue  # already a real bool -> leave it
            elif isinstance(v, bool):
                continue  # a bool into a non-bool column -> don't mangle (bool is an int)
            elif isinstance(ct, _SAInt) and not isinstance(v, int):
                try:
                    out[k] = int(float(str(v).strip()))
                except (ValueError, TypeError):
                    out[k] = 0
            elif isinstance(ct, (_SANum, _SAFloat)) and not isinstance(v, (int, float)):
                try:
                    out[k] = float(str(v).strip())
                except (ValueError, TypeError):
                    out[k] = 0.0
            elif isinstance(ct, _SAStr) and not isinstance(v, str):
                out[k] = str(v)
        except Exception:
            continue
    return out


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
except Exception as _e:
    _fw_dbg("seed_if_empty", _e)
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
# #785 (naming, not behaviour): despite the name this set holds EVERY registered resource
# (each table name plus its singular/plural variants), not just nested children — see the
# builder, which iterates all `tables`. The name describes the USE SITE (telling a nested
# child-RESOURCE route from a nested ACTION verb) rather than the contents.
# This matters because it is what implements #528's "projected wins for GET on ALL registered
# resources": reading the precedence branches alone suggests public resources fall through to
# `return _is_get` (lane wins), and they do not — `titles` is in this set. That misreading was
# made once while auditing, and #568/#569 were both route-precedence SAFETY bugs found by
# reading exactly these branches, so the trap is worth naming here.
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
# #568 (netflix r133, live cross-user leak): resources whose PROJECTED model is DEGENERATE —
# the contract registered the table with an empty column schema, so the model carries only its
# primary key. #528's whole premise for "projected read wins" is that the projected read is
# SCHEMA-SAFE by construction; with no columns to be safe about, that premise fails: the read
# cannot owner-scope (no owner FK exists in the model) and serves every user's rows. r133
# registered `my_list` with schema.columns == [] -> `class MyList(Base): id = Column(...)` ->
# GET /api/my-list returned another account's row while the lane's OWN correct handler
# (filter MyList.profile_id == prof.id) sat shadowed. For these the LANE keeps the route.
_DEGENERATE_RESOURCES = set(__DEGENERATE_RESOURCES__)


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

    def _fw_resource_seg(seg):
        """#566w: map a URL path SEGMENT into the namespace the resource sets use.
        The sets are built from TABLE names (snake_case: my_list, continue_watching) but REST
        paths for the same resource are kebab-case (/api/my-list). Comparing the raw segment
        missed EVERY multi-word resource, dropping it out of the #77/#528 projected-read-wins
        guard so a buggy lane GET shadowed the safe projected read (netflix r130, live:
        GET /api/my-list oscillated 403-own / 200-cross-user and wedged the run at 0 tags).
        Defined INSIDE this function: the #528 test harness slices this def out of the
        template and execs it standalone, so it must not reference module-level helpers."""
        return str(seg or "").strip().lower().replace("-", "_")
    last = segs[-1]
    n_params = sum(1 for s in segs if s.startswith("{") or s.startswith(":"))
    last_is_param = last.startswith("{") or last.startswith(":")
    # STANDARD-CRUD read shapes → PROJECTED wins (return False = do NOT let the lane override):
    # #528 (netflix, live): a lane custom GET on a bare collection (/api/titles) or item-by-id
    # (/api/titles/{id}) for a REGISTERED resource routinely runs raw SQL over columns that do
    # NOT exist → 500 → business_endpoints_reachable / business_chain wedge AND the frontend is
    # data-starved. The framework's projected read (db.query(Model) list / db.get(Model, id)) is
    # schema-safe and 200/404 by construction, so it MUST win for GET on these two shapes for
    # ALL registered resources — not just the owner-scoped ones (#77). TRADE-OFF: public
    # LIST/read now serves from the PROJECTED handler (schema-correct, returns rows) instead of
    # lane raw SQL — this trades any lane-added filtering/sorting on PUBLIC lists for guaranteed
    # reachability/correctness. Owner-scoped PRIVATE resources already projected-won here (#77:
    # their projected read is owner-scoped by construction; a lane GET could only re-widen the
    # scope → cross-user leak, outlook run-9) — UNCHANGED. Non-resource collection GETs (search:
    # /api/search names no table → not in the registered set) and every NON-standard lane route
    # (sub-collections/actions, custom verbs — they fall through below) still let the LANE win,
    # so lane custom/non-standard routes are UNAFFECTED. GATE on registered-resource membership
    # (guard: only decide projected-wins where a projected handler actually exists — an
    # unregistered segment has none, so returning False there would 404). WRITES stay projected:
    # create/update/delete are already owner-safe + shape-consistent (the buggy-lane-CRUD
    # concern is for mutations), and projected NESTED reads keep their parent-owner isolation.
    _is_get = method.upper() == "GET"
    if len(segs) == 1 and not last_is_param:          # collection: /messages, /api/titles
        # #528: the projected collection list wins for GET on any REGISTERED resource (a real
        # table → a projected handler exists). _OWNER_SCOPED_RESOURCES is a subset, kept as an
        # explicit belt-and-suspenders so #77 owner-scoped resources ALWAYS project-win even if
        # the registered set is later narrowed. /api/search & other unregistered collection GETs
        # are in NEITHER set → lane still wins (unchanged).
        # #568: a degenerate projected model cannot be schema-safe OR owner-scoped — the
        # premise of projected-wins fails, so the lane keeps its (schema-complete) read.
        if _is_get and _fw_resource_seg(segs[0]) in _DEGENERATE_RESOURCES:
            return True
        if _is_get and (_fw_resource_seg(segs[0]) in _NESTED_CHILD_RESOURCES
                        or _fw_resource_seg(segs[0]) in _OWNER_SCOPED_RESOURCES):
            return False
        return _is_get
    if last_is_param and n_params == 1:               # item by id: /messages/{id}, /api/titles/{id}
        # resource = the segment BEFORE the trailing {id} (segs[-2]) so a namespaced path
        # (/api/v1/messages/{id} → 'messages') is still covered, not the version prefix.
        _res = _fw_resource_seg(segs[-2]) if len(segs) >= 2 else _fw_resource_seg(segs[0])
        # #528: the projected item read (db.get(Model, id), 200/404 by construction) wins for
        # GET on any REGISTERED resource; #77 owner-scoped stays projected (no cross-user leak).
        # An unregistered by-id GET is in neither set → lane wins (unchanged).
        if _is_get and _res in _DEGENERATE_RESOURCES:
            return True                               # #568: nothing to be schema-safe about
        if _is_get and (_res in _NESTED_CHILD_RESOURCES or _res in _OWNER_SCOPED_RESOURCES):
            return False                              # projected read wins (schema-safe, no leak)
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
            and _fw_resource_seg(segs[2]) in _NESTED_CHILD_RESOURCES):
        return False
    return True                                       # actions / search / novel → custom wins

_FW_DROPPED_1166 = []   # #1166: (route, method, path) dropped for a projection that may not exist

try:
    import custom_routes as _custom_mod
    from fastapi import APIRouter as _APIRouter
    # FIX #127 (instagram run-46 M3, live): include EVERY APIRouter the lane defines,
    # not only the one named `router`. run-46's lane wrote a correct repost handler on
    # a SECOND router (`hidden_router = APIRouter()`) that the old single-name import
    # left orphaned → the projected #124 fallback (404) served the route and the
    # verifier's expect [200,201] chains wedged. Discover all module-level APIRouter
    # instances; prefer `router` FIRST (its routes register before any twin) then the
    # rest by definition order; apply the same override policy to each.
    _seen_r = set()
    _routers = []
    _named = getattr(_custom_mod, "router", None)
    if isinstance(_named, _APIRouter):
        _routers.append(_named); _seen_r.add(id(_named))
    for _rn in vars(_custom_mod):
        _rv = getattr(_custom_mod, _rn, None)
        if isinstance(_rv, _APIRouter) and id(_rv) not in _seen_r:
            _routers.append(_rv); _seen_r.add(id(_rv))
    for _custom_router in _routers:
        # Keep only the custom routes that legitimately override (or add) — drop the
        # ones duplicating a standard-CRUD endpoint so the safe projected handler serves.
        _kept_cr, _dropped_cr = [], []
        for _r in list(getattr(_custom_router, "routes", [])):
            _m_cr = next(iter(getattr(_r, "methods", []) or ["GET"]))
            _p_cr = getattr(_r, "path", "")
            (_kept_cr if _custom_route_overrides_projected(_m_cr, _p_cr)
             else _dropped_cr).append((_r, _m_cr, _p_cr))
        _custom_router.routes = [_t[0] for _t in _kept_cr]
        # #1102: SAY SO. This filter drops 98 legitimate lane routes across 57 of the
        # 65 corpus backends — measured by booting each app and diffing its declared
        # custom routes against its live route table — and said nothing, so the lane
        # sees a handler it wrote simply not run. Fourteen runs answered that by
        # reaching into sys.modules["main"] to patch the route table, and tiktok-r58
        # shipped a DELIVERED milestone whose /health, /docs and /api/videos are all
        # 404 because its patch did `app.routes.clear(); app.routes.extend(kept)` on
        # a list that IS `kept`. The ImportError branch below already learned this
        # lesson for its own case ("invisible for hours"); the same applies here.
        if _dropped_cr:
            import logging as _cr_log
            # WARNING, not info: uvicorn leaves the root logger at WARNING, so an
            # info() on a non-uvicorn logger is swallowed — verified by booting a
            # rendered app and finding no line at all. A notice nobody sees is the
            # silence this fix exists to end.
            _cr_log.getLogger("custom_routes").warning(
                "custom_routes: %d route(s) NOT registered because they duplicate "
                "standard CRUD — the framework's projected handler serves them, and it "
                "is schema-safe by construction. This is expected; do NOT patch the "
                "app's route table to force them in. To own one of these paths, change "
                "its SHAPE in the contract (an action segment such as "
                "/x/{id}/publish overrides; a bare collection or item-by-id does not): %s",
                len(_dropped_cr), [f"{_t[1]} {_t[2]}" for _t in _dropped_cr])
        # #1166: a dropped route must be dropped IN FAVOUR OF something.
        # `_custom_route_overrides_projected` decides on SHAPE alone and never asks
        # whether a projected handler for that method+path actually exists. Measured on
        # both delivered artifacts: within the SAME platform resource, POST and GET
        # /api/v1/tenants are kept while DELETE /api/v1/tenants/{tenant_id} is dropped as
        # "standard CRUD" — and the projector never touches the spine, so nothing serves
        # it. r14 live: DELETE /api/v1/tenants/default -> 404, on an endpoint the contract
        # DECLARES and the lane IMPLEMENTED.
        #
        # The check cannot run here: the projected handlers are appended to main.py BELOW
        # this line, so at include time they are not registered yet. Re-examine at startup,
        # when the module has finished executing and the route table is complete, and
        # restore only the ones nothing else serves. "Projected wins" is untouched — this
        # only stops a lane route from being dropped into the void.
        for _t_cr in _dropped_cr:
            _FW_DROPPED_1166.append((_t_cr[0], _t_cr[1], _t_cr[2]))
        app.include_router(_custom_router)


    @app.on_event("startup")
    async def _fw_restore_unserved_dropped_1166():
        """Re-register a dropped lane route that nothing else ended up serving."""
        try:
            import logging as _l1166
            _served = set()
            for _rt in app.routes:
                for _mm in (getattr(_rt, "methods", None) or ()):
                    _served.add((str(_mm).upper(), str(getattr(_rt, "path", ""))))
            _back = []
            for _r1166, _m1166, _p1166 in _FW_DROPPED_1166:
                if (str(_m1166).upper(), str(_p1166)) in _served:
                    continue          # a projection really does serve it — stay dropped
                app.router.routes.append(_r1166)
                _back.append("%s %s" % (_m1166, _p1166))
            if _back:
                _l1166.getLogger("custom_routes").warning(
                    "#1166 restored %d lane route(s) that were dropped for a projected "
                    "handler that does not exist — nothing else serves them, so dropping "
                    "them would have left a DECLARED endpoint answering 404: %s",
                    len(_back), _back)
        except Exception as _e1166:      # never let the repair break startup
            try:
                import logging as _l2
                _l2.getLogger("custom_routes").warning(
                    "#1166 restore skipped: %s", _e1166)
            except Exception:
                pass
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
    # #235 BOOTSTRAP-SYNONYM FILL-IN (tiktok r25, live): the contract names its auth
    # entry points freely — r25 declared POST /api/auth/signup while the AS router
    # serves register/login, so NOTHING ever served signup (the lane's hand-written
    # copy was overwritten every tick by this framework-owned file) → the
    # token-minting first step of every business chain 401'd → 108-min livelock.
    # Alias each absent synonym path onto the SAME canonical handler FUNCTION via
    # add_api_route (decorator-equivalent — NOT route-object reuse, see run-49
    # note above). Fill-in only: a lane-authored synonym route wins.
    _fw_alias_of = {"signup": "register", "signin": "login"}
    _fw_by_path = {}
    for _r in app.routes:
        _fw_by_path.setdefault(getattr(_r, "path", ""), _r)
    for _syn, _canon in _fw_alias_of.items():
        for _pref in ("/api/auth/", "/auth/"):
            _canon_r = _fw_by_path.get(_pref + _canon)
            if (_pref + _syn) in _fw_by_path or _canon_r is None:
                continue
            _fn = getattr(_canon_r, "endpoint", None)
            if _fn is not None:
                _methods = [m for m in (getattr(_canon_r, "methods", None) or ("POST",))
                            if m != "HEAD"]
                # #1103: response_model=None, ALWAYS. Without it FastAPI infers the
                # response model from `_fn`'s return annotation — and every AS handler
                # is `-> JSONResponse` under `from __future__ import annotations`, i.e.
                # a STRING. When that string does not resolve here, pydantic gets
                # ForwardRef('JSONResponse') and cannot build it. Registration itself
                # succeeds — the ForwardRef is simply stored — so nothing complains until
                # the schema is built, and then GET /openapi.json 500s. tiktok-r92 shipped
                # a DELIVERED milestone doing exactly that on four routes, and the same
                # input reproduces on the FastAPI this repo runs today (0.121/pydantic
                # 2.12): a dead /openapi.json and /docs, and no MCP or client generation.
                # A Response subclass is never a response model, so pinning it to None
                # is what the annotation means anyway, and it makes the alias immune to
                # how any FastAPI version happens to resolve annotations.
                app.add_api_route(_pref + _syn, _fn, methods=_methods or ["POST"],
                                  response_model=None)
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
    # TENANT-CREATE FILL-IN (#554, netflix r58 / task#47): the tenant control plane is a
    # FIXED framework contract that pins method+path but NOT body shape. A verifier authors
    # the create the natural way — POST /api/v1/tenants {"name": ...} (or body-less) — with
    # NO client-supplied PK, and a lane's create_tenant (or the old prompt template) 400s on
    # the missing id → business_chain_failing blocks delivery on an otherwise-green app. The
    # Tenant PK is server-generatable (models.py: a text/uuid id defaults to a uuid), so a
    # create that omits it must GENERATE one, NEVER 400. Serve a body-tolerant POST here
    # (method-aware, only-if-absent) so every app has a correct create by construction; a
    # lane-authored POST /api/v1/tenants still wins (fill-in only).
    def _fw_tenant_create(body: dict = None, db=Depends(get_db)):
        _b = body if isinstance(body, dict) else {}
        _tid = str(_b.get("id") or _b.get("tenant_id") or "").strip()
        _name = _b.get("name")
        if not _tid:
            # generate the PK: a slug of the name, else a uuid — NEVER 400 on a missing id.
            import re as _fw_re, uuid as _fw_uuid
            if _name:
                _tid = _fw_re.sub(r"[^a-z0-9]+", "-", str(_name).strip().lower()).strip("-")[:48]
            if not _tid:
                _tid = "t_" + _fw_uuid.uuid4().hex[:12]
        try:
            import models as _fw_m
            _T = getattr(_fw_m, "Tenant", None)
            if _T is not None:
                _obj = db.get(_T, _tid)
                if _obj is None:
                    _cols = {c.name for c in _T.__table__.columns}
                    _row = {"id": _tid}
                    if "name" in _cols:
                        _row["name"] = _name or _tid
                    db.add(_T(**_row)); db.commit()
                    _obj = db.get(_T, _tid)
                if _obj is not None:
                    return {"id": getattr(_obj, "id", _tid),
                            "name": getattr(_obj, "name", None) or _name or _tid}
        except Exception as _fw_tc_exc:
            try:
                db.rollback()
            except Exception:
                pass
            _fw_dbg("tenant_create fill-in", _fw_tc_exc)
        return {"id": _tid, "name": _name or _tid}
    _fw_present_mp = {(str(_m).upper(), getattr(_r, "path", ""))
                      for _r in app.routes
                      for _m in (getattr(_r, "methods", None) or ())}
    if ("POST", "/api/v1/tenants") not in _fw_present_mp:
        app.post("/api/v1/tenants", status_code=201)(_fw_tenant_create)
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
    from .route_projector import (_generate_handler, _norm_path, _resource_model,
                                 resolve_endpoint_auth, _truthy,
                                  _owner_fk, _TARGET_FK_NAMES)
    from .backend_scaffold import _AUTH_MIDDLEWARE, _INTEGRITY_HANDLER

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
        # #1099: the SAME auth rule as the other emitter. `resolve_endpoint_auth` handles the
        # present-but-None key correctly (r58's shape, which `bool(ep.get(k, default))` reads
        # as False) and defaults an UNSTATED endpoint by SHAPE — auth for a write or a
        # self/personalised read, open for a public catalog read. This emitter defaulted every
        # unstated endpoint to auth instead, so 38 of the corpus's 73 unstated business reads
        # (52%, 16 runs) came out authed here and anonymous there: GET /api/videos,
        # /api/users, /api/comments, /api/sounds/{id}. Whether a catalog needs a token then
        # depended on WHICH emitter filled the route, and the anonymous ui_flow walk 401s in
        # one case and not the other. Safe to align only because #1098 added `or _owner_scoped`
        # below: a private resource still forces an actor whatever the contract omits.
        auth = bool(resolve_endpoint_auth(method, path, ep, emeta))
        # Pass the declared response_key through so single-item endpoints get {item}
        # (not the collection {items,total}); mirrors route_projector.project_missing_routes.
        _eschema = ep.get("schema") if isinstance(ep.get("schema"), Mapping) else {}
        response_key = str(ep.get("response_key") or _eschema.get("response_key")
                           or emeta.get("response_key") or "").strip()
        _rm = _resource_model(path, meta)
        _owner_scoped = bool(_rm and str(_rm[0]).lower() in scoped_read_tables)
        # #1097 — ONE RULE, ONE PRODUCER. `route_projector` already decides this for the
        # routes IT projects, with two documented steps this emitter never applied:
        #   #320: an EXPLICIT `auth_required: false` is the lane's deliberate "this read is
        #         public" declaration (r88/r89's public-feed wedge) → drop the owner filter;
        #   #633: …but a structurally-private resource is private whatever the contract says
        #         (4 of 45 delivered backends shipped an UNAUTHENTICATED GET /api/search over
        #         `continue_watching`) → force it back on.
        # Applying only one half, or a path-shape heuristic of this module's own, is how the
        # two emitters drift — #1096 is what that costs.
        _explicit_public_1097 = (ep.get("auth_required") is False) or (
            isinstance(emeta, Mapping) and emeta.get("auth_required") is False)
        if _explicit_public_1097 and _owner_scoped:
            _owner_scoped = False
        try:
            from .route_projector import _structurally_private_resource_633 as _priv633
            if _priv633(method, path, meta):
                _owner_scoped = True
        except Exception:
            pass
        # #1098 — #271's guarantee, without which #633's flag means nothing. `_generate_handler`
        # gates the owner filter on AUTH (`owner_fk = _owner_fk(meta) if auth else None`), so a
        # resource that is private BY CONSTRUCTION must force an actor whatever the contract
        # forgot — otherwise it renders with no actor AND no filter, which is #633's own
        # documented leak ("returns user_id, title_id, progress_seconds for EVERY user,
        # unauthenticated"). route_projector has carried this as `resolve_endpoint_auth(...) or
        # _owner_scoped` all along; this emitter did not.
        auth = auth or _owner_scoped
        block = _generate_handler(method, path, auth, meta, i, response_key, _owner_scoped, owner_scoped_tables=scoped_read_tables)
        (param_blocks if "{" in path else static_blocks).append(block)

    # _AUTH_MIDDLEWARE references ``app`` + imports jwt/JSONResponse/jwt_manager; it is
    # inserted after the app is constructed and before the routes (static-first).
    mid = _AUTH_MIDDLEWARE.strip("\n")
    # Inject the registered resource names so the custom-route override filter can tell a
    # nested child-RESOURCE route (projector-handled → projected wins) from a nested ACTION
    # verb (lane custom wins). Names + singular/plural variants to match a path segment.
    # #1059: a resource whose PROJECTED read cannot express its privacy boundary must not be
    # handed the route here either. #77 already excludes MULTI-PRINCIPAL tables (a DM with
    # sender_id AND recipient_id: the single-owner projected read 404s the recipient) from
    # _owner_scoped_resources — but the two GET branches of the override filter accept
    # membership in EITHER set, and every table lands in this one unconditionally, so the
    # carve-out was bypassed and the projected read won anyway. Rendered proof for a `dms`
    # table flagged owner_scoped_reads:
    #
    #     obj = db.get(Dm, id)
    #     if getattr(obj, "sender_id", None) != _fw_owner_val(type(obj), "sender_id", user):
    #         raise HTTPException(status_code=404, detail="not found")
    #
    # — one FK, so the RECIPIENT 404s on their own message. Generalises past DMs to any
    # two-party row (buyer+seller, host+guest, from_user+to_user).
    #
    # Excluded only when the projected read WOULD be owner-scoped (the table is in
    # scoped_read_tables). A multi-principal table nobody scopes has no OR boundary to get
    # wrong, so it stays and keeps #528's schema-safe projected read.
    _multi_principal_1059: set = set()
    for _t in scoped_read_tables:
        _tm = meta.get(_t) or meta.get(str(_t).lower()) or {}
        _fks = _tm.get("fks") or {}
        _cols = _tm.get("cols") or []
        _p = {c for c, tgt in _fks.items() if str(tgt).lower() == "users"}
        _p |= {c for c in _cols if str(c).lower() in _TARGET_FK_NAMES}
        if len(_p) > 1:
            _n = str(_t).strip().lower()
            if _n:
                _multi_principal_1059 |= {_n, _n + "s", _n.rstrip("s")}
    _nested_resources: set = set()
    for _t in (tables or {}):
        _n = str(_t).strip().lower()
        if _n and _n not in _multi_principal_1059:
            _nested_resources |= {_n, _n + "s", _n.rstrip("s")}
    _nested_resources -= _multi_principal_1059
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
    # #568: tables whose projected model is DEGENERATE — only the primary key survived, so the
    # projected read has no column to serialize beyond `id` and no owner FK to filter on. That
    # is not a schema-safe handler, and #528/#566w hand it the route anyway unless we say so
    # here. netflix r133: the contract registered `my_list` with schema.columns == [] (its
    # siblings `ratings`/`continue_watching` registered in full), the model came out PK-only,
    # and GET /api/my-list served another account's row while the lane's correct handler was
    # shadowed. Keyed off the parsed model, so ANY cause of a degenerate model is covered.
    # Keyed on the CONTRACT's declared columns, not on the parsed model's count: a table that
    # genuinely declares only a primary key has a KNOWN, complete schema and must keep
    # projecting (its `{"id": …}` read is correct). Degenerate means the contract declared
    # NOTHING and the model's PK was synthesized — the schema is unknown, not minimal.
    _degenerate_resources: set = set()
    for _t, _tdef in (tables or {}).items():
        try:
            _declared = [c for c in (_columns_of(_tdef) or [])
                         if not _is_constraint_pseudo_column(c)]
        except Exception:
            _declared = []
        if _declared:
            continue
        _n = str(_t).strip().lower()
        if _n:
            _degenerate_resources |= {_n, _n + "s", _n.rstrip("s")}
    custom_include = _CUSTOM_ROUTES_INCLUDE.replace(
        "__NESTED_CHILD_RESOURCES__", repr(sorted(_nested_resources))
    ).replace(
        "__OWNER_SCOPED_RESOURCES__", repr(sorted(_owner_scoped_resources))
    ).replace(
        "__DEGENERATE_RESOURCES__", repr(sorted(_degenerate_resources)))
    # _CUSTOM_ROUTES_INCLUDE precedes the projected blocks so a lane custom_routes
    # handler OVERRIDES the projected one for the same METHOD+path (first-registered
    # wins in Starlette) — the documented lane-override intent, which the old footer
    # placement silently inverted.
    # FIX #82 lives HERE by construction (not only the heal-time injection): the skeleton
    # regenerates main.py every pre-validation cycle, so an injected-only handler raced the
    # regen and the deployed container could hold an un-healed main.py (run-3, 2026-07-06:
    # unchecked path-id FK INSERT → raw 500 → business_chain wedged on a tolerated-404 chain).
    integ = _INTEGRITY_HANDLER.strip("\n")
    body = (_MAIN_HEADER + "\n\n" + mid + "\n\n\n" + integ + "\n\n\n"
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
        # FIX #189 (tiktok-r5): union the skeleton's OWN module names — when
        # custom_routes.py is absent, main.py's guarded `import custom_routes`
        # hook otherwise reads as third-party and the framework itself writes a
        # non-existent pip dep → uv fails → docker_up wedges to STUCK-ABORT.
        from .backend_scaffold import _SKELETON_LOCAL_MODULES
        local = {f.stem for f in be.glob("*.py")} | set(_SKELETON_LOCAL_MODULES)
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
# #1007: no EXPOSE line, on purpose. It used to say `EXPOSE 8081`, which was wrong — main.py
# binds `API_PORT`, and compose sets that to a per-run `{backend_port}`. This template is
# written out verbatim (`w("Dockerfile", _DOCKERFILE)`), so it cannot interpolate the real
# value; any constant here is a false statement waiting to mislead the next reader. It
# misled me for a full search before I read the compose generator.
#
# Docker ignores EXPOSE for routing, so removing it changes nothing at runtime and stops the
# file asserting a port it cannot know. My first attempt at this replaced 8081 with 8082 —
# swapping one wrong constant for another that happened to be right in one run, which is
# item 422's mistake committed minutes after writing item 422.
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


def _ensure_seed_dataset(be: Path, output_dir: Any) -> bool:
    """F2/F2b: (re)assemble the design-prep REAL dataset (design/dataset/*.json) into the
    framework-owned app/backend/seed_dataset.json (the lane never authors this; the loader
    merges it OVER seed_data.json). Called from BOTH the upfront build-infra AND every
    per-milestone skeleton write, so the real data lands regardless of design-prep timing
    (googlemaps run-1: the upfront call missed it). Absent design/dataset/ → no-op → zero
    regression. Best-effort; returns True iff it wrote a non-empty seed_dataset.json."""
    try:
        from .material_prep import assemble_seed_dataset
        real = assemble_seed_dataset(Path(output_dir) / "design" / "dataset")
        if real:
            # #483: align dataset field names to the ORM model's columns before staging —
            # a contract/model that names a column differently than design-prep's dataset
            # (r55, live: titles.`title` vs dataset `name`) otherwise makes the loader DROP
            # every row at seed time (NOT-NULL unset) → empty table → 0 release. Best-effort
            # + additive: models.py absent (first upfront call) → no-op; matching names
            # (r54) → byte-identical. The per-milestone re-calls (models.py present) restage
            # the aligned dataset the DB seeds from.
            try:
                from .material_prep import (model_columns_from_models_py,
                                            align_dataset_field_names)
                _cols = model_columns_from_models_py(be / "models.py")
                if _cols:
                    real = align_dataset_field_names(real, _cols)
            except Exception:
                pass
            # #552: fill a DECLARED-but-unseeded Top-N ranking column (top10_rank/rank/
            # *_rank) so the projector's rank numerals / "#N in X Today" badges / data-
            # derived Top-10 rail actually render (they gate on the row's top10_rank being
            # non-null). Keyed off the SCHEMA (an int/nullable rank column the seed leaves
            # null), never a product literal — generalizable to any such app. Deterministic
            # + author-safe (never overwrites author-provided ranks) → byte-identical when
            # the column isn't declared or is already populated; models.py absent (upfront
            # call) → no schema → no-op. Applied at authoring time, so the runtime seed
            # fingerprint stays stable (no re-seed loop).
            try:
                from .material_prep import (model_schema_from_models_py,
                                            enrich_ranking_seed,
                                            align_dataset_id_types)
                _schema = model_schema_from_models_py(be / "models.py")
                if _schema:
                    real = enrich_ranking_seed(real, _schema)
                    # #808: and align the ID TYPES. #483 aligned field NAMES and #552 fills a
                    # ranking column; nothing checked that design-prep's integer ids match a PK
                    # the lane declared TEXT. r145 declared `titles.id TEXT` with every dependent
                    # `title_id TEXT REFERENCES titles(id)`, so the swap left 93 rows across 5
                    # tables pointing at an id space that no longer existed. #807b refuses the
                    # swap when that happens -- which protects the app but discards the real
                    # domain data. This is the root-cause half.
                    real = align_dataset_id_types(real, _schema)
            except Exception:
                pass
            import json as _json
            (be / "seed_dataset.json").write_text(
                _json.dumps(real, indent=2) + "\n", encoding="utf-8")
            return True
    except Exception:
        pass
    return False


def _ensure_seed_json(be: Path, amplify: bool = False) -> None:
    p = be / "seed_data.json"
    if not p.exists():
        p.write_text("{}\n", encoding="utf-8")
        return
    if not amplify:
        return
    # FIX #84 (instagram run-5): a lane-authored REALISTIC-but-thin seed (9 rows vs the
    # 10-row floor) wedged the authored-seed-quality gate for 7 remediation cycles →
    # STUCK-abort, while the live DB was already dense. The framework owns the density
    # floor: clone-and-perturb the lane's own rows up to the floor and write the file
    # back (marker/placeholder seeds are NOT amplified — that stays a lane job).
    try:
        import json as _json
        from .seed_audit import amplify_authored_seed
        data = _json.loads(p.read_text(encoding="utf-8"))
        amped = amplify_authored_seed(data)
        if amped is not None:
            p.write_text(_json.dumps(amped, indent=2) + "\n", encoding="utf-8")
    except Exception:
        pass

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
    _ensure_seed_dataset(be, output_dir)   # F2/F2b: stage the real dataset seed
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
               *, fk_ordinal: int = 0,
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
        # #1069: OFFSET BY THE COLUMN, not just the row. This used to be `i % m`, so
        # two FK columns pointing at the SAME parent got the same parent in every row
        # — every seeded follow was a self-follow and every seeded DM a note to self
        # (6 of 6 rows, both shapes). A DM inbox then renders empty for everyone but
        # the sender, against a gate whose bar is "domain-REALISTIC populated
        # screens", and #1059's recipient-404 could not be surfaced by any seeded row
        # because no row ever had a recipient who was not the sender.
        # `fk_ordinal` is the column's position among this table's FK columns
        # targeting this parent, so ordinal 0 (every single-FK table) is unchanged.
        idx = (i + int(fk_ordinal or 0)) % m
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
        # #993: an INLINE placeholder, not a website. This line used to emit
        # `https://picsum.photos/seed/<table><i>/<size>`, which the sandbox cannot reach:
        # every page rendering a poster logged
        # `Failed to load resource: net::ERR_TUNNEL_CONNECTION_FAILED`, console errors failed
        # the UI-evidence gate, and r161 died on it. #991 taught #512's distributor to treat
        # a stock host as degenerate — but that distributor rewrites seed ROWS, and these
        # URLs live in the generated `seed_data.py` SOURCE, so it never saw them (r162: heal
        # fired 0 times, 31 picsum URLs still in the file).
        #
        # A local /assets/… path would 404 for any row the staged asset pool does not cover,
        # which is the same console error wearing different clothes. A data URI always
        # resolves, needs no network and no file: the generated app becomes self-contained,
        # which is the right property offline as much as in this sandbox.
        w, h = ("200", "200") if ("avatar" in n or "photo" in n) else ("640", "360")
        _hue = (hash(f"{table}{i}") % 360 + 360) % 360
        _svg = (f"<svg xmlns='http://www.w3.org/2000/svg' width='{w}' height='{h}'>"
                f"<rect width='100%' height='100%' fill='hsl({_hue},45%,28%)'/></svg>")
        return "data:image/svg+xml;utf8," + _quote(_svg, safe="")
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
        # #1112: a contract that never writes `references` leaves `fks` empty, and the
        # order then comes out alphabetical — `comments` before `posts` in instagram-run50.
        # With no declared FK there is no constraint, so the inserts still succeed; what
        # they produce is a child row pointing at a parent id that does not exist yet, and
        # after #1110 hands an unparseable parent PK to the sequence the child's value is
        # stale for certain. INFER the edge from the `<name>_id` convention this file
        # already relies on elsewhere (#807's orphan scan reads `_fk[:-3]` the same way).
        # Ordering only — nothing here changes a schema or a constraint.
        for _col in (meta[t].get("cols") or []):     # `cols`, a list of NAMES
            _cn = str(_col if isinstance(_col, str) else (_col or {}).get("name") or "")
            if not _cn.endswith("_id"):
                continue
            _stem = _cn[:-3]
            for _cand in (_stem, _stem + "s", _stem.rstrip("s")):
                if _cand in deps and _cand != t:
                    deps[t].add(_cand)
                    break
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


def _seed_required_fallback(sa_type: Any, i: int) -> Any:
    """#599 — a deterministic value for a NOT NULL column no naming rule covers.

    Type-directed, mirroring what ``_fw_fill_required_defaults`` does for a request body:
    the point is only that the row LOADS. Returns ``_SEED_OMIT`` for a type it cannot
    safely fill, so behaviour there is unchanged."""
    t = str(sa_type or "").lower()
    if "bool" in t:
        return i % 2 == 0
    if "int" in t or "numeric" in t or "float" in t or "decimal" in t:
        return i + 1
    if "date" in t or "time" in t:
        # #600: the emitted loader now HAS a datetime branch (it parses ISO-8601 and drops
        # the key on anything unparseable), so a required timestamp can be filled without
        # risking a driver-level bind failure. #599 had to decline these: 108 of its residue
        # were timestamps, and 5 of those are genuinely `DateTime, nullable=False` with no
        # default in the delivered models — i.e. 5 more silently-emptied tables.
        # Deterministic and monotonic per row, so ordering by the column is stable.
        return f"2024-01-{(i % 28) + 1:02d}T{(i % 24):02d}:00:00"
    if "json" in t:
        return {}
    if "text" in t or "string" in t or "char" in t or "unicode" in t or "uuid" in t:
        return _SEED_TITLES[i % len(_SEED_TITLES)]
    return _SEED_OMIT


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
        # #1069: position of each FK column among this table's FK columns pointing at
        # the SAME parent, so two-party rows (follower/followee, sender/recipient) walk
        # DIFFERENT parents. Column order is the contract's, so this is deterministic.
        _fk_ordinals: Dict[str, int] = {}
        _seen_parents: Dict[str, int] = {}
        for _c in cols:
            _pt = fks.get(_c) or _seed_infer_fk(_c, known_tables)
            if not _pt:
                continue
            _fk_ordinals[_c] = _seen_parents.get(_pt, 0)
            _seen_parents[_pt] = _fk_ordinals[_c] + 1
        rows: List[Dict[str, Any]] = []
        for i in range(counts.get(t, 6)):
            row: Dict[str, Any] = {}
            for c in cols:
                _fk = fks.get(c) or _seed_infer_fk(c, known_tables)
                v = _seed_cell(c, t, i, _fk, counts,
                               fk_ordinal=_fk_ordinals.get(c, 0),
                               pk_name=_pk_name, pk_type=_pk_type, pk_types=pk_types)
                if v is _SEED_OMIT and c in (meta[t].get("required") or ()):
                    # #599: `_seed_cell` omits a column it has no naming rule for, and the
                    # loader then drops the ENTIRE row on the NOT NULL — silently, by design
                    # ("a dropped seed row … uncovered NOT NULL … _seed_dbg prints it when
                    # FW_DEBUG is set"). Measured over the 1196 seeded tables in the arc: 204
                    # columns are NOT NULL with no default of any kind and never set, and the
                    # damage is whole EMPTY TABLES, not missing fields — r134, one of the three
                    # *** MULTI-MILESTONE VALIDATED *** runs, ships `ratings` empty
                    # (`value Text NOT NULL`, seed rows are `{profile_id, title_id}`) AND
                    # `episodes` empty (`season Integer NOT NULL`, never seeded). Top offenders
                    # arc-wide: ratings.value x80, episodes.season x34, genres.slug x15.
                    # 4 instances survive into r134+.
                    #
                    # A required column has no naming rule precisely because it is
                    # domain-specific, so fall back on the column's TYPE — the same thing
                    # `_fw_fill_required_defaults` already does for a request body on the API
                    # path. Deterministic, and only ever reached where the alternative is a
                    # dropped row.
                    v = _seed_required_fallback(meta[t].get("types", {}).get(c), i)
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
        "import json, hashlib, os\n"
        "from pathlib import Path\n"
        "from database import SessionLocal\n"
        "import models\n\n"
        "# audit rank-1 (whack-a-mole eradication): the per-row / per-table seed inserts below\n"
        "# swallow failures BY DESIGN (#218 savepoint) so one bad row can't empty a table — but\n"
        "# silently, so a dropped seed row (FK to a missing parent, uncovered NOT NULL, wrong\n"
        "# type) leaves a table empty/partial and only surfaces as a business_chain 404 a run\n"
        "# later. _seed_dbg prints the dropped row's exception to stderr when FW_DEBUG is set.\n"
        "_FW_DEBUG = os.environ.get('FW_DEBUG', '').strip().lower() in ('1', 'true', 'yes', 'on')\n"
        "def _seed_dbg(where, exc):\n"
        "    if not _FW_DEBUG:\n"
        "        return\n"
        "    import sys as _sys, traceback as _tb\n"
        "    print('[FW_DEBUG] %s: %r' % (where, exc), file=_sys.stderr, flush=True)\n"
        "    _tb.print_exception(type(exc), exc, exc.__traceback__, file=_sys.stderr)\n\n\n"
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
        "def _coerce_nested_for_string_cols(cls, vals):\n"
        "    # FIX #156 (gmrun3: routes 0/8 rows): a REAL-dataset value can be a nested\n"
        "    # list/dict (routes.steps = list-of-dict) while the contract typed the column\n"
        "    # String/Text — the driver cannot adapt it, the INSERT dies at the per-table\n"
        "    # commit, and the rollback drops EVERY row of that table. JSON-serialize a\n"
        "    # nested value ONLY when the target column is String/Text; a native JSON/ARRAY\n"
        "    # column keeps the structured value (Text subclasses String; JSON does not).\n"
        "    # FIX #213 (r16: 0 videos, empty feed): the SCALAR inverse — a mis-typed\n"
        "    # scalar (a caption STRING in an INTEGER count column) likewise dies at the\n"
        "    # per-table commit on postgres and rolls back the whole table. Coerce a\n"
        "    # numeric string to the column's number; neutralize a non-numeric string in\n"
        "    # a numeric column to 0 so the ROW survives (a NULL is left NULL; bools and\n"
        "    # already-correct values are untouched).\n"
        "    try:\n"
        "        from sqlalchemy import (String as _SAStr, Integer as _SAInt,\n"
        "                                Numeric as _SANum, Float as _SAFloat,\n"
        "                                DateTime as _SADT, Date as _SADate)\n"
        "        cols = cls.__table__.columns\n"
        "    except Exception:\n"
        "        return vals\n"
        "    out = dict(vals)\n"
        "    for k, v in vals.items():\n"
        "        if k not in cols:\n"
        "            continue\n"
        "        try:\n"
        "            ctype = cols[k].type\n"
        "        except Exception:\n"
        "            continue\n"
        "        if isinstance(v, (list, dict)):\n"
        "            try:\n"
        "                if isinstance(ctype, _SAStr):\n"
        "                    out[k] = json.dumps(v, ensure_ascii=False, default=str)\n"
        "            except Exception:\n"
        "                pass\n"
        "            continue\n"
        "        if v is None or isinstance(v, bool):\n"
        "            continue\n"
        "        try:\n"
        "            _is_int = isinstance(ctype, _SAInt)\n"
        "            _is_num = isinstance(ctype, (_SANum, _SAFloat))\n"
        "            _is_str = isinstance(ctype, _SAStr)\n"
        "            _is_dt = isinstance(ctype, (_SADT, _SADate))\n"
        "        except Exception:\n"
        "            _is_int = _is_num = _is_str = _is_dt = False\n"
        "        if _is_str and not isinstance(v, str):\n"
        "            # FIX #388 (netflix r13: maturity_rating is TEXT but the seed carried\n"
        "            # an INT 1..5): postgres rejects an int bound to a text column ('type\n"
        "            # text but expression is of type integer'), the per-table commit dies\n"
        "            # and the savepoint ROLLS BACK EVERY title row -> empty catalog -> GET\n"
        "            # /api/titles []=> the whole business_chain 404s -> STUCK abort. A\n"
        "            # scalar destined for a String/Text column becomes its str() form.\n"
        "            out[k] = str(v)\n"
        "        elif _is_int and not isinstance(v, int):\n"
        "            try:\n"
        "                out[k] = int(float(str(v).strip()))\n"
        "            except (ValueError, TypeError):\n"
        "                # #1110: 0 is right for a DATA column (#213 keeps the row\n"
        "                # instead of losing the table) and never right for a PRIMARY\n"
        "                # KEY: every unparseable id collapses to the SAME 0, so the\n"
        "                # first row takes it and the rest die on a UniqueViolation —\n"
        "                # the table keeps ONE row, which is the opposite of what #213\n"
        "                # is for. instagram-run50 seeds UUID ids into SERIAL columns\n"
        "                # and ships a delivered app whose database holds nothing but\n"
        "                # _seed_meta and the tenants row. DROP the key instead and let\n"
        "                # the sequence assign — the same thing #600 does one branch\n"
        "                # below for an unparseable timestamp.\n"
        "                try:\n"
        "                    _is_pk = bool(cols[k].primary_key)\n"
        "                except Exception:\n"
        "                    _is_pk = False\n"
        "                if _is_pk:\n"
        "                    out.pop(k, None)\n"
        "                else:\n"
        "                    out[k] = 0\n"
        "        elif _is_num and not isinstance(v, (int, float)):\n"
        "            try:\n"
        "                out[k] = float(str(v).strip())\n"
        "            except (ValueError, TypeError):\n"
        "                out[k] = 0.0\n"
        "        elif _is_dt and isinstance(v, str):\n"
        "            # #600: the coercion table had str/int/float and NO datetime\n"
        "            # branch, so #599 could not fill a NOT NULL timestamp without\n"
        "            # risking a driver-level bind failure. Parse ISO-8601 here (Z\n"
        "            # accepted) and DROP the key on anything unparseable, so a bad\n"
        "            # value can never take the whole row down with it.\n"
        "            try:\n"
        "                from datetime import datetime as _dtc\n"
        "                out[k] = _dtc.fromisoformat(v.strip().replace('Z', '+00:00'))\n"
        "            except Exception:\n"
        "                out.pop(k, None)\n"
        "    return out\n\n\n"
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
        "    # Base = the lane-authored seed_data.json (users + demo rows), else the embedded _SEED.\n"
        "    base = _SEED\n"
        "    try:\n"
        "        data = json.loads(Path(__file__).with_name('seed_data.json').read_text(encoding='utf-8'))\n"
        "        if isinstance(data, dict) and any(data.values()):\n"
        "            base = data\n"
        "    except Exception:\n"
        "        pass\n"
        "    # F2 dual-source: merge the framework-owned seed_dataset.json (design-prep REAL\n"
        "    # data — the lane cannot author/clobber it) OVER the base; dataset tables win, so\n"
        "    # the DB ships real domain rows deterministically. Absent file → base unchanged.\n"
        "    try:\n"
        "        real = json.loads(Path(__file__).with_name('seed_dataset.json').read_text(encoding='utf-8'))\n"
        "        if isinstance(real, dict) and any(real.values()):\n"
        "            merged = dict(base)\n"
        "            # #264: the dataset REPLACES a table wholesale, so a column its rows omit\n"
        "            # is LOST. seed_dataset.json carries 35 real videos with no tenant_id, so\n"
        "            # they loaded NULL-scoped and EVERY tenant-scoped read came back empty on a\n"
        "            # FULL database (r56: the feed returned {items: []} while an unscoped by-id\n"
        "            # read fetched the very same row). It reads as missing data, so the lanes\n"
        "            # chase a phantom seeding bug. ONLY the scope column is carried over: the\n"
        "            # dataset also omits email (unique -> 9 identical users would fail the\n"
        "            # insert) and parent_id (a self-FK -> every comment a reply to comment 1),\n"
        "            # so a blanket copy would corrupt the seed instead of repairing it.\n"
        "            _SCOPE_KEYS = ('tenant_id', 'tenant', 'org_id', 'organization_id',\n"
        "                           'workspace_id', 'account_id')\n"
        "            # #807b: REFUSE the swap when it would change the table's ID SPACE.\n"
        "            # r145: the lane keyed titles on TEXT slugs ('movie-hollowfield') and every\n"
        "            # dependent row referenced those slugs; the dataset supplies integer ids\n"
        "            # 1..60. Replacing wholesale orphaned 93 rows across 5 tables -- the app\n"
        "            # shipped a 60-title catalogue with ZERO episodes, my_list, ratings or\n"
        "            # continue_watching. Pruning them is honest but still incoherent; keeping the\n"
        "            # lane's own 20 titles WITH their 93 dependent rows is a smaller app that\n"
        "            # actually works. Realism is worth less than coherence. Judged on the\n"
        "            # MAJORITY: a few unresolved rows are genuinely stale links (prune below), a\n"
        "            # majority means the two sources never shared an id space.\n"
        "            _refused = set()\n"
        "            for _t, _rows in real.items():\n"
        "                if not (isinstance(_rows, list) and _rows and isinstance(_rows[0], dict)):\n"
        "                    continue\n"
        "                _new_ids = {_r.get('id') for _r in _rows if isinstance(_r, dict)}\n"
        "                _dep_total = _dep_orphan = 0\n"
        "                for _dt, _drows in base.items():\n"
        "                    if _dt in real or not (isinstance(_drows, list) and _drows):\n"
        "                        continue\n"
        "                    if not isinstance(_drows[0], dict):\n"
        "                        continue\n"
        "                    for _fk in [_c for _c in _drows[0] if str(_c).endswith('_id')]:\n"
        "                        _tgt = str(_fk)[:-3]\n"
        "                        if _t not in (_tgt + 's', _tgt, _tgt + 'es'):\n"
        "                            continue\n"
        "                        for _d in _drows:\n"
        "                            if not isinstance(_d, dict) or _d.get(_fk) is None:\n"
        "                                continue\n"
        "                            _dep_total += 1\n"
        "                            if _d.get(_fk) not in _new_ids:\n"
        "                                _dep_orphan += 1\n"
        "                if _dep_total and _dep_orphan * 2 > _dep_total:\n"
        "                    _refused.add(_t)\n"
        "                    print('[seed] #807b REFUSED the dataset swap for %s: it would orphan '\n"
        "                          '%d of %d dependent row(s) -- the two sources do not share an '\n"
        "                          'id space (lane ids look like %r, dataset ids like %r). Keeping '\n"
        "                          'the lane rows: a smaller COHERENT app beats a larger one with '\n"
        "                          'no episodes/list/ratings.'\n"
        "                          % (_t, _dep_orphan, _dep_total,\n"
        "                             next((_x.get('id') for _x in (base.get(_t) or [])\n"
        "                                   if isinstance(_x, dict)), None),\n"
        "                             next(iter(_new_ids), None)))\n"
        "            for _t, _rows in real.items():\n"
        "                if _t in _refused:\n"
        "                    continue\n"
        "                if not (isinstance(_rows, list) and _rows):\n"
        "                    continue\n"
        "                _base = base.get(_t) or []\n"
        "                _scope = dict()\n"
        "                if _base and isinstance(_base[0], dict):\n"
        "                    for _k in _SCOPE_KEYS:\n"
        "                        if isinstance(_base[0].get(_k), (str, int)):\n"
        "                            _scope[_k] = _base[0][_k]\n"
        "                _out = []\n"
        "                for _r in _rows:\n"
        "                    if isinstance(_r, dict) and _scope:\n"
        "                        _m = dict(_r)\n"
        "                        for _k, _v in _scope.items():\n"
        "                            if _k not in _m:\n"
        "                                _m[_k] = _v\n"
        "                        _out.append(_m)\n"
        "                    else:\n"
        "                        _out.append(_r)\n"
        "                merged[_t] = _out\n"
        "            # #807: replacing a table WHOLESALE can orphan the rows that reference it.\n"
        "            # #264 handled the scope column; nothing checked referential integrity after\n"
        "            # the swap. Measured over the 7 most recent corpus runs: 1 of 7 (r145) had\n"
        "            # EVERY title_genres row pointing at a title id the dataset had replaced --\n"
        "            # 35 of 35 orphaned. Invisible until #803 started folding those labels into\n"
        "            # the detail read, at which point it renders an empty chip row on every page.\n"
        "            # PRUNE, never remap: a remap would invent associations that were never in\n"
        "            # either source. Losing a stale link is correct; inventing one is not.\n"
        "            for _t, _rows in list(merged.items()):\n"
        "                if (_t in real and _t not in _refused) \\\n"
        "                        or not (isinstance(_rows, list) and _rows):\n"
        "                    continue\n"
        "                if not isinstance(_rows[0], dict):\n"
        "                    continue\n"
        "                for _fk in [_c for _c in _rows[0] if str(_c).endswith('_id')]:\n"
        "                    _tgt = str(_fk)[:-3]\n"
        "                    _live = None\n"
        "                    # #807c: ONLY tables the dataset actually replaced. Sourcing this from\n"
        "                    # `merged` instead turned a swap-orphan cleanup into a general\n"
        "                    # referential-integrity pruner over the lane's whole seed, and it\n"
        "                    # deleted valid rows in 3 of 4 corpus runs (r151/r150 lost every\n"
        "                    # my_list/ratings/continue_watching row to a user_id check that has\n"
        "                    # nothing to do with the dataset). A REFUSED table was not replaced,\n"
        "                    # so it is not a source of orphans either.\n"
        "                    for _cand in (_tgt + 's', _tgt, _tgt + 'es'):\n"
        "                        if _cand in real and _cand not in _refused \\\n"
        "                                and isinstance(real.get(_cand), list):\n"
        "                            _live = {_x.get('id') for _x in real[_cand]\n"
        "                                     if isinstance(_x, dict)}\n"
        "                            break\n"
        "                    if not _live:\n"
        "                        continue\n"
        "                    _kept = [_x for _x in _rows\n"
        "                             if not isinstance(_x, dict) or _x.get(_fk) is None\n"
        "                             or _x.get(_fk) in _live]\n"
        "                    if len(_kept) != len(_rows):\n"
        "                        print('[seed] #807 pruned %d of %d %s row(s) whose %s no longer '\n"
        "                              'resolves after the dataset replaced %s -- a stale link is '\n"
        "                              'dropped, never remapped'\n"
        "                              % (len(_rows) - len(_kept), len(_rows), _t, _fk, _tgt))\n"
        "                        _rows = _kept\n"
        "                        merged[_t] = _kept\n"
        "            return merged\n"
        "    except Exception:\n"
        "        pass\n"
        "    return base\n\n\n"
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
        "def _ensure_default_tenant(db, data=None):\n"
        "    # #1105: users.tenant_id is `ForeignKey('tenants.id'), nullable=False` — the\n"
        "    # framework's own spine column — and the seed loader backfills it with\n"
        "    # `row.setdefault('tenant_id', 'default')`. Nothing created that tenant. The\n"
        "    # only writer of a tenants row is oauth_store.register_user, which runs when\n"
        "    # somebody REGISTERS — long after seeding. So every seeded user row died on\n"
        "    # users_tenant_id_fkey, was dropped by the per-row savepoint, and the app came\n"
        "    # up with no demo users at all: 58 of the 59 corpus runs whose seed_data.json\n"
        "    # carries users, 29 of them with a delivered milestone. The one that worked\n"
        "    # had a tenants row from elsewhere. Every content row then FKs to a user that\n"
        "    # does not exist, so any read that JOINs users returns nothing (run-77 ships\n"
        "    # 4 posts and a feed that answers `{'items': []}`), and the demo login the\n"
        "    # loader's own docstring promises cannot work.\n"
        "    # #1111: not just 'default'. A seed's users may carry tenant_id='tenant1'\n"
        "    # while _ORDER excludes `tenants` (the identity spine is not seed-managed),\n"
        "    # so nothing ever creates the tenant they point at and EVERY user row dies\n"
        "    # on users_tenant_id_fkey — three delivered runs (run50, run76, r33) ship\n"
        "    # with no users at all because of it. Create every tenant the seed refers to.\n"
        "    cls = getattr(models, 'Tenant', None)\n"
        "    if cls is None:\n"
        "        return\n"
        "    wanted = ['default']\n"
        "    try:\n"
        "        for _u in ((data or {}).get('users') or []):\n"
        "            _t = (_u or {}).get('tenant_id')\n"
        "            if _t and str(_t) not in wanted:\n"
        "                wanted.append(str(_t))\n"
        "    except Exception:\n"
        "        pass\n"
        "    for _tid in wanted:\n"
        "        _ensure_one_tenant(db, cls, _tid)\n"
        "\n"
        "\n"
        "def _real_owner_ids(db, cache):\n"
        "    # #1113: the ids that actually LANDED, not 1..n. The owner backfill guessed\n"
        "    # `(i % nu) + 1`, which is right only when the users table happens to start\n"
        "    # at 1 and run contiguously. A seed with explicit ids (instagram-run77 uses\n"
        "    # 1001..) or a re-seed onto an advanced sequence makes every guess point at\n"
        "    # nothing, so every child row with no owner dies on the FK and its table\n"
        "    # ships empty. `users` is first in _ORDER, so by the time a child is built\n"
        "    # the real ids exist. Cached per seed pass; empty list keeps the old guess.\n"
        "    if cache.get('ids') is None:\n"
        "        cache['ids'] = []\n"
        "        try:\n"
        "            _uc = getattr(models, _CLASS.get('users', '') or 'User', None)\n"
        "            _upk = (_PK.get('users') or ['id'])[0]\n"
        "            if _uc is not None and hasattr(_uc, _upk):\n"
        "                cache['ids'] = [getattr(_r, _upk) for _r in\n"
        "                                db.query(_uc).order_by(getattr(_uc, _upk)).all()\n"
        "                                if getattr(_r, _upk, None) is not None]\n"
        "        except Exception as _e:\n"
        "            _seed_dbg('real_owner_ids', _e)\n"
        "    return cache['ids']\n"
        "\n"
        "\n"
        "def _ensure_one_tenant(db, cls, tid):\n"
        "    try:\n"
        "        if db.get(cls, tid) is not None:\n"
        "            return\n"
        "    except Exception:\n"
        "        return\n"
        "    cols = {c.name for c in cls.__table__.columns}\n"
        "    vals = {k: v for k, v in (('id', tid), ('name', tid),\n"
        "                              ('slug', tid), ('status', 'active'))\n"
        "            if k in cols}\n"
        "    try:\n"
        "        db.add(cls(**vals))\n"
        "        db.commit()\n"
        "    except Exception as _e:\n"
        "        db.rollback()\n"
        "        _seed_dbg('ensure_tenant %s' % tid, _e)\n\n\n"
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
        "            # FIX #99 (instagram run-17 M3, live): reset.sh clears business rows\n"
        "            # via Base.metadata, but _seed_meta is a RAW-SQL table it never\n"
        "            # touches — the surviving fingerprint made this path SKIP re-seeding\n"
        "            # an EMPTY database (posts=0 after the M2 reset) → every chain\n"
        "            # id-source starved → literal ${x_id} → 422 wedge. Same fingerprint\n"
        "            # + ALL seed-managed business tables empty ⇒ the data was wiped:\n"
        "            # fall through and re-apply. users/tenants excluded (the identity\n"
        "            # spine survives resets and would mask the wipe).\n"
        "            # FIX #130 (instagram-core-di run-49 M3, live) REFINES #99: the old\n"
        "            # guard skipped re-seeding when ANY business table had rows, but a\n"
        "            # PARTIAL state fools that: a child write-handler that does NOT validate\n"
        "            # its parent FK (POST /api/posts/{id}/like -> 201 on a NON-EXISTENT\n"
        "            # post) leaves ORPHAN child rows, so `likes` is non-empty while `posts`\n"
        "            # was wiped -> seed skipped -> posts stays EMPTY -> the repost/like chain\n"
        "            # 404s forever (business_chain wedge). Re-seed when ANY seed-PROVIDED\n"
        "            # content table is EMPTY (incomplete), not only when ALL are; the all-\n"
        "            # empty post-reset wipe #99 targeted is a subset of incomplete.\n"
        "            _seed_incomplete = False\n"
        "            for _t in _ORDER:\n"
        "                if _t in ('users', 'tenants'):\n"
        "                    continue\n"
        "                if not (data.get(_t) or []):\n"
        "                    continue  # seed provides no rows for this table — not a completeness signal\n"
        "                _cls = getattr(models, _CLASS.get(_t, ''), None)\n"
        "                if _cls is None:\n"
        "                    continue\n"
        "                try:\n"
        "                    if db.query(_cls).first() is None:\n"
        "                        _seed_incomplete = True\n"
        "                        break\n"
        "                except Exception:\n"
        "                    continue\n"
        "            if not _seed_incomplete:\n"
        "                # Fully applied — heal the sequences (a container restarted on a\n"
        "                # pre-#56 database boots here with its sequences still inside the\n"
        "                # seeded id range, run-41) and skip re-seeding.\n"
        "                _sync_sequences(db)\n"
        "                return\n"
        "            print('seed: fingerprint matched but a seed-provided table is EMPTY (partial wipe / orphan pollution) — re-seeding (FIX #130)')\n"
        "        if applied is not None:\n"
        "            _reset_seeded_tables(db)\n"
        "        # #1105: BEFORE the first insert — users cannot land without their\n"
        "        # tenant, and every table after users FKs to users.\n"
        "        _ensure_default_tenant(db, data)\n"
        "        # #1112: seed id -> the id the DATABASE actually assigned. #1110 drops an\n"
        "        # unparseable PK so the sequence can assign one, which leaves every child\n"
        "        # row pointing at the seed's original value: instagram-run50's posts all\n"
        "        # die on posts_user_id_fkey after its users finally land. _ORDER is\n"
        "        # parent-first (topo, now including the `<name>_id` inference), so the\n"
        "        # parent's mapping exists by the time its children are built.\n"
        "        _pk_remap = {}\n"
        "        _owner_id_cache = {}\n"
        "        for t in _ORDER:\n"
        "            cls = getattr(models, _CLASS.get(t, ''), None)\n"
        "            if cls is None:\n"
        "                continue\n"
        "            # FIX #135 (instagram run-58, live): a PARTIALLY-wiped table must still\n"
        "            # receive its MISSING seed rows BY PK. The old all-or-nothing 'table\n"
        "            # non-empty -> skip' left the #130 re-seed impotent: test-registered\n"
        "            # users survive a wipe (users non-empty, but WITHOUT the seed ids), the\n"
        "            # users table was skipped wholesale, and every posts row (user_id=1)\n"
        "            # then died on posts_user_id_fkey -> silently swallowed per-row ->\n"
        "            # posts stayed EMPTY forever -> business_chain repost 404 wedge.\n"
        "            # Rows with an explicit PK are upserted-by-existence; rows without one\n"
        "            # keep the legacy skip (can't identify them).\n"
        "            _pk_name = (_PK.get(t) or ['id'])[0]\n"
        "            try:\n"
        "                _has_rows = db.query(cls).first() is not None\n"
        "            except Exception:\n"
        "                continue\n"
        "            owner = _OWNER_COL.get(t)\n"
        "            for i, row in enumerate(data.get(t, [])):\n"
        "                row = dict(row)\n"
        "                if _has_rows:\n"
        "                    _pkv = row.get(_pk_name)\n"
        "                    if _pkv is None:\n"
        "                        continue  # no explicit PK -> legacy skip for this row\n"
        "                    try:\n"
        "                        if db.get(cls, _pkv) is not None:\n"
        "                            continue  # this seed row already present\n"
        "                    except Exception:\n"
        "                        continue\n"
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
        "                    # FIX #217: the spine `users` table is email + name NOT NULL, but a\n"
        "                    # REAL dataset / agent seed frequently omits them (carries only\n"
        "                    # username/display_name). A missing value fails the NOT NULL check\n"
        "                    # and — because the commit is per-TABLE — rolls back EVERY user →\n"
        "                    # 0 users → every FK child (videos.author_id → users) then fails in\n"
        "                    # postgres → the whole app reads empty ('No data yet') AND login is\n"
        "                    # impossible. Backfill both, deterministic + unique (id fallback).\n"
        "                    if not row.get('email'):\n"
        "                        _un = str(row.get('username') or '').strip().lstrip('@')\n"
        "                        _uid = row.get('id') or (i + 1)\n"
        "                        row['email'] = (_un + '@example.com') if _un else ('user' + str(_uid) + '@seed.local')\n"
        "                    if not row.get('name'):\n"
        "                        row['name'] = (row.get('display_name') or str(row.get('username') or '').lstrip('@')\n"
        "                                       or ('User ' + str(row.get('id') or (i + 1))))\n"
        "                elif owner and not row.get(owner):\n"
        "                    _rids = _real_owner_ids(db, _owner_id_cache)\n"
        "                    row[owner] = (_rids[i % len(_rids)] if _rids else (i % nu) + 1)\n"
        "                for _ic in _IMAGE_COL.get(t, []):\n"
        "                    if not row.get(_ic):\n"
        "                        row[_ic] = 'https://picsum.photos/seed/' + t + str(i) + '/400/400'\n"
        "                # #1112: point this row's FKs at the ids the parents really got.\n"
        "                for _fkc in [c for c in list(row) if str(c).endswith('_id')]:\n"
        "                    _fv = row.get(_fkc)\n"
        "                    if _fv is None:\n"
        "                        continue\n"
        "                    _stem = str(_fkc)[:-3]\n"
        "                    for _cand in (_stem, _stem + 's', _stem.rstrip('s')):\n"
        "                        _m = _pk_remap.get(_cand)\n"
        "                        if _m and _fv in _m:\n"
        "                            row[_fkc] = _m[_fv]\n"
        "                            break\n"
        "                _orig_pk = row.get(_pk_name)\n"
        "                _obj = cls(**_coerce_nested_for_string_cols(\n"
        "                    cls, {k: v for k, v in row.items()\n"
        "                          if hasattr(cls, k) and v is not None}))\n"
        "                try:\n"
        "                    # FIX #218: isolate each insert in a SAVEPOINT so ONE bad row\n"
        "                    # (a FK to a missing parent, a duplicate PK, an uncovered NOT\n"
        "                    # NULL) rolls back only ITSELF — not the whole-table commit,\n"
        "                    # which would empty the surface forever ('No data yet').\n"
        "                    # Degrade to a plain add when the session has no savepoint API.\n"
        "                    _bn = getattr(db, 'begin_nested', None)\n"
        "                    if callable(_bn):\n"
        "                        with _bn():\n"
        "                            db.add(_obj)\n"
        "                            db.flush()\n"
        "                    else:\n"
        "                        db.add(_obj)\n"
        "                    # #1112: record it ONLY when the database chose a different id;\n"
        "                    # a row that kept its explicit PK needs no remap and must not\n"
        "                    # add a self-mapping.\n"
        "                    _got_pk = getattr(_obj, _pk_name, None)\n"
        "                    if _orig_pk is not None and _got_pk is not None \\\n"
        "                            and _got_pk != _orig_pk:\n"
        "                        _pk_remap.setdefault(t, {})[_orig_pk] = _got_pk\n"
        "                except Exception as _e:\n"
        "                    _seed_dbg('seed_row_drop %s[%d]' % (t, i), _e)\n"
        "                    pass\n"
        "            try:\n"
        "                db.commit()\n"
        "            except Exception as _e:\n"
        "                _seed_dbg('seed_commit_rollback %s' % t, _e)\n"
        "                db.rollback()\n"
        "        _sync_sequences(db)\n"
        "        _store_fingerprint(db, fp)\n"
        "    finally:\n"
        "        db.close()\n"
        "        _ensure_canonical_rows()\n"  # FIX #72: heal canonical rows on EVERY boot
        "        _concentrate_demo_content()\n"  # FIX #74: fill the demo user's screens
    )
    return body


# FIX #196 — user→content INTERACTION verbs whose action endpoint
# (POST /api/<parent>/{id}/<verb>) needs a join table to record WHO did it.
# follow/subscribe/block are user→USER (dual-role FKs, ambiguous) → EXCLUDED.
_INTERACTION_VERBS = {
    "like": "likes", "save": "saves", "favorite": "favorites",
    "favourite": "favorites", "bookmark": "bookmarks", "watchlist": "watchlists",
    "pin": "pins", "star": "stars", "react": "reactions", "vote": "votes",
    "upvote": "votes", "downvote": "votes",
}
# an "un-" prefix undoes the same relation → shares the base table (unlike→likes).
_INTERACTION_UNDO_PREFIX = "un"

# FIX #204 — user→USER verbs (POST /api/users/{id}/follow): a self-referential
# join with TWO distinguishable user FKs. verb → (table, actor_fk, target_fk);
# target_fk MUST be a name the projector's _target_fk recognises
# (_TARGET_FK_NAMES) so it binds the path user, and the actor_fk is the caller.
_USER_USER_VERBS = {
    "follow": ("follows", "follower_id", "followed_id"),
}


def _pk_type_of(table: Mapping[str, Any]) -> str:
    """The declared type of ``table``'s primary key, ``"text"`` when it has none.

    #1095: this hand-rolled `table["schema"]["columns"]` and so saw NOTHING in the FLATTENED
    `{"columns": [...]}` shape — returning its `"text"` default for every table, including
    `integer + primary_key=True`. `_columns_of` is the shape-tolerant accessor that exists for
    exactly this and is already imported and used twice in this module; this was the one place
    that did not use it.

    What it cost, found by probing 20 real contracts against a live postgres: the FK columns
    `interaction_tables_to_provision` (#196) derives from the parent were all typed `text`, so
    `render_models`' FK reconciliation flipped the REFERENCED pk to match —
    run51's `posts.id` went `Integer` -> `Column(Text, default=uuid)` — while `route_projector`
    typed the `{id}` path param from the CONTRACT (`serial primary key` -> `int`). Every by-id
    read and write of that resource then issued `WHERE posts.id = $1::INTEGER` against a TEXT
    column: `operator does not exist: text = integer`, HTTP 500, on the app's central resource.
    (`users.id` was mistyped identically but survives — the spine pins users/tenants PK
    categories, so the reconciler skips them.)"""
    for c in _columns_of(table or {}):
        if isinstance(c, dict) and (c.get("primary_key") or c.get("pk")):
            return str(c.get("type") or "text")
    return "text"


def _table_has_fk_to(table: Mapping[str, Any], target: str) -> bool:
    """#1106: completes #1095 two functions later, on the same two counts.

    The hand-rolled `schema.columns` misses a FLATTENED table record, which
    `_columns_of` exists to tolerate, and `c.get("references")` misses the two other
    FK spellings this file's own `_fk_target` accepts — an explicit `fk` field and an
    inline `REFERENCES` inside the type. A miss here is not inert: this decides
    whether an interaction join table ALREADY EXISTS (#196), so a false answer
    provisions a duplicate of a table the contract already declared.

    Neither shape occurs in the corpus today (0 of 865 table records are flattened,
    0 of 856 FK columns are inline), so this changes nothing that is running; it
    stops the two accessors that exist for these shapes from being bypassed here."""
    for c in (_columns_of(table or {}) or []):
        if isinstance(c, dict) and str(_fk_target(c) or "").split(".")[0] == target:
            return True
    return False


def interaction_tables_to_provision(
    endpoints: List[Mapping[str, Any]], tables: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """FIX #196 (r6 root): return join-table specs to add for interaction action
    endpoints (POST /api/<parent>/{param}/<verb>) that have NO backing join table
    — the like/save/favorite BUTTON otherwise 404s (projector #124). Named to the
    verb's canonical plural so _resource_model resolves the action segment to it;
    one table per verb carrying a user_id FK + one nullable <parent>_id FK per
    distinct likeable parent (multi-parent → shared table). Conservative: skips
    when a backing table already exists, when the parent has no table, and for
    the excluded user→user verbs. Pure; never raises."""
    try:
        tbl_lower = {str(k).lower(): v for k, v in (tables or {}).items()}
        # users is the framework SPINE table — always present in the rendered app
        # even when the caller's contract dict omits it. Guarantee it so the actor
        # FK resolves and detection isn't skipped on a spine-only users case.
        tbl_lower.setdefault("users", {"name": "users", "schema": {"columns": [
            {"name": "id", "primary_key": True, "type": "integer"}]}})
        # verb -> {parent_table, ...} collected across all interaction endpoints
        by_verb: Dict[str, set] = {}
        for ep in (endpoints or []):
            if str(ep.get("method", "")).upper() != "POST":
                continue
            segs = [s for s in str(ep.get("path", "")).strip("/").split("/") if s]
            if segs and segs[0] == "api":
                segs = segs[1:]
            # shape: <parent> {param} <verb>
            if len(segs) != 3:
                continue
            parent, param, verb = segs
            if not (param.startswith("{") or param.startswith(":")):
                continue
            verb = verb.lower()
            if verb.startswith(_INTERACTION_UNDO_PREFIX) and verb[2:] in _INTERACTION_VERBS:
                verb = verb[2:]
            if verb not in _INTERACTION_VERBS:
                continue
            parent_l = parent.lower()
            # the parent must be a real content table (not users → that's follow-shaped)
            if parent_l == "users" or (parent_l not in tbl_lower
                                       and parent_l.rstrip("s") not in tbl_lower):
                continue
            by_verb.setdefault(verb, set()).add(parent_l)
        out: List[Dict[str, Any]] = []
        uid_type = _pk_type_of(tbl_lower["users"])
        for verb, parents in sorted(by_verb.items()):
            table_name = _INTERACTION_VERBS[verb]
            # PROVISION IFF #198 can't resolve an EXISTING join. Candidate names
            # mirror #198's resolution exactly: the bare `<verb>s`/`<verb>` AND the
            # parent-prefixed `<parent_singular>_<verb>[s]` (video_likes) — so #196
            # never creates a duplicate `likes` when the lane already modeled
            # `video_likes`. The verb-in-name check (via the candidate set) keeps a
            # CONTENT table like `comments` (user+video FKs but no verb in its name)
            # from being mistaken for the like join.
            _cands = {table_name, verb}
            for p in parents:
                _ps = (p.rstrip("s") or p)
                _cands |= {f"{_ps}_{verb}", f"{_ps}_{verb}s", f"{p}_{verb}", f"{p}_{verb}s"}
            _resolved = False
            for _cn in _cands:
                _ex = tbl_lower.get(_cn)
                if isinstance(_ex, dict) and _table_has_fk_to(_ex, "users") and any(
                        _table_has_fk_to(_ex, p.rstrip("s")) or _table_has_fk_to(_ex, p)
                        for p in parents):
                    _resolved = True
                    break
            if _resolved:
                continue
            cols = [{"name": "id", "primary_key": True, "type": "integer"},
                    {"name": "user_id", "references": "users.id", "type": uid_type}]
            seen_fk = set()
            for p in sorted(parents):
                p_table = p if p in tbl_lower else (p.rstrip("s") if p.rstrip("s") in tbl_lower else p)
                singular = p_table.rstrip("s") or p_table
                fk = singular + "_id"
                if fk in seen_fk:
                    continue
                seen_fk.add(fk)
                cols.append({"name": fk, "references": f"{p_table}.id",
                             "type": _pk_type_of(tbl_lower[p_table])})
            cols.append({"name": "created_at", "type": "timestamp"})
            out.append({
                "name": table_name,
                "schema": {"columns": cols},
                "metadata": {"framework_provisioned": True,
                             "owner_scoped_reads": False},
                "status": "implemented",
                "provider": "framework",
            })

        # FIX #204: user→USER follow (POST /api/users/{param}/follow). #196 above
        # excludes it (parent==users), so provision the self-referential `follows`
        # here with two distinguishable user FKs — the projector then serves the
        # follow button by construction (verified: followed_id←path, follower_id←caller).
        _uu_seen: set = set()
        for ep in (endpoints or []):
            if str(ep.get("method", "")).upper() != "POST":
                continue
            segs = [s for s in str(ep.get("path", "")).strip("/").split("/") if s]
            if segs and segs[0] == "api":
                segs = segs[1:]
            if len(segs) != 3:
                continue
            parent, param, verb = segs
            if parent.lower() != "users" or not (param.startswith("{") or param.startswith(":")):
                continue
            verb = verb.lower()
            if verb.startswith(_INTERACTION_UNDO_PREFIX) and verb[2:] in _USER_USER_VERBS:
                verb = verb[2:]
            spec = _USER_USER_VERBS.get(verb)
            if not spec or verb in _uu_seen:
                continue
            _uu_seen.add(verb)
            tname, actor_fk, target_fk = spec
            existing = tbl_lower.get(tname)
            # skip if a real self-referential join already exists (2 user FKs)
            if isinstance(existing, dict):
                # #1106: same two accessors as _table_has_fk_to above — a flattened
                # record or an inline FK read as "no user FKs here" and re-provisioned
                # a self-referential join the contract already had.
                _ufks = sum(1 for c in (_columns_of(existing) or [])
                            if isinstance(c, dict)
                            and str(_fk_target(c) or "").split(".")[0] == "users")
                if _ufks >= 2:
                    continue
            out.append({
                "name": tname,
                "schema": {"columns": [
                    {"name": "id", "primary_key": True, "type": "integer"},
                    {"name": actor_fk, "references": "users.id", "type": uid_type},
                    {"name": target_fk, "references": "users.id", "type": uid_type},
                    {"name": "created_at", "type": "timestamp"}]},
                "metadata": {"framework_provisioned": True, "owner_scoped_reads": False},
                "status": "implemented", "provider": "framework",
            })
        return out
    except Exception:
        return []


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

    # FIX #196: provision missing interaction join tables (like/save/favorite/…)
    # BEFORE rendering models/DDL/seed, so the projector's existing action-mapping
    # (#124) serves POST /api/<parent>/{id}/<verb> end-to-end instead of 404ing a
    # non-functional button (r6's business_chain killer). Additive + strict
    # detection → apps with no interaction endpoints are byte-identical.
    try:
        _provision = interaction_tables_to_provision(endpoints, tables)
        if _provision:
            tables = dict(tables or {})
            for _spec in _provision:
                tables.setdefault(_spec["name"], _spec)
    except Exception:
        pass

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
    # The framework deliberately does not write seed_data.json's CONTENT — that DATA file is
    # the backend agent's to AUTHOR with domain-aware values. (#852: read this together with
    # `_ensure_seed_json` three lines below, which DOES create the file as empty ``{}``
    # only-if-absent so the Dockerfile's ``*.json`` glob has a match. The two comments read as a
    # contradiction; the code is coherent, and the distinction is content vs existence.) Shipping a COMPLETE default here
    # anchored the agent to placeholder content (live 2026-06-29: it kept the framework's
    # "Getting Started"/"Project Overview" subjects + generic bodies instead of authoring
    # real ones). So we ship only the LOADER, whose embedded _SEED is the runtime fallback
    # (the app is still never blank). render_seed_json stays for tooling/inspection.
    w("auth_dependency.py", _AUTH_DEPENDENCY_PY)
    w("main.py", render_skeleton_main(endpoints, tables))
    w("schemas.py", _SCHEMAS_PY)
    _ensure_seed_json(be, amplify=True)   # FIX #84: density floor by construction
    _ensure_seed_dataset(be, output_dir)  # F2b: re-assert the real dataset seed every milestone
    w("pyproject.toml", render_pyproject(be))
    w("Dockerfile", _DOCKERFILE)
    w("reset.sh", _RESET_SH)
    return {"written": list(written), "backend_dir": str(be)}
