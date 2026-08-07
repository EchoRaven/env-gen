"""Contract-completeness oracle (#557, R1).

Every other test/coverage layer in the generator derives from the DECLARED
endpoint contract, and NOTHING checks the declared contract against the INTENDED
feature set. So a MISSING endpoint is invisible: ``business_chain_api_coverage``
counts the declared endpoints (15/15 = "100%") while a needed write-path (e.g. a
Continue-Watching progress ``POST``/``PUT``) simply does not exist — the
functional gate goes green with the feature broken. The signature "resume
watching" then reflects only seed data because there is no play/progress write
endpoint.

This module reconciles THREE already-present sources and emits blocking-capable
check results keyed off STRUCTURE, never off product literals:

1. ``feature_inventory {entities, flows}`` — emitted at M1 kickoff and persisted
   inside the kickoff WorkHub document(s) under ``metadata.decisions[*].content``.
   Two shapes exist in the wild: the validator shape ``{entities:[...],
   flows:[...]}`` and the frontend's per-feature map ``{feature_name: prose}``.
   Both are normalized to ``(entities, flows)`` here.
2. Registered TABLES — ``registryhub.list_tables()``. A STATE-BEARING entity is a
   table carrying a mutable, non-FK, non-timestamp, non-PK scalar *data* column
   (``progress_seconds``, ``status``, ``value``, ``position``, ``is_watched`` …).
   ``_is_state_column`` / ``_state_entities`` classify these generically.
3. Endpoint SURFACE — ``registryhub.get_endpoints()`` — the actual declared /
   implemented routes.

Emitted checks (each a dict ``{check_id, ok, severity, entity/flow, detail,
suggested_fix}``):

* ``completeness_state_entity_no_write`` — a state-bearing table that is READABLE
  (has a GET) but has NO POST/PUT/PATCH endpoint: the feature can be read but
  never written (the Continue-Watching class). severity ``error``.
* ``completeness_flow_no_write`` — a declared feature-inventory FLOW whose verb
  implies mutation (play/resume/watch/rate/like/add/save/update/track/progress/
  mark/toggle/start/create) but no write endpoint backs it. severity ``warn``.
* ``completeness_entity_no_read`` — a declared entity with no GET (secondary).
  severity ``warn``.

Pure read-side over the hubs. Best-effort: never raises — a hiccup degrades to an
empty report rather than wedging the delivery gate.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Vocabulary (structural, generalizable — NO product literals)
# ---------------------------------------------------------------------------

# Column-name word-parts that denote MUTABLE per-row state — the kind of value a
# feature UPDATES over the life of a row (progress, playback position, status,
# toggles, counters). Matched EXACTLY against a name's word-parts (split on "_"
# and camelCase) so ``last_name`` / ``real_estate`` / ``top10_rank`` do NOT
# collide with ``last`` / ``state`` / ``rank``. Deliberately EXCLUDES catalog /
# descriptive tokens (name, title, rating, rank, duration, year, …) so a
# read-only reference/catalog table is never mistaken for a state entity.
_STATE_TOKENS = frozenset({
    # playback / progress
    "progress", "seconds", "secs", "elapsed", "remaining", "position", "offset",
    "timecode", "watched", "played", "viewed", "seen", "watchtime",
    # lifecycle / status
    "status", "state", "stage", "phase", "step", "completed", "complete",
    "finished", "done", "active", "inactive", "enabled", "disabled", "paused",
    "archived", "pinned",
    # counters / measures that mutate
    "count", "score", "level", "points", "streak", "quantity", "qty", "amount",
    "balance", "total", "value", "percent", "pct",
    # per-user toggle / preference state
    "read", "unread", "liked", "disliked", "favorite", "favorited",
    "bookmarked", "saved", "checked", "toggled", "selected",
})

# Descriptive / identity / catalog column names that are set-once content, never
# mutable state. A belt-and-suspenders guard: even if such a name ever shared a
# word-part with a state token, it stays out of the state set.
_DESCRIPTIVE_TOKENS = frozenset({
    "name", "title", "label", "slug", "code", "url", "uri", "link", "href",
    "image", "img", "avatar", "icon", "logo", "banner", "poster", "backdrop",
    "thumbnail", "photo", "picture", "color", "colour", "email", "username",
    "handle", "phone", "address", "bio", "caption", "summary", "description",
    "desc", "content", "body", "text", "message", "note", "notes", "year",
    "genre", "genres", "language", "lang", "category", "kind", "type", "rating",
    "password", "hash", "secret", "token", "key",
})

_BOOL_TYPES = frozenset({"bool", "boolean", "tinyint(1)", "bit"})
_BOOL_PREFIXES = ("is_", "has_", "was_", "did_", "can_", "should_", "are_")

_TIMESTAMP_TYPE_HINTS = ("timestamp", "datetime", "date", "time")
_TIMESTAMP_NAMES = frozenset({"created", "updated", "timestamp", "created_at",
                              "updated_at", "deleted_at", "modified_at"})

# Verbs whose presence in a FLOW name implies a mutation (write) is required.
_MUTATION_VERBS = frozenset({
    "play", "resume", "watch", "rate", "like", "add", "save", "update", "track",
    "progress", "mark", "toggle", "start", "create",
})

_WRITE_METHODS = frozenset({"POST", "PUT", "PATCH"})

# Fallback spine set (framework-owned identity/tenancy tables) if the canonical
# import is unavailable — these are NOT app features and are always excluded.
_SPINE_FALLBACK = frozenset({
    "tenants", "users", "oauth_clients", "oauth_authorization_codes",
})


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _norm(s: Any) -> str:
    return str(s or "").strip().lower()


def _split_ident(name: Any) -> List[str]:
    """Split an identifier into lower-case word parts on ``_``/``-``/space and
    camelCase boundaries: ``progress_seconds`` -> ['progress','seconds'];
    ``isWatched`` -> ['is','watched']."""
    s = str(name or "").strip()
    if not s:
        return []
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", s)  # camelCase -> snake
    parts = re.split(r"[^A-Za-z0-9]+", s)
    return [p.lower() for p in parts if p]


def _is_pk_name(name_lc: str) -> bool:
    return name_lc in ("id", "pk", "uuid", "guid")


def _is_fk_name(name_lc: str) -> bool:
    # ``profile_id`` / ``title_id`` / ``user_id`` are foreign keys; the bare
    # ``id`` is the PK (handled above), never an FK.
    return name_lc.endswith("_id") and name_lc != "id"


def _is_timestamp(name_lc: str, type_lc: str) -> bool:
    if any(h in type_lc for h in _TIMESTAMP_TYPE_HINTS):
        return True
    if name_lc in _TIMESTAMP_NAMES or name_lc.endswith("_at"):
        return True
    return False


def _is_state_column(name: Any, type_: Any) -> bool:
    """Generalizable classifier: is ``(name, type)`` a MUTABLE state column?

    A state column is a scalar *data* column a feature updates over a row's life
    (progress/status/toggle/counter). It is NOT a primary key, NOT a foreign key,
    NOT a timestamp, and NOT a set-once descriptive/identity/catalog column.

    Signals (any one is sufficient):
      * a boolean type or an ``is_/has_/was_/…`` flag name  → a toggle;
      * a name whose word-parts hit the mutable-state vocabulary
        (``progress``/``status``/``position``/``value``/``watched``/…).

    Deliberately conservative so a read-only reference/catalog table (whose only
    non-key column is ``name``/``title``/``rating``/``rank``…) is never
    misclassified. Standalone-usable (does not need the full column record)."""
    n = _norm(name)
    t = _norm(type_)
    if not n:
        return False
    if _is_pk_name(n) or _is_fk_name(n) or _is_timestamp(n, t):
        return False
    parts = _split_ident(n)
    # descriptive/identity/catalog column → set-once content, not state.
    if parts and all(p in _DESCRIPTIVE_TOKENS for p in parts):
        return False
    # boolean flags are toggle state.
    if t in _BOOL_TYPES or any(n.startswith(p) for p in _BOOL_PREFIXES):
        return True
    # explicit mutable-state name tokens.
    if any(p in _STATE_TOKENS for p in parts):
        return True
    return False


def _column_records(table: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Normalize a table record's columns to a list of dicts, tolerating both the
    ``schema.columns`` list shape and the flat ``columns`` dict/list shapes."""
    if not isinstance(table, dict):
        return []
    cols = None
    schema = table.get("schema")
    if isinstance(schema, dict):
        cols = schema.get("columns")
    if cols is None:
        cols = table.get("columns")
    out: List[Dict[str, Any]] = []
    if isinstance(cols, list):
        for c in cols:
            if isinstance(c, dict) and c.get("name"):
                out.append(c)
    elif isinstance(cols, dict):
        for cname, cval in cols.items():
            if isinstance(cval, dict):
                out.append({"name": cname, **cval})
            else:
                out.append({"name": cname, "type": cval})
    return out


def _column_is_fk(col: Dict[str, Any]) -> bool:
    if col.get("references") or col.get("foreign_key") or col.get("fk"):
        return True
    return _is_fk_name(_norm(col.get("name")))


def _column_is_pk(col: Dict[str, Any]) -> bool:
    if col.get("primary_key") or col.get("pk"):
        return True
    return _is_pk_name(_norm(col.get("name")))


def _table_state_columns(table: Dict[str, Any]) -> List[str]:
    """State-bearing column names for one table (empty ⇒ not a state entity)."""
    out: List[str] = []
    for col in _column_records(table):
        if _column_is_pk(col) or _column_is_fk(col):
            continue
        if _is_state_column(col.get("name"), col.get("type")):
            out.append(str(col.get("name")))
    return out


def _spine_tables() -> frozenset:
    try:
        from .database_scaffold import _SPINE_OWNED_TABLES
        return frozenset(str(t).lower() for t in _SPINE_OWNED_TABLES)
    except Exception:
        return _SPINE_FALLBACK


def _state_entities(tables: Dict[str, Any]) -> Dict[str, List[str]]:
    """Map ``{table_name: [state_column, ...]}`` for every APP (non-spine,
    non-deprecated) table that carries at least one mutable state column."""
    spine = _spine_tables()
    out: Dict[str, List[str]] = {}
    for key, rec in (tables or {}).items():
        if key == "_meta" or not isinstance(rec, dict):
            continue
        name = str(rec.get("name") or key)
        if name.lower() in spine:
            continue
        if _norm(rec.get("status")) == "deprecated":
            continue
        cols = _table_state_columns(rec)
        if cols:
            out[name] = cols
    return out


# ---------------------------------------------------------------------------
# Endpoint-surface matching
# ---------------------------------------------------------------------------

def _entity_tokens(name: Any) -> set:
    """Path-segment tokens an endpoint could carry for this entity: the raw name,
    its no-separator collapse, and naive singular/plural — all underscore-normalized
    (so a ``/continue-watching`` segment matches a ``continue_watching`` table)."""
    base = re.sub(r"[^a-z0-9]+", "_", _norm(name)).strip("_")
    if not base:
        return set()
    toks = {base, base.replace("_", "")}
    if base.endswith("ies"):
        toks.add(base[:-3] + "y")
    elif base.endswith("ses"):
        toks.add(base[:-2])
    elif base.endswith("s"):
        toks.add(base[:-1])
    else:
        toks.add(base + "s")
    # add collapsed forms of the singular/plural variants too
    return {t for t in (toks | {t.replace("_", "") for t in toks}) if t}


def _path_segments(path: Any) -> List[str]:
    """Concrete (non-param) path segments, underscore-normalized + lower-cased."""
    out: List[str] = []
    for seg in str(path or "").split("/"):
        seg = seg.strip()
        if not seg or seg.startswith("{") or seg.startswith(":"):
            continue
        out.append(seg.lower().replace("-", "_"))
    return out


def _endpoint_touches(path: Any, tokens: set) -> bool:
    if not tokens:
        return False
    for seg in _path_segments(path):
        if seg in tokens or seg.replace("_", "") in tokens:
            return True
    return False


def _iter_endpoints(endpoints: Dict[str, Any]):
    for key, rec in (endpoints or {}).items():
        if key == "_meta" or not isinstance(rec, dict):
            continue
        if not str(rec.get("path") or "").strip():
            continue
        if _norm(rec.get("status")) == "deprecated":
            continue
        yield rec


def _methods_touching(endpoints: Dict[str, Any], tokens: set) -> set:
    """The set of HTTP methods on endpoints whose path touches ``tokens``."""
    methods: set = set()
    for rec in _iter_endpoints(endpoints):
        if _endpoint_touches(rec.get("path"), tokens):
            methods.add(_norm(rec.get("method")).upper())
    return methods


# ---------------------------------------------------------------------------
# feature_inventory (source #1) — read from the persisted kickoff document(s)
# ---------------------------------------------------------------------------

def _load_feature_inventory(hubs) -> Dict[str, Any]:
    """Best-effort read of the M1 ``feature_inventory`` from the kickoff WorkHub
    document(s). Returns the raw inventory dict (either shape), or ``{}``."""
    wh = getattr(hubs, "workhub", None)
    if wh is None or not hasattr(wh, "list_documents"):
        return {}
    try:
        docs = wh.list_documents(kind="kickoff") or []
    except Exception:
        return {}
    candidates: List[Dict[str, Any]] = []
    for doc in docs:
        if not isinstance(doc, dict):
            continue
        meta = doc.get("metadata") or {}
        for dec in (meta.get("decisions") or []):
            if not isinstance(dec, dict):
                continue
            content = dec.get("content")
            if not isinstance(content, dict):
                continue
            fi = content.get("feature_inventory")
            if isinstance(fi, dict) and fi:
                candidates.append(fi)
    if not candidates:
        return {}
    # Prefer the canonical {entities|flows} shape; else the richest per-feature map.
    for fi in candidates:
        if "entities" in fi or "flows" in fi:
            return fi
    return max(candidates, key=len)


def _normalize_inventory(fi: Dict[str, Any]) -> Tuple[List[str], List[str]]:
    """Normalize either inventory shape to ``(entities, flows)`` name lists."""
    if not isinstance(fi, dict):
        return [], []
    if "entities" in fi or "flows" in fi:
        entities = [str(e).strip() for e in (fi.get("entities") or []) if str(e).strip()]
        flows = [str(f).strip() for f in (fi.get("flows") or []) if str(f).strip()]
        return entities, flows
    # non-canonical per-feature map: keys are feature/flow names
    flows = [str(k).strip() for k in fi.keys() if str(k).strip()]
    return [], flows


def _flow_mutation_verb(flow_name: str) -> Optional[str]:
    """Return the mutation verb a flow name implies, else ``None``. Word-part
    matched (exact for short verbs, prefix for len>=4) so ``continue_watching`` ->
    ``watch`` and ``player`` -> ``play`` while ``display`` does NOT hit ``play``."""
    for p in _split_ident(flow_name):
        for v in _MUTATION_VERBS:
            if p == v or (len(v) >= 4 and p.startswith(v)):
                return v
    return None


# ---------------------------------------------------------------------------
# Result / report shapes (mirror runtime/coverage_audit.py)
# ---------------------------------------------------------------------------

@dataclass
class CompletenessResult:
    check_id: str
    ok: bool
    severity: str  # "error" | "warn"
    detail: str
    entity: Optional[str] = None
    flow: Optional[str] = None
    missing_verb: Optional[str] = None
    suggested_fix: str = ""

    def to_dict(self) -> dict:
        return {
            "check_id": self.check_id,
            "ok": self.ok,
            "severity": self.severity,
            "entity": self.entity,
            "flow": self.flow,
            "missing_verb": self.missing_verb,
            "detail": self.detail,
            "suggested_fix": self.suggested_fix,
        }


@dataclass
class CompletenessReport:
    results: List[CompletenessResult] = field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        return not any(not r.ok for r in self.results)

    def problems(self, severity: Optional[str] = None) -> List[CompletenessResult]:
        return [r for r in self.results
                if not r.ok and (severity is None or r.severity == severity)]

    def blocking_check_ids(self, severity: str = "error") -> List[str]:
        seen: List[str] = []
        for r in self.problems(severity):
            if r.check_id not in seen:
                seen.append(r.check_id)
        return seen

    def to_dict(self) -> dict:
        return {
            "results": [r.to_dict() for r in self.results],
            "is_clean": self.is_clean,
            "problem_count": len(self.problems()),
        }


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

def state_entities_missing_write(tables: Dict[str, Any],
                                 endpoints: Dict[str, Any]) -> Dict[str, List[str]]:
    """The state-bearing entities that are READABLE (have a GET) but have NO
    POST/PUT/PATCH — i.e. the EXACT set ``check_state_entity_no_write`` flags,
    returned as ``{entity: [state_column, ...]}``.

    This is the ONE detection shared by BOTH sides of the loop: the oracle (#557,
    ``check_state_entity_no_write``, which turns each into a blocking result) AND
    the framework HEAL (#556, ``route_projector.project_state_write_endpoints``,
    which projects an idempotent upsert write handler for each). Sharing a single
    classifier guarantees the heal closes exactly what the oracle detects — the
    two can never drift. Precise scope: readable-but-not-writable (the
    Continue-Watching class). A state table with NO endpoints at all is a
    different bug (dead table — coverage_audit's job) and is deliberately excluded
    so neither the oracle nor the heal touches an internal/unexposed table."""
    out: Dict[str, List[str]] = {}
    for entity, cols in _state_entities(tables).items():
        tokens = _entity_tokens(entity)
        methods = _methods_touching(endpoints, tokens)
        if "GET" in methods and not (methods & _WRITE_METHODS):
            out[entity] = cols
    return out


def check_state_entity_no_write(tables: Dict[str, Any],
                                endpoints: Dict[str, Any]) -> List[CompletenessResult]:
    """A state-bearing table that is READABLE (has a GET) but has NO
    POST/PUT/PATCH endpoint — the feature can be read but never written."""
    out: List[CompletenessResult] = []
    for entity, cols in state_entities_missing_write(tables, endpoints).items():
        col_list = ", ".join(cols)
        out.append(CompletenessResult(
            check_id="completeness_state_entity_no_write",
            ok=False, severity="error", entity=entity, missing_verb="POST/PUT/PATCH",
            detail=(f"state-bearing table `{entity}` (mutable column(s): {col_list}) "
                    f"has a GET but NO POST/PUT/PATCH endpoint — the feature can be "
                    f"READ but never WRITTEN. The declared-contract coverage gate "
                    f"cannot see this because the write endpoint was never declared."),
            suggested_fix=(f"Declare + implement a write endpoint for `{entity}` "
                           f"(e.g. POST or PUT on its collection) so `{col_list}` "
                           f"can be persisted, then register it in RegistryHub."),
        ))
    return out


def check_flow_no_write(hubs, endpoints: Dict[str, Any],
                        flows: List[str]) -> List[CompletenessResult]:
    """A declared feature-inventory FLOW whose verb implies mutation but which no
    write (POST/PUT/PATCH) endpoint backs."""
    out: List[CompletenessResult] = []
    for flow in flows:
        verb = _flow_mutation_verb(flow)
        if not verb:
            continue
        tokens = _entity_tokens(flow)
        methods = _methods_touching(endpoints, tokens)
        if methods & _WRITE_METHODS:
            continue  # a write endpoint plausibly backs the flow
        out.append(CompletenessResult(
            check_id="completeness_flow_no_write",
            ok=False, severity="warn", flow=flow, missing_verb=verb,
            detail=(f"declared flow `{flow}` implies a mutation (verb `{verb}`) but no "
                    f"POST/PUT/PATCH endpoint backs it — the flow can be viewed but not "
                    f"performed. Feature declared, write-path missing."),
            suggested_fix=(f"Add + register a write endpoint for the `{flow}` flow "
                           f"(the `{verb}` action) so the declared feature actually works."),
        ))
    return out


def check_entity_no_read(endpoints: Dict[str, Any],
                         entities: List[str]) -> List[CompletenessResult]:
    """(Secondary) a declared entity with no GET endpoint."""
    out: List[CompletenessResult] = []
    for entity in entities:
        tokens = _entity_tokens(entity)
        methods = _methods_touching(endpoints, tokens)
        if "GET" in methods:
            continue
        out.append(CompletenessResult(
            check_id="completeness_entity_no_read",
            ok=False, severity="warn", entity=entity, missing_verb="GET",
            detail=(f"declared entity `{entity}` has NO GET endpoint — it can never be "
                    f"read by the app."),
            suggested_fix=(f"Add + register a GET endpoint for `{entity}` so the entity "
                           f"is reachable from the frontend."),
        ))
    return out


def compute_completeness(hubs) -> CompletenessReport:
    """Reconcile feature_inventory ∪ state-bearing tables against the endpoint
    surface and return a structured report. Best-effort; never raises."""
    report = CompletenessReport()
    try:
        registryhub = getattr(hubs, "registryhub", None)
        schema_hub = getattr(hubs, "schema_hub", None) or registryhub
        endpoints: Dict[str, Any] = {}
        tables: Dict[str, Any] = {}
        if registryhub is not None and hasattr(registryhub, "get_endpoints"):
            try:
                endpoints = registryhub.get_endpoints() or {}
            except Exception:
                endpoints = {}
        table_src = None
        # Prefer registryhub.list_tables (task spec); schema_hub is the same object.
        for src in (registryhub, schema_hub):
            if src is not None and hasattr(src, "list_tables"):
                table_src = src
                break
        if table_src is not None:
            try:
                tables = table_src.list_tables() or {}
            except Exception:
                tables = {}

        # source #1 — declared feature inventory (best-effort)
        entities, flows = _normalize_inventory(_load_feature_inventory(hubs))

        report.results.extend(check_state_entity_no_write(tables, endpoints))
        report.results.extend(check_flow_no_write(hubs, endpoints, flows))
        report.results.extend(check_entity_no_read(endpoints, entities))
    except Exception:
        # Defense in depth: a malformed hub must never crash the gate.
        return report
    return report


__all__ = [
    "CompletenessResult", "CompletenessReport", "compute_completeness",
    "check_state_entity_no_write", "check_flow_no_write", "check_entity_no_read",
    "state_entities_missing_write", "_is_state_column", "_state_entities",
]
