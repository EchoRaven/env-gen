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
  GENUINELY implies mutation (create/update/save/add/remove/rate/like/post/submit/
  track/record/set/toggle/play/resume/watch/progress/mark/start) AND which no
  write endpoint backs — where "backs" includes a write on the flow's own route, a
  write on a state entity the flow references, or (for a play/watch/resume flow) a
  progress state-write endpoint like Continue-Watching (#556). View-only/static
  flows (marketing/landing/splash/browse/…) carry no mutation verb and are never
  flagged. severity ``warn``. (Precision hardened in #559.)
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
# Word-part matched against a flow name (see ``_mutation_verb_of``): the token is
# the bare verb OR the verb + a real inflection suffix (``play`` -> ``player`` /
# ``playing``; ``mark`` -> ``marks`` / ``marking``) — NOT any arbitrary word that
# merely starts with the verb (``mark`` must NOT match ``marketing``; ``play``
# must NOT match ``playlist``).
_MUTATION_VERBS = frozenset({
    # playback / lifecycle (original)
    "play", "resume", "watch", "progress", "mark", "start",
    # explicit create/update/toggle vocabulary
    "create", "update", "save", "add", "remove", "rate", "like", "post",
    "submit", "track", "record", "set", "toggle",
})

# Inflection suffixes that keep a token a form of its verb. Includes agent/action
# noun forms (``play`` -> ``player``) so a "<verb>er" flow still reads as the
# action, while blocking coincidental longer words (``mark`` + ``eting`` is NOT a
# suffix, so ``marketing`` is not a mutation; ``play`` + ``list`` is not a suffix,
# so ``playlist`` is not a mutation).
_VERB_SUFFIXES = frozenset({"", "s", "es", "d", "ed", "ing", "er", "ers"})

# View-only / static flow tokens: a flow described ONLY by these implies NO
# mutation (a splash/marketing/landing/browse surface). Whole-token matched so
# ``review`` / ``overview`` never collide with ``view``. If a flow ALSO carries a
# genuine mutation verb it is still treated as a mutation flow (these never
# suppress a real write requirement).
_VIEW_ONLY_TOKENS = frozenset({
    "marketing", "landing", "splash", "welcome", "browse", "view", "explore",
    "discover", "home", "hero", "promo", "banner", "billboard", "gallery",
    "showcase", "carousel", "menu", "nav", "navigation", "preview",
})

# Playback/progress-class mutation verbs — their write is a per-row *progress*
# state update, which a media app records through a state-write endpoint on a
# progress-bearing table (e.g. a Continue-Watching ``POST``). A ``play``/``watch``
# flow is therefore SATISFIED when such a state-write endpoint exists (#556), even
# though its own name does not token-match that table's route.
_PLAYBACK_VERBS = frozenset({"play", "resume", "watch", "progress"})

# The mutable-state column tokens that denote playback/progress state (a subset of
# ``_STATE_TOKENS``). A state-write-backed table carrying one of these backs a
# playback flow's mutation.
_PLAYBACK_STATE_TOKENS = frozenset({
    "progress", "seconds", "secs", "elapsed", "remaining", "position", "offset",
    "timecode", "watched", "played", "viewed", "seen", "watchtime",
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


def _mutation_verb_of(token: str) -> Optional[str]:
    """Return the mutation verb a single word-part *is a form of*, else ``None``.

    A token matches a verb when it is the bare verb OR the verb followed by a real
    inflection suffix (``_VERB_SUFFIXES``): ``play``/``player``/``playing`` ->
    ``play``; ``mark``/``marks``/``marking`` -> ``mark``. A word that merely STARTS
    with a verb but whose remainder is not a suffix does NOT match — ``marketing``
    (``mark`` + ``eting``) and ``playlist`` (``play`` + ``list``) are not
    mutations. Descriptive/identity tokens (``poster`` etc.) and view-only tokens
    can never be a verb even if they inflection-match (``poster`` -> ``post``)."""
    if not token or token in _DESCRIPTIVE_TOKENS or token in _VIEW_ONLY_TOKENS:
        return None
    if token in _MUTATION_VERBS:
        return token
    for v in sorted(_MUTATION_VERBS):
        if len(v) >= 3 and token.startswith(v) and token[len(v):] in _VERB_SUFFIXES:
            return v
    return None


def _flow_mutation_verb(flow_name: str) -> Optional[str]:
    """Return the mutation verb a flow name genuinely implies, else ``None``.

    Rule 2 (non-mutation flows): a flow whose word-parts are ALL view-only/static
    (``landing_marketing``, ``browse_home``, ``splash``) implies no write and
    returns ``None``. Otherwise the first word-part that is a form of a mutation
    verb wins (``player`` -> ``play``, ``continue_watching`` -> ``watch``,
    ``create_order`` -> ``create``). A flow carrying BOTH a view-only token and a
    real mutation verb is still a mutation flow — view-only tokens never suppress a
    genuine write requirement."""
    parts = _split_ident(flow_name)
    if not parts:
        return None
    for p in parts:
        v = _mutation_verb_of(p)
        if v:
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


def state_entities_with_write(tables: Dict[str, Any],
                              endpoints: Dict[str, Any]) -> Dict[str, List[str]]:
    """The COMPLEMENT of ``state_entities_missing_write``: state-bearing entities
    that DO have a POST/PUT/PATCH endpoint — i.e. their mutation is satisfied by a
    real write (e.g. ``continue_watching`` once #556 projects its progress write).
    Returned as ``{entity: [state_column, ...]}``. Shares the SAME classifier and
    the SAME endpoint reconciliation as the error-side detection, so the two can
    never drift."""
    out: Dict[str, List[str]] = {}
    for entity, cols in _state_entities(tables).items():
        methods = _methods_touching(endpoints, _entity_tokens(entity))
        if methods & _WRITE_METHODS:
            out[entity] = cols
    return out


def _has_playback_state_write(state_write_backed: Dict[str, List[str]]) -> bool:
    """True iff some state-write-backed entity carries a playback/progress state
    column — the write that records a ``play``/``watch``/``resume`` mutation."""
    for cols in state_write_backed.values():
        for col in cols:
            if any(p in _PLAYBACK_STATE_TOKENS for p in _split_ident(col)):
                return True
    return False


def _flow_references_entity(flow_parts: List[str], entity: str) -> bool:
    """True iff the flow name contains the entity as a sub-phrase — every word-part
    of ``entity`` appears among ``flow_parts`` (``track_watch_progress`` references
    ``watch_progress``). Word-part matched so a partial word never collides."""
    ent_parts = _split_ident(entity)
    if not ent_parts:
        return False
    fset = set(flow_parts)
    return all(p in fset for p in ent_parts)


def check_flow_no_write(hubs, endpoints: Dict[str, Any],
                        flows: List[str],
                        tables: Optional[Dict[str, Any]] = None) -> List[CompletenessResult]:
    """A declared feature-inventory FLOW whose verb genuinely implies a mutation
    but which NO write (POST/PUT/PATCH) endpoint backs.

    A flow's mutation is considered SATISFIED (not flagged) when any of:
      * its subject tokens touch a write endpoint's route (``_methods_touching``);
      * its subject tokens reference a state entity that HAS a write endpoint
        (``state_entities_with_write`` — the #556 complement); or
      * it is a playback/progress-class flow (``play``/``watch``/``resume``) and
        the app has a state-write endpoint on a progress-bearing table (the
        Continue-Watching write that records playback progress).

    Non-mutation flows (view-only/static: marketing, landing, splash, browse …)
    carry no mutation verb and are never candidates. Only a flow whose verb truly
    implies a write, with NO backing write anywhere, is flagged — so a real gap
    still surfaces while already-satisfied / static flows do not."""
    out: List[CompletenessResult] = []
    tables = tables or {}
    state_write_backed = state_entities_with_write(tables, endpoints)
    playback_backed = _has_playback_state_write(state_write_backed)
    for flow in flows:
        verb = _flow_mutation_verb(flow)
        if not verb:
            continue  # rule 2: non-mutation / view-only flow implies no write
        tokens = _entity_tokens(flow)
        methods = _methods_touching(endpoints, tokens)
        if methods & _WRITE_METHODS:
            continue  # a write endpoint plausibly backs the flow
        flow_parts = _split_ident(flow)
        if any(_flow_references_entity(flow_parts, ent) for ent in state_write_backed):
            continue  # rule 1: flow references a state entity that HAS a write
        if verb in _PLAYBACK_VERBS and playback_backed:
            continue  # rule 1: playback mutation recorded via a progress write
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
            except Exception as _ep_exc:
                # #883: zero endpoints makes a COMPLETENESS audit vacuous — nothing registered
                # means nothing can be missing, so the audit passes by having failed. #792's shape
                # ("a gate that cannot load must not read as a gate that PASSED") in an audit file
                # #792 never reached.
                try:
                    from .deliverability import _gate_absent_792
                    _gate_absent_792("completeness_endpoints", _ep_exc, "read")
                except Exception:
                    pass
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
        report.results.extend(check_flow_no_write(hubs, endpoints, flows, tables))
        report.results.extend(check_entity_no_read(endpoints, entities))
    except Exception:
        # Defense in depth: a malformed hub must never crash the gate.
        return report
    return report


__all__ = [
    "CompletenessResult", "CompletenessReport", "compute_completeness",
    "check_state_entity_no_write", "check_flow_no_write", "check_entity_no_read",
    "state_entities_missing_write", "state_entities_with_write",
    "_is_state_column", "_state_entities", "_flow_mutation_verb",
]
