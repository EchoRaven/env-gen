"""Framework-owned by-construction route projector.

Root fix for the hollow-release class of bug (instagram MM, 2026-06-08): a backend
lane routinely DECLARES endpoints in RegistryHub but runs out of its loop budget before
writing the route code for all of them — then the milestone delivers anyway because
the delivery gate trusted RegistryHub *status* and api_smoke counted a 404 as "reachable".
The result: declared endpoints that 404 in the shipped app.

The fix mirrors ``database_scaffold`` (which projects DDL from the ORM rather than
trusting LLM-written SQL): the contract surface must be PROJECTED from the declared
contract, not left to lane thoroughness. For every business endpoint RegistryHub declares
that has no route in ``main.py``, this projects a working FastAPI handler from the
ORM models — list / get-by-id / get-by-field / search / create / update-me /
delete-by-id patterns, with a valid-shape fallback for anything unrecognised. So the
delivered app always answers every declared route (real where the lane coded it,
projected where it stopped short) — never 404.

Nested-resource awareness (instagram MM verification, 2026-06-09): a path like
``/api/users/{username}/posts`` is a *parent → child collection*, not a get-one. The
projector resolves the parent (``users`` via ``{username}``) and LISTS the child
(``posts``) scoped by the child's FK to the parent (``author_id``) — instead of the
old naive ``Post.id == username`` (a 500: ``operator does not exist: integer =
varchar``). Likewise create handlers inject the authenticated user into the owner FK
(``author_id``/``user_id``) and bind a path-param parent into the target FK
(``following_id`` for ``/users/{username}/follow``) — so a created row is actually
attributed (no more ``author_id = null``).

Deterministic, AST-based, idempotent: re-running adds nothing once every declared
endpoint has a route. Appended LAST so general ``/{id}`` patterns never shadow the
specific routes the lane wrote.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

_HTTP_METHODS = ("get", "post", "put", "delete", "patch")

# Columns that name the ACTOR/owner of a row — the authenticated caller. Order is
# preference (a row with both ``user_id`` and ``author_id`` is owned by the first).
_OWNER_FK_NAMES = (
    "user_id", "author_id", "owner_id", "creator_id", "created_by",
    "follower_id", "sender_id", "from_user_id", "actor_id", "uploaded_by",
    "posted_by", "account_id",
    # N-P0-2 (netflix): per-profile private data (ratings / my_list /
    # continue_watching) is owned by the caller's PROFILE, not their user row —
    # the create handler must fill it or the insert NOT-NULL-violates. Last in the
    # list so a user-level owner (user_id/account_id) still wins when both exist;
    # the VALUE is resolved to the caller's profile by _fw_owner_val (backend).
    "profile_id",
)
# Columns that name the TARGET/object of a relation — resolved from a path param.
_TARGET_FK_NAMES = (
    "following_id", "followee_id", "followed_id", "recipient_id", "to_user_id",
    "target_user_id", "addressee_id",
)
# Path params that reference a user even when no ``users`` segment precedes them.
_USER_PARAM_NAMES = ("username", "user_id", "userid", "user", "handle")


# SQLAlchemy type names that map to a Python ``int`` path param. A path param compared
# against one of these columns MUST be typed ``int`` so FastAPI coerces ``"123"→123``
# (and 422s non-numeric input) instead of handing a ``str`` to a postgres integer
# comparison → ``invalid input syntax for integer`` → HTTP 500 (the 500 that stalled
# validation, 2026-06-16). Everything else (String/Text/UUID/...) stays ``str``.
_INT_SA_TYPES = ("Integer", "BigInteger", "SmallInteger", "INTEGER", "BIGINT", "SMALLINT")


def _express_to_fastapi(path: str) -> str:
    """Normalise an Express-style ``:param`` path to FastAPI ``{param}``.

    A backend lane that wrote ``@app.get("/api/videos/:id")`` (Express idiom) makes
    ``:id`` a LITERAL segment in FastAPI — it matches only the literal URL and 404/405s
    real ids (fails ``business_endpoints_implemented``). Both DECLARED endpoint paths
    and the path we stamp into the decorator go through this so a ``:id`` always becomes
    a real ``{id}`` path param (2026-06-16). Idempotent on already-``{}`` paths."""
    return re.sub(r":([A-Za-z_][A-Za-z0-9_]*)", r"{\1}", path or "")


def _py_type_for_sa(sa_type: Optional[str]) -> str:
    """SQLAlchemy type name → FastAPI path-param annotation (``int`` for integer
    columns, else ``str``). Unknown/absent → ``str`` (the safe default; a str param
    never causes the int-coercion 500)."""
    return "int" if sa_type in _INT_SA_TYPES else "str"


def _norm_path(path: str) -> str:
    """Collapse path params to a single placeholder so ``/x/{id}`` == ``/x/{pid}``."""
    return re.sub(r"\{[^}]+\}", "{}", path or "")


# ---------------------------------------------------------------------------
# Introspection: existing routes (main.py AST) + ORM models (models.py AST)
# ---------------------------------------------------------------------------
def _existing_routes(src: str) -> set:
    """Return the set of ``(METHOD, normalised_path)`` already decorated in *src*."""
    routes: set = set()
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return routes
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call):
                continue
            func = dec.func
            # @app.get("/x") / @router.post("/x")
            if not isinstance(func, ast.Attribute) or func.attr not in _HTTP_METHODS:
                continue
            if not dec.args:
                continue
            arg0 = dec.args[0]
            if isinstance(arg0, ast.Constant) and isinstance(arg0.value, str):
                # Normalise an Express-style ``:id`` the lane wrote so a declared
                # ``:id``/``{id}`` endpoint is recognised as already-routed and not
                # re-projected into a duplicate handler for the same method+path.
                routes.add((func.attr.upper(), _norm_path(_express_to_fastapi(arg0.value))))
    return routes


def _duplicate_routes(src: str) -> set:
    """``(METHOD, normalised_path)`` pairs decorated MORE THAN ONCE in *src* — an
    intra-module route collision. FastAPI mounts the FIRST matching definition and
    silently shadows the rest, so a BROKEN first handler ships while its correct twin
    is dead code — yet ``_existing_routes`` collapses both into one set entry, so the
    code-truth audit flips the endpoint ``implemented`` on decorator-presence alone,
    blind to which handler actually serves (audit #6, run v12: custom_routes.py defined
    the same route twice; the first 500'd, the audit went green). Returns the collided
    keys so the audit can refuse to credit them."""
    from collections import Counter
    counts: Counter = Counter()
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call):
                continue
            func = dec.func
            if not isinstance(func, ast.Attribute) or func.attr not in _HTTP_METHODS:
                continue
            if not dec.args:
                continue
            arg0 = dec.args[0]
            if isinstance(arg0, ast.Constant) and isinstance(arg0.value, str):
                counts[(func.attr.upper(), _norm_path(_express_to_fastapi(arg0.value)))] += 1
    return {k for k, n in counts.items() if n >= 2}


def _column_sa_type(call: ast.Call) -> Optional[str]:
    """The SQLAlchemy type name of a ``Column(<Type>, ...)`` declaration, e.g.
    ``Column(Integer, primary_key=True)`` → ``"Integer"`` and ``Column(String(255))``
    → ``"String"``. Returns None when the first positional arg is not a type
    reference (e.g. ``Column(ForeignKey(...))`` with the type inferred). Used to type
    a path param to its target column so an int PK lookup coerces ``"123"→123``
    (a 422 on bad input, never the postgres ``invalid input syntax for integer`` 500)."""
    if not call.args:
        return None
    first = call.args[0]
    # Column(Integer, ...) — a bare type name
    if isinstance(first, ast.Name):
        return first.id
    # Column(String(255), ...) / Column(Numeric(10, 2), ...) — a parametrised type
    if isinstance(first, ast.Call):
        fn = first.func
        return getattr(fn, "id", None) or getattr(fn, "attr", None)
    # Column(sa.Integer, ...) — attribute access
    if isinstance(first, ast.Attribute):
        return first.attr
    return None


def _orm_models(backend_dir: Path) -> Dict[str, Dict[str, Any]]:
    """Parse models.py → ``{tablename: {"cls", "cols": [...], "fks": {col: table},
    "types": {col: "Integer"|...}}}``.

    ``fks`` captures ``Column(..., ForeignKey("users.id"))`` targets when present;
    handler projection also falls back to column-name heuristics so models that omit
    explicit ``ForeignKey`` (common in LLM-written ORMs) still wire correctly.
    ``types`` captures each column's SQLAlchemy type name so the projector can type a
    path param to the column it is compared against (int PK/FK → ``int`` path param)."""
    models: Dict[str, Dict[str, Any]] = {}
    models_py = backend_dir / "models.py"
    if not models_py.exists():
        return models
    try:
        tree = ast.parse(models_py.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return models
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        tablename: Optional[str] = None
        cols: List[str] = []
        fks: Dict[str, str] = {}
        types: Dict[str, str] = {}
        required: List[str] = []
        for stmt in node.body:
            # __tablename__ = "users"
            if isinstance(stmt, ast.Assign):
                target = stmt.targets[0] if stmt.targets else None
                name = getattr(target, "id", None)
                if name == "__tablename__" and isinstance(stmt.value, ast.Constant):
                    tablename = str(stmt.value.value)
                elif name and isinstance(stmt.value, ast.Call):
                    # col = Column(...)  → a mapped column
                    callee = stmt.value.func
                    if getattr(callee, "id", None) == "Column" or getattr(callee, "attr", None) == "Column":
                        cols.append(name)
                        sa_type = _column_sa_type(stmt.value)
                        if sa_type:
                            types[name] = sa_type
                        for a in stmt.value.args:  # scan for ForeignKey("table.col")
                            if not isinstance(a, ast.Call):
                                continue
                            fc = a.func
                            if (getattr(fc, "id", None) == "ForeignKey" or getattr(fc, "attr", None) == "ForeignKey") \
                                    and a.args and isinstance(a.args[0], ast.Constant):
                                fks[name] = str(a.args[0].value).split(".")[0]
                        # #566n: a column the create body MUST supply = NOT-NULL, not the PK,
                        # and no default/server_default. Lets the request-schema heal add exactly
                        # the required fields (e.g. rating.value) without over-sending optional or
                        # server-defaulted columns.
                        _kw = {k.arg: k.value for k in stmt.value.keywords if k.arg}
                        def _is_true(_v):
                            return isinstance(_v, ast.Constant) and _v.value is True
                        def _is_false(_v):
                            return isinstance(_v, ast.Constant) and _v.value is False
                        _is_pk = _is_true(_kw.get("primary_key"))
                        _notnull = _is_false(_kw.get("nullable"))
                        _has_default = ("default" in _kw) or ("server_default" in _kw)
                        if _notnull and not _is_pk and not _has_default:
                            required.append(name)
        if tablename:
            models[tablename] = {"cls": node.name, "cols": cols, "fks": fks,
                                 "types": types, "required": required}
    return models


# ---------------------------------------------------------------------------
# Path / resource analysis
# ---------------------------------------------------------------------------
def _segments(path: str) -> List[Tuple[str, bool]]:
    """``/api/users/{username}/posts`` → ``[("users",F),("username",T),("posts",F)]``
    (the leading ``api`` segment is dropped). Bool = is a path param."""
    out: List[Tuple[str, bool]] = []
    for seg in (path or "").split("/"):
        if not seg or seg == "api":
            continue
        if seg.startswith("{") and seg.endswith("}"):
            out.append((seg[1:-1], True))
        else:
            out.append((seg, False))
    return out


def _path_params(path: str) -> List[str]:
    return [s for s, is_p in _segments(path) if is_p]


def _sanitize_path_params(path: str) -> str:
    """Fix #57 (outlook run-43, live): a registered path can carry an EMPTY or
    non-identifier brace param — the verifier registered ``DELETE
    /api/messages/{}`` — and projected VERBATIM it emits ``def h(: str, ...)``
    → SyntaxError → the backend CRASH-LOOPS and every validation cycle dies on
    backend_port (never a published port). Rewrite each invalid ``{...}`` to a
    deterministic positional ``{param_N}``: the handler is valid Python and the
    served route still matches the same URL shapes. Registration now also
    REJECTS such paths (registryhub); this is the defense for garbage already
    in a hub store."""
    segs = (path or "").split("/")
    out = []
    for n, seg in enumerate(segs, 1):
        if seg.startswith("{") and seg.endswith("}"):
            name = seg[1:-1]
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
                seg = "{param_%d}" % n
        out.append(seg)
    return "/".join(out)


def _ends_in_param(path: str) -> bool:
    segs = _segments(path)
    return bool(segs) and segs[-1][1]


def _param_type_by_name(param: str) -> str:
    """Name-only fallback when the schema can't resolve a param's column (e.g. a
    raw-SQL app with no models.py): ``id``/``*_id``/``*id``/``*Id`` look like int PKs."""
    return "int" if _is_id_param(param) else "str"


def _param_column_type(param: str, path: str, models: Dict[str, Dict[str, Any]]) -> str:
    """Type a path param to the COLUMN it is compared against, so an int PK/FK lookup
    coerces ``"123"→123`` (FastAPI returns 422 on non-numeric, never the postgres
    integer-coercion 500). By-construction from the schema — never hardcodes names:

    * a terminal param (``/videos/{id}``) → its resource model's matched column (PK
      ``id`` for ``*id``/``id``, else the matched text column username/slug/...);
    * a nested parent param (``/channels/{channelId}/videos``) → the PARENT model's
      matched column (``Channel.id`` here → ``int``).

    Falls back to the name heuristic when no model resolves (raw-SQL apps)."""
    segs = _segments(path)
    # Locate the param's position to find the model it qualifies.
    for i, (seg, is_p) in enumerate(segs):
        if not is_p or seg != param:
            continue
        prev = segs[i - 1][0] if i > 0 and not segs[i - 1][1] else None
        target_meta: Optional[Dict[str, Any]] = None
        if prev:
            pm = _match_model(prev, models)
            if pm:
                target_meta = pm[1]
        if target_meta is None and i == len(segs) - 1:
            # terminal param with no immediately-preceding model segment: fall back to
            # the resource model the whole path operates on (e.g. /api/{id} edge cases).
            rm = _resource_model(path, models)
            if rm:
                target_meta = rm[1]
        if target_meta is not None:
            field = _lookup_field(param, target_meta)
            cols = target_meta.get("cols", [])
            param_is_id = _is_id_param(param)
            # ``_lookup_field`` DEFAULTS to "id" when nothing matches. A non-id-named
            # param (``{username}``) whose name matched NO real column fell back to
            # "id" — but it is NOT the resource's own id, it's a foreign natural key
            # (e.g. ``POST /api/messages/{username}`` → look the recipient user up by
            # username). It must stay ``str`` so FastAPI doesn't int-coerce it
            # (``/api/messages/alice`` → 422) and the handler's by-name lookup works.
            # The old ``or "id" in cols`` clause wrongly typed ``{username}`` as int
            # whenever the matched table merely HAD an id column (messages does):
            # instagram run #3 typed it int, the probe sent ``1``, the handler ran and
            # 500'd on the insert. Gate on the PARAM name only, never the table's id.
            if field == "id" and not param_is_id:
                return "str"
            sa_type = (target_meta.get("types") or {}).get(field)
            if sa_type is not None:
                return _py_type_for_sa(sa_type)
            # Column resolved but no captured type (e.g. an inferred-type FK column):
            # ``id``/``*_id`` columns are integer PKs/FKs by overwhelming convention.
            if field == "id" or field.endswith("_id"):
                return "int"
            return "str"
        break
    return _param_type_by_name(param)


def _match_model(seg: str, models: Dict[str, Dict[str, Any]]) -> Optional[Tuple[str, Dict[str, Any]]]:
    # N-P0-2 (Netflix): a kebab-case route segment (/api/my-list, /api/for-you) names a
    # snake_case table (my_list / for_you). Only +s/-s and y->ies were normalized, so a
    # hyphenated segment matched NOTHING → empty-stub projection. A '-' segment matched
    # nothing before, so folding it to '_' can only add a correct match (never steal one).
    cand = seg.lower().replace("-", "_")
    # FIX #202 (r11 live): the y→ies irregular plural — a segment 'activity'
    # must match table 'activities' (also category/categories, story/stories,
    # company/companies). Only the regular +s/-s was handled, so an '-y' resource
    # GET shipped an empty stub → #173 wall. Derive the -ies form of an -y segment.
    _ies = (cand[:-1] + "ies") if cand.endswith("y") and len(cand) > 2 else None
    for table, meta in models.items():
        if (cand == table or cand + "s" == table or cand == table.rstrip("s")
                or cand.rstrip("s") == table.rstrip("s")
                or (_ies is not None and _ies == table)):
            return (table, meta)
    return None


# Path tokens that name a FEED/TIMELINE of the app's primary content rather than
# a table. Without this, /api/feed and /api/explore resolved to NO model and the
# projector emitted a hardcoded empty list — every feed screen showed "no items"
# forever (2026-06-10, seeded posts invisible). Resolution is DOMAIN-AGNOSTIC (see
# _primary_content_model): the social `posts` table when present, else the most
# feed-shaped business table — so news/activity/task feeds work too, not only the
# Instagram surface.
_FEED_SHAPED_TOKENS = ("feed", "explore", "timeline", "reels", "discover", "stream")

# Identity / auth / tenant control-plane tables a content feed never lists.
_SPINE_TABLE_STEMS = ("user", "tenant", "role", "permission", "session", "migration", "setting")
# Columns that make a row time-ordered (a feed is chronological).
_FEED_TS_COLS = ("created_at", "created", "timestamp", "posted_at", "published_at", "inserted_at")


def _is_spine_table(table: str) -> bool:
    n = table.lower().rstrip("s")
    return (
        n in _SPINE_TABLE_STEMS
        or n.startswith("oauth")
        or n.startswith("auth")
        or "token" in n
        or "credential" in n
    )


def _has_timestamp(cols: List[str]) -> bool:
    return any(c in _FEED_TS_COLS or c.endswith("_at") for c in cols)


def _primary_content_model(
    models: Dict[str, Dict[str, Any]]
) -> Optional[Tuple[str, Dict[str, Any]]]:
    """The business table a domain-agnostic feed/timeline lists, picked BY SHAPE
    (not a hardcoded name): a non-spine table that looks like a feed item — a
    timestamp column (time-ordered) and, preferably, an owner FK to users
    (authored). Among candidates, prefer feed-item shape, then the richest table,
    then alphabetical (deterministic). Returns None when nothing is feed-shaped,
    so the projector never guesses a wrong table."""
    candidates: List[Tuple[int, int, str, Dict[str, Any]]] = []
    for table, meta in models.items():
        if _is_spine_table(table):
            continue
        cols = meta.get("cols", [])
        if not _has_timestamp(cols):
            continue  # a feed is chronological; no timestamp → not a feed source
        rank = 2 if _owner_fk(meta) else 1  # authored content ranks above un-owned
        candidates.append((rank, len(cols), table, meta))
    if not candidates:
        return None
    candidates.sort(key=lambda c: (-c[0], -c[1], c[2]))
    _, _, table, meta = candidates[0]
    return (table, meta)


def _search_target_model(
    models: Dict[str, Dict[str, Any]]
) -> Optional[Tuple[str, Dict[str, Any]]]:
    """The table a RESOURCE-LESS global search (``GET /api/search``) targets: the richest
    non-spine business table (most columns; alphabetical tiebreak, deterministic). Unlike
    _primary_content_model this does NOT require a timestamp — a catalog like Netflix
    ``titles`` has none, so without this a bare ``/api/search`` fell to an empty
    ``{"items":[],"total":0}`` stub → deliverability_placeholder_stub_handler hard-blocks
    delivery (Gen-1). Returns None only when there is no business table at all."""
    cands = [(len(m.get("cols", [])), t, m)
             for t, m in models.items() if not _is_spine_table(t)]
    if not cands:
        return None
    cands.sort(key=lambda c: (-c[0], c[1]))
    _, table, meta = cands[0]
    return (table, meta)


def _resource_model(path: str, models: Dict[str, Dict[str, Any]]) -> Optional[Tuple[str, Dict[str, Any]]]:
    """Pick the ORM model a path operates on: the LAST path segment that matches a
    known table (plural or singular). ``/api/users/{u}/posts`` → posts(Post).
    A feed/timeline path that names no table resolves to the app's primary content
    table — shape-derived (timestamp + owner FK + richness), domain-agnostic."""
    chosen: Optional[Tuple[str, Dict[str, Any]]] = None
    _segs = _segments(path)
    for seg, is_p in _segs:
        if is_p:
            continue
        m = _match_model(seg, models)
        if m:
            chosen = m
    # FIX #198 (r8 live): an ACTION path `/api/<parent>/{param}/<verb>` whose
    # trailing verb names no model of its own (POST .../{id}/like) resolves to
    # the PARENT here → FIX #124 then 404s it. But the lane commonly models the
    # relation as a PARENT-PREFIXED join (`video_likes`), and #196 provisions a
    # bare `likes` — neither of which _match_model('like') finds. When the verb
    # tail is unmatched AND sits after a `<resource>/{param}`, try the join
    # names `<parent_singular>_<verb>[s]` so a correctly-modeled interaction
    # actually gets its insert handler instead of a 404.
    _non_param = [(s, i) for i, (s, is_p) in enumerate(_segs) if not is_p and s != "api"]
    if len(_segs) >= 3 and _non_param:
        _last_s = _non_param[-1][0]
        _last_i = _non_param[-1][1]
        _verb_unmatched = _match_model(_last_s, models) is None
        _prev_is_param = _last_i >= 1 and _segs[_last_i - 1][1]
        if _verb_unmatched and _prev_is_param and len(_non_param) >= 2:
            _parent_seg = _non_param[-2][0]
            _parent_sing = _parent_seg.rstrip("s") or _parent_seg
            for _cand in (f"{_parent_sing}_{_last_s}", f"{_parent_sing}_{_last_s}s"):
                _jm = _match_model(_cand, models)
                if _jm:
                    return _jm
    # FIX #200 (r10 live): a GET path whose segments don't LITERALLY equal a table
    # name projected an empty-collection STUB → #173 HARD-blocked it, and — being a
    # FRAMEWORK handler in main.py — the lane couldn't fix it → guaranteed wall.
    # Two deterministic rungs, tried only when nothing matched exactly (so no
    # existing resolution changes):
    if chosen is None and _non_param:
        _res_segs = [s for s, _ in _non_param]
        # (1) MULTI-SEGMENT JOIN: adjacent non-param segments joined with '_' name a
        #     table the path split across a hierarchy (/api/live/streams → live_streams).
        for _i in range(len(_res_segs) - 1):
            _joined = f"{_res_segs[_i]}_{_res_segs[_i + 1]}"
            _jm = _match_model(_joined, models)
            if _jm:
                chosen = _jm
                break
        # (2) SUFFIX MATCH: the resource segment names the CORE of a qualified table
        #     (/api/messages → direct_messages). Fallback-only, and length-guarded
        #     (≥3 chars) so a tiny segment can't spuriously suffix-hit a big table.
        if chosen is None:
            for _seg in reversed(_res_segs):
                _sl = _seg.lower()
                if len(_sl.rstrip("s")) < 3:
                    continue
                _cands = [t for t in models
                          if t.lower().endswith("_" + _sl)
                          or t.lower().endswith("_" + _sl.rstrip("s"))
                          or t.lower().endswith("_" + _sl.rstrip("s") + "s")]
                if len(_cands) == 1:  # unambiguous only
                    chosen = (_cands[0], models[_cands[0]])
                    break
        # (3) PREFIX MATCH (#205, r13 live): a shorthand segment names the CORE of
        #     a `<segment>_<...>` compound table (/api/live → live_streams). The '_'
        #     boundary + UNIQUENESS guard keep it from spuriously hitting a substring
        #     (cat↛category) or an ambiguous pair (two live_* tables).
        if chosen is None:
            for _seg in reversed(_res_segs):
                _sl = _seg.lower()
                if len(_sl.rstrip("s")) < 3:
                    continue
                _pre = _sl.rstrip("s")
                _cands = [t for t in models if t.lower().startswith(_pre + "_")]
                if len(_cands) == 1:
                    chosen = (_cands[0], models[_cands[0]])
                    break
    if chosen is None:
        segs = {seg for seg, is_p in _segments(path) if not is_p}
        if segs & set(_FEED_SHAPED_TOKENS):
            # No hardcoded "posts" preference — derive the primary content model
            # from shape so a feed-shaped path in a non-social app maps correctly.
            chosen = _primary_content_model(models)
    return chosen


def _is_id_param(param: str) -> bool:
    """An id-referencing path param — case-insensitively, so camelCase ``channelId`` /
    ``videoId`` (the common Express/JS idiom) resolve to the ``id`` column just like
    snake_case ``channel_id``. Without this, ``channelId`` slipped through to a slug/
    username match (or the default), producing a wrong-column comparison."""
    p = param.lower()
    return p == "id" or p.endswith("id") or p.endswith("_id")


# #270: text-ish columns a by-NAME path param may legitimately match, most specific first.
_NAMED_LOOKUP_COLS = ("username", "handle", "slug", "name", "title", "code", "key", "email")



# #271: resolve whether a projected endpoint needs auth, treating an UNSTATED contract
# (missing OR None) as "decide by shape", never as "public".
_WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
# Path fragments that make a GET personal to the caller — a read of these is per-user and
# cannot be anonymous. Kept generic (no app vocabulary): "me", the personalised feeds, and
# the notification/inbox family.
# #279: following/friends are personalised (a specific user's graph → auth). The FOR-YOU /
# FYP feed is NOT — it is the app's public recommended stream, served logged-out in real
# apps (TikTok's FYP is browsable anonymously; the login wall is only on interaction).
# Marking it self-read (#271) required auth on it, which failed the anonymous ui_flow walk
# on a working app (r62). An explicit auth_required in the contract still wins.
_SELF_READ_MARKERS = ("/me", "/me/", "feed/following", "feed/friends",
                      "notification", "inbox", "/mine")
# The auth CONTROL surface mints tokens, so it must stay anonymous even for writes.
_AUTH_CONTROL_PREFIXES = ("/auth/", "/api/auth/", "/oauth", "/api/oauth", "/.well-known")


def resolve_endpoint_auth(method, path, ep, meta=None):
    """True if this endpoint must project with Depends(get_current_user).

    r58 (live): every unauthored endpoint carried auth_required=None, and
    ``bool(ep.get("auth_required", True))`` returned False for a PRESENT-but-None key
    (the default only applies when the key is ABSENT), so /api/me, /api/feed/following and
    the video write routes all projected WIDE OPEN and 200'd anonymously. Fixed two ways:
    None means "unstated" (explicit is-None check, not .get-with-default), and an unstated
    endpoint defaults to auth ONLY when its shape needs it — a write, or a self/personalised
    read — so public reads (a feed, an explore grid) stay open. An explicit True/False in
    the contract or metadata always wins.
    """
    stated = ep.get("auth_required")
    if stated is None and isinstance(meta, Mapping):
        stated = meta.get("auth_required")
    if stated is not None:
        return bool(stated)
    p = str(path or "").lower()
    if any(p.startswith(pre) for pre in _AUTH_CONTROL_PREFIXES):
        return False                              # token-minting surface stays anonymous
    if str(method or "").upper() in _WRITE_METHODS:
        return True                               # a mutation needs an actor
    return any(mark in p for mark in _SELF_READ_MARKERS)   # personalised read needs one


def _lookup_field(param: str, parent_meta: Dict[str, Any]) -> str:
    """Which parent column a path param matches: id for ``*id``, else a NAMED column.

    #270 (r58, live): ``/api/users/{username}/follow`` projected to
    ``db.query(User).filter(getattr(User, "id") == username)``. That run's ``User`` has no
    ``username`` column — it is id / email / name / password_hash / tenant_id / created_at,
    the username lives on another model — so every rung of the old ladder missed and the
    final ``return "id"`` compared an Integer primary key to "avachen". That is an
    unconditional Postgres type error: three routes 500 on every request, no lane can fix
    it, and it reads as a backend bug rather than a projection bug.

    The fallback was the defect. For an id-LIKE param the PK is right. For a param named
    after something else, the PK is a guaranteed 500, so prefer any TEXT-ish identifying
    column the parent actually has: a text-to-text comparison cannot raise, and a miss
    becomes an honest 404. Only an id-like param (or a model with nothing else) still
    reaches ``id``.
    """
    cols = parent_meta.get("cols", [])
    if _is_id_param(param):
        return "id"
    if param in cols:
        return param
    if "username" in cols and ("user" in param or param == "username" or param == "handle"):
        return "username"
    if "slug" in cols:
        return "slug"
    # #270: a name-shaped param must not claim the PK. Prefer a column whose name relates
    # to the param, then any text-ish identifier the model carries.
    for col in _NAMED_LOOKUP_COLS:
        if col in cols and (col in param or param in col):
            return col
    for col in _NAMED_LOOKUP_COLS:
        if col in cols:
            return col
    return "id"


def _parent_context(
    path: str, models: Dict[str, Dict[str, Any]], child_table: str
) -> Optional[Tuple[str, Dict[str, Any], str]]:
    """For a nested path, find ``(parent_table, parent_meta, parent_param)``: a path
    param whose preceding segment names a DIFFERENT model (``users/{username}`` →
    User), or a user-referencing param even without a ``users`` segment."""
    segs = _segments(path)
    for i, (seg, is_p) in enumerate(segs):
        if not is_p:
            continue
        param = seg
        prev = segs[i - 1][0] if i > 0 and not segs[i - 1][1] else None
        if prev:
            pm = _match_model(prev, models)
            if pm and pm[0] != child_table:
                return (pm[0], pm[1], param)
        if param.lower() in _USER_PARAM_NAMES and "users" in models and child_table != "users":
            return ("users", models["users"], param)
    return None


def _owner_fk(child_meta: Dict[str, Any], exclude: Tuple[str, ...] = ()) -> Optional[str]:
    """The child column that holds the ACTOR (authenticated user): a known owner
    name, else a parsed FK to ``users``."""
    cols = child_meta.get("cols", [])
    fks = child_meta.get("fks", {})
    for name in _OWNER_FK_NAMES:
        if name in cols and name not in exclude:
            return name
    for col, tgt in fks.items():
        if tgt == "users" and col not in exclude:
            return col
    return None


def _scope_fk(child_meta: Dict[str, Any], parent_table: str, parent_singular: str) -> Optional[str]:
    """The child column linking it to a parent — used to LIST/scope by the parent."""
    cols = child_meta.get("cols", [])
    fks = child_meta.get("fks", {})
    sing = parent_singular + "_id"
    if sing in cols:
        return sing
    for col, tgt in fks.items():
        if tgt == parent_table:
            return col
    if parent_table == "users":
        return _owner_fk(child_meta)
    return None


def _assoc_table(
    models: Dict[str, Dict[str, Any]], parent_table: Optional[str], child_table: Optional[str]
) -> Optional[Tuple[str, str, str]]:
    """For a MANY-TO-MANY nested collection whose child has no direct parent FK
    (``_scope_fk`` → None), find the association table linking parent↔child and return
    ``(assoc_cls, parent_link_col, child_link_col)``. Generalizable: ANY third table
    whose FKs point to BOTH the parent and the child qualifies — e.g. ``title_genres``
    (``genre_id``→genres, ``title_id``→titles) for ``/genres/{id}/titles``. Returns None
    when nothing links them (the caller then best-effort lists, still 404-ing a missing
    parent). No product literals: keyed purely off the contract's FK graph."""
    if not parent_table or not child_table:
        return None
    for _t, _m in (models or {}).items():
        if _t in (parent_table, child_table):
            continue
        fks = _m.get("fks", {}) or {}
        p_col = next((c for c, tgt in fks.items() if tgt == parent_table), None)
        c_col = next((c for c, tgt in fks.items() if tgt == child_table), None)
        if p_col and c_col:
            return (_m["cls"], p_col, c_col)
    return None


def _target_fk(child_meta: Dict[str, Any], parent_table: str, parent_singular: str) -> Optional[str]:
    """The child column naming the TARGET of a relation (the path-param parent) —
    e.g. ``following_id`` for ``Follow`` under ``/users/{username}/follow``."""
    cols = child_meta.get("cols", [])
    fks = child_meta.get("fks", {})
    if parent_table == "users":
        for name in _TARGET_FK_NAMES:
            if name in cols:
                return name
    sing = parent_singular + "_id"
    if sing in cols:
        return sing
    for col, tgt in fks.items():
        if tgt == parent_table:
            return col
    return None


# ---------------------------------------------------------------------------
# Handler generation
# ---------------------------------------------------------------------------

# Imports/helpers the projected handlers rely on — injected idempotently + GUARDED
# so a raw-SQL app with no models.py does not crash on load. Shared by BOTH
# ``project_missing_routes`` and ``project_state_write_endpoints`` (#556) so a
# state-write handler projected on its own (project_missing_routes may project
# nothing) is still self-sufficient. FastAPI/HTTP names re-import harmlessly;
# ``from models import *`` is best-effort; the ``_fw_*`` re-defs are idempotent and
# never clobber the skeleton header's richer canonical versions (see inline notes).
_PROJECTOR_GUARD = (
    "# by-construction projector deps (guarded; safe to re-import)\n"
    "from fastapi import Depends, HTTPException, Query  # noqa: F401,F811\n"
    "from sqlalchemy.exc import IntegrityError, DataError  # noqa: F401,F811\n"
    "def _fw_uid(user):  # noqa: F811 — idempotent re-definition is harmless\n"
    "    _v = getattr(user, 'id', None)\n"
    "    if _v is None and isinstance(user, dict):\n"
    "        _v = user.get('id') or user.get('sub')\n"
    "    if _v is None:\n"
    "        _v = user\n"
    "    try:\n"
    "        return int(_v)\n"
    "    except (TypeError, ValueError):\n"
    "        return _v\n"
    "try:\n"
    "    _fw_owner_val  # noqa: F821 — canonical (rich) header version wins if present\n"
    "except NameError:\n"
    "    def _fw_owner_val(cls, col, user):\n"
    "        _v = _fw_uid(user)\n"
    "        try:\n"
    "            _pt = getattr(cls, col).type.python_type\n"
    "        except Exception:\n"
    "            return _v\n"
    "        try:\n"
    "            if _pt is str and not isinstance(_v, str):\n"
    "                return str(_v)\n"
    "            if _pt is int and not isinstance(_v, int):\n"
    "                return int(_v)\n"
    "        except (TypeError, ValueError):\n"
    "            pass\n"
    "        return _v\n"
    # #556: a state-write upsert handler projected into a lane-authored main.py that
    # never ran generate_backend_skeleton would NameError on _coerce_body. Define a
    # minimal fallback ONLY when the header's rich version is absent (the try binds the
    # name → the fallback is skipped when the skeleton defined it). Best-effort coerce.
    "try:\n"
    "    _coerce_body  # noqa: F821 — canonical (rich) header version wins if present\n"
    "except NameError:\n"
    "    def _coerce_body(cls, valid):\n"
    "        return valid\n"
    "try:\n"
    "    from models import *  # noqa: F401,F403\n"
    "except Exception:\n"
    "    pass\n"
    "try:\n"
    "    from auth_dependency import get_current_user  # noqa: F401,F811\n"
    "except Exception:\n"
    "    pass\n"
    "try:\n"
    "    from database import get_db  # noqa: F401,F811\n"
    "except Exception:\n"
    "    pass\n"
)


def _serialize_expr(var: str, cols: List[str]) -> str:
    """Build a dict literal serialising an ORM instance's columns (ISO datetimes)."""
    if not cols:
        return f'{{"id": getattr({var}, "id", None)}}'
    parts = []
    for c in cols:
        if c.endswith("_at"):
            # FIX #214 (r16: GET /api/messages 500): a ``*_at`` value is not always a
            # datetime — a TEXT column or a pre-serialized string arrives as ``str``,
            # and ``str.isoformat()`` raises AttributeError → the projected read 500s →
            # business_chain/ui_flow can never pass → delivery churns. Only call
            # ``.isoformat()`` when the value actually has it; otherwise pass it through
            # (a string stays a string, ``None`` stays ``None``).
            parts.append(
                f'"{c}": ({var}.{c}.isoformat() '
                f'if hasattr(getattr({var}, "{c}", None), "isoformat") '
                f'else getattr({var}, "{c}", None))')
        elif c == "password_hash":
            continue  # never serialise secrets
        else:
            parts.append(f'"{c}": getattr({var}, "{c}", None)')
    return "{" + ", ".join(parts) + "}"


def _sig_for_params(params: List[str], path: str, models: Dict[str, Dict[str, Any]]) -> str:
    """Path-param signature fragment, each param typed to the COLUMN it is compared
    against (int PK/FK → ``int``) so non-coercible input 422s instead of 500-ing."""
    return "".join(f"{p}: {_param_column_type(p, path, models)}, " for p in params)


def _me_user_model(models: Dict[str, Dict[str, Any]]):
    """The model backing a ``/me`` current-user endpoint — the users table.

    A GET path ending in ``/me`` is ALWAYS the authenticated caller's own record,
    so it resolves to the users model regardless of the path's resource segment
    (``/api/auth/me`` → "auth" has no table, but the row is still a user). Returns
    ``(class_name, cols)`` or ``None``. Prefers a conventionally-named users table,
    else any model carrying an ``email``/``username`` column (user-like)."""
    for name in ("users", "user", "accounts", "account"):
        m = models.get(name)
        if isinstance(m, dict) and m.get("cls"):
            return m["cls"], (m.get("cols") or [])
    for _m in models.values():
        if not isinstance(_m, dict) or not _m.get("cls"):
            continue
        cols = _m.get("cols") or []
        if "email" in cols or "username" in cols:
            return _m["cls"], cols
    return None


def _generate_handler(method: str, path: str, auth: bool, models: Dict[str, Dict[str, Any]], idx: int, response_key: str = "", owner_scoped_reads: bool = False, owner_scoped_tables: Optional[Iterable[str]] = None) -> str:
    """Project a FastAPI handler. Functional for recognised CRUD + nested-resource
    patterns over a resolvable model; valid-shape stub otherwise. Never 404s.

    ``owner_scoped_reads``: OPT-IN per-resource signal (default off). When set AND
    the model has an owner FK AND the route is authenticated, the by-id GET, flat
    collection GET, and search are scoped to ``owner_fk == _fw_uid(user)`` — mirroring
    the PUT/DELETE write authz. This is how a per-user-PRIVATE resource (notes,
    email, calendar, drafts) gets correct read isolation BY CONSTRUCTION, instead
    of a remediation loop the lane can't win (projected wins for CRUD, fd56c2e).
    Default off keeps the reference public-feed behaviour (anyone GETs any row)."""
    path = _sanitize_path_params(path)   # #57: never emit invalid Python for a bad brace param
    fn = "_projected_" + re.sub(r"[^a-zA-Z0-9]+", "_", f"{method}_{path}").strip("_").lower() + f"_{idx}"
    res = _resource_model(path, models)
    # A bare GET search path (``/api/search``) names no resource → res is None → it fell
    # to an empty ``{"items":[],"total":0}`` stub, a HARD delivery blocker
    # (deliverability_placeholder_stub_handler, Gen-1). Resolve it to the content table so
    # the real search handler below fires over that table's text columns. ``/api/<res>/
    # search`` already resolves <res>, so this only rescues the resource-less search.
    if res is None and method.upper() == "GET" and "search" in path.lower():
        res = _primary_content_model(models) or _search_target_model(models)
    # No type annotations on the dependency params: a ``: User`` / ``: Session``
    # annotation REFERENCES those names at import time, so if the lane wrote a raw-SQL
    # app (no ``from models import User``) the projected handler crashes the whole app
    # with ``NameError: name 'User' is not defined`` (instagram MM run #13 — the app
    # would not even start). FastAPI resolves the dependency from the ``Depends(...)``
    # default, not the annotation, so dropping them is behaviour-preserving + safe.
    deps = "db=Depends(get_db)"
    if auth:
        deps += ", user=Depends(get_current_user)"

    params = _path_params(path)
    last_param = params[-1] if params else None
    sig_params = _sig_for_params(params, path, models)

    cls = None
    cols: List[str] = []
    table = ""
    owner_fk = None
    if res:
        table, meta = res
        cls, cols = meta["cls"], meta["cols"]
        # The column that attributes a row to the authenticated caller (user_id/
        # author_id/...). Used to AUTHORIZE mutations (PUT/DELETE only touch your
        # OWN rows). NOTE: read-scoping (GET list/item) is deliberately NOT keyed
        # off this — "only see your own rows" is domain-dependent (private notes
        # vs a public feed), so it stays a separate, explicit decision.
        owner_fk = _owner_fk(meta) if auth else None

    # Nested parent: /api/users/{username}/posts → parent users(User) via {username}.
    parent_ctx = _parent_context(path, models, table) if cls else None
    parent_cls = parent_table = parent_singular = parent_param = parent_field = None
    # NESTED-RESOURCE ISOLATION: when the PARENT table is per-user-private (owner-scoped
    # reads), a nested route (/api/projects/{id}/tasks) must owner-check the parent — else
    # a user reaches another user's children via the nested path (smoke-proj: GET
    # /api/projects/{otherId}/tasks → 200 leaked another user's tasks). The parent lookup
    # then filters by its owner FK == _fw_uid(user), so a non-owned parent resolves to None → 404.
    _parent_owner_filter = ""
    if parent_ctx:
        parent_table, parent_meta, parent_param = parent_ctx
        parent_cls = parent_meta["cls"]
        parent_singular = parent_table.rstrip("s")
        parent_field = _lookup_field(parent_param, parent_meta)
        # FIX #288 (tiktok r73, live): owner-scoping the parent lookup is correct for a PRIVATE
        # container (/api/projects/{id}/tasks — you may only reach your own project), but WRONG
        # for the app's primary PUBLIC content. TikTok's videos are public (#279 already serves
        # the FYP feed logged-out); commenting/liking authenticates the ACTOR but targets ANY
        # video. Scoping the parent turned "must log in to comment" into "can only comment on
        # your OWN videos" → a non-author's POST/GET /api/videos/{id}/comments resolved
        # parent=None → 404 → fyp_comments ui_flow failed (r73's sole remaining blocker). So skip
        # the parent filter when the parent IS the primary content model (the public feed source,
        # shape-derived) — mirroring #279 (the login wall is on interaction, not on the content).
        # A genuinely private container (not the feed's content model) still scopes its parent,
        # preserving the cross-user leak protection the filter was added for.
        _pc = _primary_content_model(models)
        _pc_table = _pc[0] if _pc else None
        if (auth and owner_scoped_tables and parent_table in set(owner_scoped_tables)
                and parent_table != _pc_table):
            _p_ofk = _owner_fk(parent_meta)
            if _p_ofk:
                _parent_owner_filter = f'.filter(getattr({parent_cls}, "{_p_ofk}") == _fw_owner_val({parent_cls}, "{_p_ofk}", user))'

    body_lines: List[str] = []
    m = method.upper()

    scope_fk = (
        _scope_fk(meta, parent_table, parent_singular)
        if (cls and parent_ctx and m == "GET" and not _ends_in_param(path))
        else None
    )

    if cls and m == "GET" and not _ends_in_param(path) and parent_ctx and scope_fk:
        # NESTED COLLECTION: resolve the parent, list the child scoped by its FK.
        body_lines = [
            f'    parent = db.query({parent_cls}).filter(getattr({parent_cls}, "{parent_field}") == {parent_param}){_parent_owner_filter}.first()',
            "    if parent is None:",
            '        raise HTTPException(status_code=404, detail="not found")',
            f'    rows = db.query({cls}).filter(getattr({cls}, "{scope_fk}") == parent.id).limit(100).all()',
            f'    return {{"items": [{_serialize_expr("r", cols)} for r in rows], "total": len(rows)}}',
        ]
    elif cls and m == "GET" and not _ends_in_param(path) and parent_ctx:
        # NESTED COLLECTION, no direct child→parent FK (scope_fk is None): the link is
        # MANY-TO-MANY via an association table (e.g. /genres/{id}/titles where `titles`
        # has no genre_id column — the link lives in title_genres). The old code fell
        # THROUGH to the plain-collection branch below → returned EVERY child row, 200,
        # ignoring the parent entirely (netflix r112 live: GET /api/genres/{missing}/titles
        # → 200 instead of 404 → business_chain wedged for ~50 min, never cut a release).
        # Resolve the parent (404 if missing — mirrors the scope_fk branch above, incl. the
        # #288/#77 owner filter) and, when an association table links parent↔child, scope
        # the list THROUGH it so the child rows are actually the parent's.
        _assoc = _assoc_table(models, parent_table, table)
        body_lines = [
            f'    parent = db.query({parent_cls}).filter(getattr({parent_cls}, "{parent_field}") == {parent_param}){_parent_owner_filter}.first()',
            "    if parent is None:",
            '        raise HTTPException(status_code=404, detail="not found")',
        ]
        if _assoc:
            _acls, _a_pcol, _a_ccol = _assoc
            body_lines.append(
                f'    rows = db.query({cls}).join({_acls}, getattr({_acls}, "{_a_ccol}") == getattr({cls}, "id")).filter(getattr({_acls}, "{_a_pcol}") == parent.id).limit(100).all()'
            )
        else:
            body_lines.append(f"    rows = db.query({cls}).limit(100).all()")
        body_lines.append(
            f'    return {{"items": [{_serialize_expr("r", cols)} for r in rows], "total": len(rows)}}'
        )
    elif cls and m == "GET" and _ends_in_param(path) and last_param and _is_id_param(last_param):
        # GET item by id
        body_lines = [
            f"    obj = db.get({cls}, {last_param})",
            "    if obj is None:",
            '        raise HTTPException(status_code=404, detail="not found")',
        ]
        if owner_scoped_reads and owner_fk:
            # PRIVATE resource: a non-owner read is a 404 (not 403 — don't even
            # leak existence), exactly like the PUT/DELETE owner gate. Opt-in via
            # the resource's owner_scoped_reads contract signal; open by default.
            body_lines += [
                f'    if getattr(obj, "{owner_fk}", None) != _fw_owner_val(type(obj), "{owner_fk}", user):',
                '        raise HTTPException(status_code=404, detail="not found")',
            ]
        body_lines += [
            f"    return {{\"item\": {_serialize_expr('obj', cols)}}}",
        ]
    elif (cls and m == "DELETE" and not _ends_in_param(path) and parent_ctx
          and _target_fk(meta, parent_table, parent_singular)):
        # CHILD-COLLECTION TOGGLE-OFF: DELETE /api/<parent>/{parent_id}/<child>
        # (unlike / unsave / unfollow) removes the CALLER's row in <child> scoped to
        # the parent. The old branch did db.get(<child>, parent_id) — but parent_id is
        # the PARENT's id, NOT the child row's PK, so it deleted the wrong row / 404'd /
        # 500'd (instagram_v6: DELETE /api/posts/{post_id}/like|save + /users/{username}/
        # follow all 500 → delivery wedged). Find by (target_fk==parent.id [, owner_fk==
        # _fw_uid(user)]) and delete idempotently (a no-op delete still succeeds — toggles are
        # safe to repeat). Uses _target_fk (the create-bind FK) NOT _scope_fk so a
        # self-referential join (follows: follower_id + following_id both → users)
        # filters the FOLLOWED side (following_id==parent.id) against the OWNER side
        # (follower_id==_fw_uid(user)) — mirrors the create handler's bind.
        _sfk = _target_fk(meta, parent_table, parent_singular)
        body_lines = [
            f'    parent = db.query({parent_cls}).filter(getattr({parent_cls}, "{parent_field}") == {parent_param}){_parent_owner_filter}.first()',
            "    if parent is None:",
            '        raise HTTPException(status_code=404, detail="not found")',
            f'    _q = db.query({cls}).filter(getattr({cls}, "{_sfk}") == parent.id)',
        ]
        if owner_fk:
            body_lines.append(
                f'    _q = _q.filter(getattr({cls}, "{owner_fk}") == _fw_owner_val({cls}, "{owner_fk}", user))')
        body_lines += [
            "    obj = _q.first()",
            "    if obj is not None:",
            "        db.delete(obj)",
            "        db.commit()",
            '    return {"item": {"deleted": True}}',
        ]
    elif cls and m == "DELETE" and last_param and _is_id_param(last_param):
        body_lines = [
            f"    obj = db.get({cls}, {last_param})",
            "    if obj is None:",
            '        raise HTTPException(status_code=404, detail="not found")',
        ]
        if owner_fk:
            # AUTHORIZE: only the owner may delete (404, not 403, so a non-owner
            # can't even probe existence). Safe default for projected CRUD; broader
            # rules (admin/moderator) go in the lane's custom_routes.
            body_lines += [
                f'    if getattr(obj, "{owner_fk}", None) != _fw_owner_val(type(obj), "{owner_fk}", user):',
                '        raise HTTPException(status_code=404, detail="not found")',
            ]
        body_lines += [
            "    db.delete(obj)",
            "    db.commit()",
            f"    return {{\"item\": {{\"id\": {last_param}, \"deleted\": True}}}}",
        ]
    elif cls and m == "GET" and _ends_in_param(path) and last_param and not _is_id_param(last_param):
        # GET by non-id field (e.g. username). Match on the model's matching column.
        field = "username" if "username" in cols else (last_param if last_param in cols else "id")
        if field == "id":
            # Fallback: the model has no matching text column (e.g. the contract
            # registered users with EMPTY columns → spine-only model). The path param
            # is a string; comparing it raw against the integer id column is a
            # postgres type error → 500 on every probe (instagram M1: GET
            # /api/users/{username} → 500 burned the whole validation budget).
            # Coerce safely: non-numeric → 404 (a valid "not found"), numeric → int.
            body_lines = [
                f"    _key = str({last_param}).strip()",
                "    if not _key.lstrip('-').isdigit():",
                '        raise HTTPException(status_code=404, detail="not found")',
                f"    obj = db.query({cls}).filter(getattr({cls}, \"id\") == int(_key)).first()",
                "    if obj is None:",
                '        raise HTTPException(status_code=404, detail="not found")',
                f"    return {{\"item\": {_serialize_expr('obj', cols)}}}",
            ]
        else:
            body_lines = [
                f"    obj = db.query({cls}).filter(getattr({cls}, \"{field}\") == {last_param}).first()",
                "    if obj is None:",
                '        raise HTTPException(status_code=404, detail="not found")',
                f"    return {{\"item\": {_serialize_expr('obj', cols)}}}",
            ]
    elif cls and m == "GET" and "search" in path:
        # Search the model's TEXTUAL columns, derived from the contract's type map —
        # not a hardcoded social/content name allowlist (which silently failed to
        # search any column outside that vocabulary). Falls back to all columns when
        # the type map is unavailable (raw-SQL app); the runtime hasattr() guards it.
        _tmap = (meta.get("types") or {}) if res else {}
        def _sensitive(_c):
            _l = _c.lower()
            return ("password" in _l or _l.endswith("_hash") or "secret" in _l or "token" in _l)
        _search_cols = [c for c in cols if not _sensitive(c) and any(
            k in str(_tmap.get(c, "")).lower() for k in ("char", "text", "string", "clob", "unicode"))]
        if not _search_cols:
            _search_cols = [c for c in cols if not _sensitive(c)]
        body_lines = [
            "    term = (q or \"\").strip()",
            f"    query = db.query({cls})",
        ]
        if owner_scoped_reads and owner_fk:
            body_lines.append(
                f'    query = query.filter(getattr({cls}, "{owner_fk}") == _fw_owner_val({cls}, "{owner_fk}", user))')
        body_lines += [
            "    if term:",
            f"        cols_to_search = [c for c in {_search_cols!r} if hasattr({cls}, c)]",
            "        from sqlalchemy import or_ as _or, String as _Str, Text as _Txt",
            # ``ilike`` is only valid on a STRING/TEXT column. When the type map was
            # unavailable the projector falls back to ALL columns, so a runtime type
            # guard is REQUIRED — calling ``.ilike`` on an Integer/Boolean/DateTime
            # column raises (outlook GET /api/messages/search → 500). Skip non-text cols.
            f"        conds = [getattr({cls}, c).ilike(f\"%{{term}}%\") for c in cols_to_search"
            f" if isinstance(getattr(getattr({cls}, c), 'type', None), (_Str, _Txt))]",
            "        if conds:",
            "            query = query.filter(_or(*conds))",
            "    rows = query.limit(50).all()",
            f"    return {{\"items\": [{_serialize_expr('r', cols)} for r in rows], \"total\": query.count()}}",
        ]
        sig_params += 'q: str = "", '
    elif m == "GET" and path.endswith("/me"):
        # GET /<resource>/me → the CURRENT authenticated user as a single {item}.
        # "me" is a STATIC segment (not a path param), so without this case it falls
        # through to the GET-collection branch and returns EVERY row — a shape AND
        # semantic bug. CRITICALLY this must NOT be gated on the path's resource
        # segment resolving to a model: ``/api/auth/me`` has resource "auth" (no
        # table) → cls is None → it used to skip this branch and hit the generic GET
        # stub, which shipped a ``{"items":[],"total":0}`` LIST envelope whenever the
        # contract's response_key wasn't "item" → business_endpoints_correct_shape
        # failed forever ("returns a list but the contract is a single item"; outlook
        # run #2, GET /api/auth/me). /me is ALWAYS the authenticated caller's own
        # record, so resolve to the users model (so the row serializes with its real
        # columns) regardless of the resource segment.
        _me = _me_user_model(models) or ((cls, cols) if cls else None)
        if _me and _me[0]:
            _ucls, _ucols = _me
            body_lines = [
                (f"    obj = db.get({_ucls}, _fw_owner_val({_ucls}, 'id', user)) if user is not None else None"
                 if auth else f"    obj = db.query({_ucls}).first()"),
                "    if obj is None:",
                '        raise HTTPException(status_code=404, detail="not found")',
                f"    return {{\"item\": {_serialize_expr('obj', _ucols)}}}",
            ]
        else:
            body_lines = ['    return {"item": {}}']
    elif cls and m == "GET":
        # GET collection
        if owner_scoped_reads and owner_fk:
            # PRIVATE resource: the list is the caller's own rows only.
            body_lines = [
                f'    rows = db.query({cls}).filter(getattr({cls}, "{owner_fk}") == _fw_owner_val({cls}, "{owner_fk}", user)).limit(100).all()',
                f"    return {{\"items\": [{_serialize_expr('r', cols)} for r in rows], \"total\": len(rows)}}",
            ]
        else:
            body_lines = [
                f"    rows = db.query({cls}).limit(100).all()",
                f"    return {{\"items\": [{_serialize_expr('r', cols)} for r in rows], \"total\": len(rows)}}",
            ]
    elif cls and m in ("POST", "PUT", "PATCH"):
        # DB mutations are wrapped: a relational create the projector can't fully
        # wire (e.g. a missing NOT-NULL FK) must not 500 — roll back + answer.
        body_lines = [
            "    payload = body if isinstance(body, dict) else {}",
            f"    valid = {{k: v for k, v in payload.items() if hasattr({cls}, k)}}",
            # DROP unresolved verification-chain placeholders ("${calendar_id}" / "{calendar_id}")
            # before constructing the ORM row. A chain that cannot bind an FK var — e.g. the app
            # exposes no POST for the parent resource (outlook: GET /api/calendars but no POST), so
            # ${calendar_id} never resolves — otherwise sends the LITERAL token, which the projected
            # insert passes to the typed column → psycopg InvalidTextRepresentation ("invalid input
            # syntax for type integer: \"${calendar_id}\"") → 500 that wedges business_chain (run-14).
            # Skipping it lets a NULLABLE FK stay null and the create succeed (a required FK still
            # errors honestly). Whole-value tokens only, so real data (e.g. a JSON string) is kept.
            "    valid = {k: v for k, v in valid.items() if not ("
            "isinstance(v, str) and v.endswith(\"}\") and (v.startswith(\"${\") or "
            "(v.startswith(\"{\") and v[1:-1].isidentifier())))}",
            # Audit rank-4: coerce loosely-typed chain body values to each column's ACTUAL
            # type for BOTH create AND update (was create-only #395). A thumbs rating
            # {"value":"up"} into an INTEGER col, "true"/"1" into a Boolean col — the
            # setattr / cls(**valid) below then can't 500 on a type mismatch, and a value
            # that still can't be coerced (a bad datetime) is caught by the global
            # DataError->400 handler rather than 500ing. No-op for a well-typed body.
            f"    valid = _coerce_body({cls}, valid)",
        ]
        # #566u: owner-scoped STATE-WRITE upsert-on-conflict params (set only for a POST create below)
        _uc_enabled = False
        _uc_ofk = None
        _uc_subject_fks: List[str] = []
        if m in ("PUT", "PATCH") and path.endswith("/me"):
            # mirror GET /me: resolve the user model DYNAMICALLY. Hardcoding `User`
            # broke /me updates for any app whose user table isn't literally named
            # User (accounts/profiles/members) — `NameError: User` at request time.
            _me_u = _me_user_model(models) or ((cls, cols) if cls else None)
            _ucls = (_me_u[0] if (_me_u and _me_u[0]) else None) or cls
            body_lines += [
                "    try:",
                f"        obj = db.get({_ucls}, _fw_owner_val({_ucls}, 'id', user))" if auth else f"        obj = db.query({_ucls}).first()",
                "        if obj is None:",
                '            raise HTTPException(status_code=404, detail="not found")',
                "        for k, v in valid.items():",
                "            setattr(obj, k, v)",
            ]
        elif m in ("PUT", "PATCH") and last_param and _is_id_param(last_param):
            # UPDATE the existing row by id — NOT a new insert. Falling through to
            # the create path below made PUT/PATCH do ``cls(**valid); db.add`` →
            # every update INSERTED a duplicate row (live: PUT /api/notes/{id}
            # created notes instead of editing them).
            body_lines += [
                "    try:",
                f"        obj = db.get({cls}, {last_param})",
                "        if obj is None:",
                '            raise HTTPException(status_code=404, detail="not found")',
            ]
            if owner_fk:
                body_lines += [
                    f'        if getattr(obj, "{owner_fk}", None) != _fw_owner_val(type(obj), "{owner_fk}", user):',
                    '            raise HTTPException(status_code=404, detail="not found")',
                ]
            body_lines += [
                "        for k, v in valid.items():",
                "            setattr(obj, k, v)",
            ]
        elif m in ("PUT", "PATCH") and owner_fk and not last_param:
            # #277 (r61, live): PATCH /api/settings 500'd. An owner-scoped SINGLETON with no
            # id param and not ending in /me (settings / preferences / profile / config — one
            # row per user) fell through to the CREATE path below, so PATCH did
            # ``cls(**valid); db.add`` — a second INSERT that hit the owner/unique constraint
            # (or a NOT-NULL owner it never set). It is a one-row-per-user resource, so load
            # the caller's existing row (like /me) and setattr onto it; create it if absent so
            # a first PATCH still works.
            body_lines += [
                "    try:",
                f'        obj = db.query({cls}).filter('
                f'getattr({cls}, "{owner_fk}") == _fw_owner_val({cls}, "{owner_fk}", user)).first()',
                "        if obj is None:",
                f'            obj = {cls}(**valid)',
                f'            setattr(obj, "{owner_fk}", _fw_owner_val({cls}, "{owner_fk}", user))',
                "            db.add(obj)",
                "        else:",
                "            for k, v in valid.items():",
                "                setattr(obj, k, v)",
            ]
        else:
            bound: List[str] = []
            # Bind a path-param parent into the relation's TARGET FK, and inject the
            # authenticated caller into the OWNER FK — so created rows are attributed.
            if m == "POST" and parent_ctx:
                tfk = _target_fk(meta, parent_table, parent_singular)
                if tfk:
                    body_lines += [
                        f'    _parent = db.query({parent_cls}).filter(getattr({parent_cls}, "{parent_field}") == {parent_param}){_parent_owner_filter}.first()',
                        # #498 (netflix r67, live): a nested create under /parents/{id}/children whose
                        # path-derived parent does NOT resolve must 404 — NOT silently omit the FK and
                        # let the INSERT NULL-violate. r67 wedged here: the chain rated title 11 (seed
                        # had only ids 1-6), _parent was None, ``valid`` never got title_id, the INSERT
                        # 400'd ``null value in column "title_id"`` — an OPAQUE error the verifier
                        # misread as a HANDLER bug and re-authored the chain 303× chasing it. A 404
                        # ("parent not found") is the HONEST, correct-REST outcome: every chain
                        # expect-family tolerates 404 (see #124), remediation routes to the missing
                        # parent (chain/seed) instead of the handler, and the churn breaks. HAPPY PATH
                        # (parent exists) is byte-identical to before — this only changes the
                        # parent-missing branch, which previously produced a wedging 400 or an orphan
                        # row. Generalizes to every projected nested create in every app.
                        "    if _parent is None:",
                        '        raise HTTPException(status_code=404, detail="parent resource not found")',
                        f'    valid["{tfk}"] = _parent.id',
                    ]
                    bound.append(tfk)
            # FIX #124 (instagram run-43 M1, live): an ACTION-suffix POST whose action
            # segment did NOT resolve to its own model falls back here with cls = the
            # PARENT entity — the generic create then INSERTS A NEW PARENT on the action
            # route (POST /api/users/{id}/unfollow → User(**{}) → NotNull → 400 on the
            # HAPPY PATH; the chain wedged 35+ min while follow — whose 'follow' segment
            # DID map to the Follow association — worked). A semantically-unmappable
            # action must 404 ("not implemented") instead: every chain expect-family
            # tolerates 404, and the lane's custom handler — registered BEFORE the
            # projected routes — wins the match the moment it exists.
            _segs_np = [g for g in str(path).strip("/").split("/")
                        if g and not (g.startswith("{") or g.startswith(":"))]
            _last_np = (_segs_np[-1].lower() if _segs_np else "")
            _action_unmapped = (
                m == "POST" and params and not str(path).rstrip("/").endswith("}")
                and not bound
                and _last_np not in (str(table).lower(),
                                     str(table).lower().rstrip("s"))
            )
            if _action_unmapped:
                body_lines = [
                    "    raise HTTPException(status_code=404, detail="
                    "\"action endpoint not implemented by the projection — "
                    "the app's own handler serves this route\")",
                ]
            if m == "POST" and auth:
                ofk = _owner_fk(meta, exclude=tuple(bound))
                if ofk:
                    # #566s: REJECT a cross-user create — a body owner-FK the caller does NOT own
                    # → 403 (IDOR: userB POSTing body profile_id=userA's). An OWNED value is kept
                    # (multi-profile); absent → resolve the caller's own via _fw_owner_val.
                    body_lines += [
                        f'    if valid.get("{ofk}") is not None and not _fw_owns({cls}, "{ofk}", valid.get("{ofk}"), user):',
                        f'        raise HTTPException(status_code=403, detail="{ofk} does not belong to the caller")',
                        f'    valid.setdefault("{ofk}", _fw_owner_val({cls}, "{ofk}", user))',
                    ]
            if m == "POST":
                # #566t: a create body that DROPPED a NOT-NULL column (verifier authored the wrong
                # key) INSERTs NULL even when the column has a DB DEFAULT → NOT-NULL 400. Apply the
                # column's DB default explicitly for any absent NOT-NULL no-model-default column.
                body_lines += [f'    valid = _fw_fill_required_defaults({cls}, valid, db)']
                # #566u: enable upsert-on-conflict for an owner-scoped STATE-WRITE (owner + subject FKs
                # = natural key: rating/my_list/continue_watching re-write must UPDATE, not 409).
                _uc_ofk = _owner_fk(meta, exclude=tuple(bound))
                if not _action_unmapped and _uc_ofk:
                    _uc_subject_fks = [str(_f) for _f in (meta.get("fks") or {})
                                       if str(_f) != str(_uc_ofk)]
                    _uc_enabled = bool(_uc_subject_fks)
            if not _action_unmapped:
                body_lines += [
                    # valid was already coerced to the column types up-front (rank-4,
                    # covers create + update); just construct + add here.
                    "    try:",
                    f"        obj = {cls}(**valid)",
                    "        db.add(obj)",
                ]
        if body_lines and body_lines[0].lstrip().startswith("raise HTTPException(status_code=404"):
            pass  # FIX #124 stub body is complete — no create/commit footer
        else:
            body_lines += [
                "        db.commit()",
            "        db.refresh(obj)",
            f"        return {{\"item\": {_serialize_expr('obj', cols)}}}",
            "    except HTTPException:",
            "        raise",
            "    except IntegrityError:",
            "        # FIX #93 (run-12 M2, live): an integrity violation is CLIENT-DATA",
            "        # (probe body missing password_hash → NotNull; bad FK; duplicate) —",
            "        # REST semantics are 4xx, and the catch-all's 500 BYPASSED the",
            "        # by-construction global IntegrityError handler → reachability",
            "        # wedged. Rollback and RE-RAISE: the global handler maps it",
            "        # (FK 23503→404, unique 23505→409, other incl. NotNull→400).",
            "        db.rollback()",
            *(([  # #566u: owner-scoped state-write → UPSERT on the (owner,subject) conflict, not 409
                f'        _uc = _fw_upsert_on_conflict(db, {cls}, valid, user, "{_uc_ofk}", {_uc_subject_fks!r})',
                "        if _uc is not None:",
                f"            return {{\"item\": {_serialize_expr('_uc', cols)}}}",
             ]) if _uc_enabled else []),
            "        raise",
            "    except DataError:",
            "        # rank-4: a value that doesn't fit the column TYPE (bad datetime/int/",
            "        # bool / out-of-range) is CLIENT data, not a server fault. Rollback and",
            "        # RE-RAISE to the global DataError->400 handler — the catch-all's 500",
            "        # below lands in no chain's expect list -> business_chain wedge.",
            "        db.rollback()",
            "        raise",
            "    except Exception as _exc:",
            "        db.rollback()",
            "        # Surface the failure HONESTLY — do NOT return a fake 201 whose",
            "        # body lacks the PK. A masked insert made a verification chain that",
            "        # captures {id} from the create bind nothing, so ${...} reached the",
            "        # next step (→ 422), and hid the real cause (e.g. a null-PK / NOT",
            "        # NULL violation). A 500 lets the gate + the owning lane see it.",
            "        raise HTTPException(status_code=500, detail=f\"create failed: {_exc}\")",
        ]
        sig_params += "body: dict = None, " if "body: dict" not in sig_params else ""
    else:
        # Valid-shape stub — unknown pattern, but the route must answer (no 404).
        if m == "GET" and last_param:
            # SHAPE CORRECTNESS (2026-06-11, live: GET /api/business_discovery/
            # {username} — an MCP-doc endpoint with no table — was stubbed as a
            # COLLECTION, and the business_endpoints_correct_shape gate
            # rightly failed it forever). A parameterized GET is single-
            # resource by contract: resolve via a model whose column matches
            # the param name (generic — {username}→users.username works for
            # ANY app), else an honest 404 (the gate only checks 2xx shapes).
            _resolver = None
            # FIX #162 (gmrun7 transit 500): a GENERIC id param is a meaningless resolver
            # signal — EVERY model has an ``id`` column, so ``last_param in _col_names``
            # matched the FIRST model (the tenants spine, TEXT id) for an unmappable path
            # like ``/api/transit/{id}/departures`` → ``db.query(Tenant).filter(Tenant.id ==
            # id)`` with ``id: int`` → ``operator does not exist: text = integer`` → 500 on
            # every call (M2 wedge). Resolve ONLY via a DISTINCTIVE (non-id) param that
            # uniquely names a column (username/slug/handle); a generic-id unmappable path
            # falls to the honest 404 stub below (a param-path 404 is exempted by the
            # reachability gate; the lane implements the real handler in custom_routes.py).
            if not _is_id_param(last_param):
                for _mn, _mm in (models or {}).items():
                    # the models dict shape is {table: {"cls": str, "cols": [name,...]}} —
                    # the prior _mm.get("columns")/"class_name" keys never existed, so this
                    # resolver was dead (always 404). Read the real keys.
                    _col_names = list(_mm.get("cols") or [])
                    if last_param in _col_names:
                        _resolver = (_mm.get("cls") or _mn.capitalize(),
                                     last_param, _col_names)
                        break
            if _resolver:
                _cls, _col, _col_names = _resolver
                body_lines = [
                    f"    obj = db.query({_cls}).filter({_cls}.{_col} == {last_param}).first()",
                    "    if obj is None:",
                    "        raise HTTPException(status_code=404, detail=\"not found\")",
                    f"    return {{\"item\": {_serialize_expr('obj', _col_names)}}}",
                ]
            else:
                body_lines = [
                    "    raise HTTPException(status_code=404, detail=\"not found\")",
                ]
        elif m == "GET":
            # SHAPE CORRECTNESS (youtube run #16, 2026-06-20): a non-param GET whose
            # resource has no resolvable model (e.g. GET /api/auth/me — "auth" has no
            # table) fell through to the COLLECTION stub, but the contract declared
            # response_key='item' → business_endpoints_correct_shape failed forever
            # ("returns a list but the contract is a single item"). Honor the declared
            # response_key so the stub shape always matches the contract.
            if response_key == "item":
                body_lines = ['    return {"item": {}}']
            else:
                body_lines = ['    return {"items": [], "total": 0}']
        elif m == "DELETE":
            body_lines = ['    return {"item": {"deleted": True}}']
        else:
            body_lines = ['    return {"item": {}}']

    status = ', status_code=201' if m == "POST" else ""
    # body param must come before defaults-with-Depends in the signature
    sig = f"{sig_params}{deps}"
    return (
        f'@app.{method.lower()}("{path}"{status})\n'
        f"def {fn}({sig}):\n"
        + "\n".join(body_lines)
    )


def _insert_before_first_route(src: str, block: str) -> str:
    """Insert *block* right before the FIRST ``@app.<method>(`` route decorator, so the
    static routes it carries are defined before any lane route (and thus win FastAPI's
    in-order match). Falls back to before the main guard if no route is found yet."""
    m = re.search(r"^@app\.(?:get|post|put|delete|patch)\(", src, re.M)
    if not m:
        return _insert_before_main_guard(src, block)
    at = m.start()
    return src[:at] + block + "\n\n\n" + src[at:]


def _insert_before_main_guard(src: str, block: str) -> str:
    marker = 'if __name__ == "__main__":'
    idx = src.rfind(marker)
    if idx == -1:
        return src.rstrip() + "\n\n\n" + block + "\n"
    return src[:idx].rstrip() + "\n\n\n" + block + "\n\n\n" + src[idx:]


def _truthy(v: Any) -> bool:
    """Tolerant truthiness for a contract flag that may arrive as a real bool, a
    JSON string ("true"/"1"/"yes"), or already-coerced — the hub round-trips
    metadata through JSON and lane/LLM writers are inconsistent."""
    if isinstance(v, str):
        return v.strip().lower() in {"true", "1", "yes", "y", "on"}
    return bool(v)


def project_missing_routes(
    backend_dir: Any,
    declared_endpoints: List[Mapping[str, Any]],
    owner_scoped_tables: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """Append a projected handler to ``main.py`` for every declared business
    endpoint that has no route. Returns ``{"projected": [...], "already": int}``.

    ``declared_endpoints``: ``[{method, path, auth_required?}]`` — the contract the
    lanes were supposed to implement (RegistryHub business endpoints).

    ``owner_scoped_tables``: table names the CONTRACT marked per-user-private
    (``owner_scoped_reads`` in the table metadata). Their reads are owner-scoped
    by construction. This is the RELIABLE source — one decision per table at
    kickoff — and is unioned with any per-endpoint ``owner_scoped_reads`` flag."""
    backend_dir = Path(backend_dir)
    main_py = backend_dir / "main.py"
    if not main_py.exists():
        return {"projected": [], "already": 0, "error": "main.py absent"}
    src = main_py.read_text(encoding="utf-8")
    existing = _existing_routes(src)
    models = _orm_models(backend_dir)

    # Per-RESOURCE read-visibility: a resource is read-isolated if ANY of its
    # declared endpoints carries the owner_scoped_reads signal (the contract may
    # mark only the collection or only the item — apply it to EVERY read of the
    # resource). Empty ⇒ all reads open (public-feed reference behaviour, default).
    scoped_read_tables: set = set(owner_scoped_tables or ())
    for ep in declared_endpoints:
        md = ep.get("metadata") if isinstance(ep.get("metadata"), Mapping) else {}
        _sch = ep.get("schema") if isinstance(ep.get("schema"), Mapping) else {}
        if (_truthy(ep.get("owner_scoped_reads")) or _truthy(md.get("owner_scoped_reads"))
                or _truthy(_sch.get("owner_scoped_reads"))):
            rm = _resource_model(_express_to_fastapi(str(ep.get("path", ""))), models)
            if rm:
                scoped_read_tables.add(rm[0])

    projected: List[str] = []
    block_info: List[Tuple[str, str]] = []  # (path, handler source)
    for i, ep in enumerate(declared_endpoints):
        method = str(ep.get("method", "")).upper()
        # Normalise Express-style ``:id`` → FastAPI ``{id}`` before anything reads the
        # path: the decorator we emit, the param list, and the dedup key all then see a
        # real path param (BUG #11). ``_norm_path`` collapses ``{id}``≡``{x}`` so a
        # ``:id`` that duplicates an existing ``{x}`` route is de-duped automatically
        # (the native ``{...}`` route already in ``existing`` wins; no 2nd decorator).
        path = _express_to_fastapi(str(ep.get("path", "")))
        # Only /api/ business endpoints are lane-owned + projectable. /auth/* is
        # owned by the embedded OAuth2 AS (register/login are framework-guaranteed)
        # so it is never projected here.
        if not method or not path.startswith("/api/"):
            continue
        if (method, _norm_path(path)) in existing:
            continue
        meta = ep.get("metadata") if isinstance(ep.get("metadata"), Mapping) else {}
        _rm_cur = _resource_model(path, models)
        _owner_scoped = bool(_rm_cur and _rm_cur[0] in scoped_read_tables)
        # #320 (r88/r89 public-feed wedge): a table can hold OWNED-but-PUBLIC content
        # (TikTok videos, IG posts, YT videos) — rows have a creator yet the feed is
        # public (the design inputs literally include fyp_feed_logged_out.png). Its
        # per-table owner_scoped_reads flag (set for the "my videos" profile view / write
        # ownership) otherwise owner-scopes + #315-force-auths EVERY read, so the public
        # feed 401s and the ui_flow gate wedges. An EXPLICIT auth_required=False is the
        # lane's DELIBERATE "this read is public" declaration — honor it: serve public
        # (no owner row-filter, no force-auth) for THIS endpoint. UNSTATED reads on an
        # owner-scoped table still force-auth + owner-scope (r58/#315 leak protection: a
        # private table's unstated read must NOT default open — a strong model marks a
        # genuinely-private list private and only sets =False on a real public feed).
        _explicit_public = (ep.get("auth_required") is False) or (
            isinstance(meta, Mapping) and meta.get("auth_required") is False)
        if _explicit_public and _owner_scoped:
            _owner_scoped = False   # deliberate public read → all rows, no owner filter
        # An owner-scoped resource is per-user PRIVATE (notes/email/drafts): its reads
        # can only be scoped to ``owner_fk == the caller``, which REQUIRES an actor. #271
        # made an unstated read default to PUBLIC — so a private resource whose contract
        # marked owner_scoped_reads but not auth_required projected anonymous + UNSCOPED
        # (owner_fk is None when auth is False → the owner filter is silently dropped →
        # every caller, even anonymous, reads every row: a cross-user leak). Force auth
        # for an owner-scoped resource so the by-construction read isolation actually
        # takes effect. This DELIBERATELY overrides even an explicit auth_required=False:
        # "per-user-private reads" and "public" are contradictory, and a private read is
        # unscopable without an actor — so owner_scoped wins here. Non-owner-scoped
        # endpoints keep resolve_endpoint_auth's decision unchanged (incl. explicit False).
        auth = resolve_endpoint_auth(method, path, ep, meta) or _owner_scoped   # #271
        _schema = ep.get("schema") if isinstance(ep.get("schema"), Mapping) else {}
        response_key = str(
            ep.get("response_key")
            or (_schema.get("response_key") if isinstance(_schema, Mapping) else "")
            or meta.get("response_key")
            or ""
        ).strip()
        block_info.append((path, _generate_handler(method, path, auth, models, i, response_key, _owner_scoped, owner_scoped_tables=scoped_read_tables)))
        projected.append(f"{method} {path}")
        existing.add((method, _norm_path(path)))  # dedupe within this batch

    if block_info:
        # Imports/helpers the projected handlers rely on — injected idempotently +
        # GUARDED so a raw-SQL app with no models.py (run #13) does not crash on load.
        # Single source of truth: _PROJECTOR_GUARD (shared with #556's state-write
        # projection). The _fw_owner_val / _coerce_body re-defs are try/except-guarded
        # so the skeleton header's richer canonical versions always win when present.
        guard = _PROJECTOR_GUARD
        # STATIC routes (no path param) match an exact path only, so they can never
        # shadow anything — but a lane catch-all like /api/users/{username} WILL shadow
        # a projected /api/users/suggested if the latter is defined after it (run #13:
        # suggested → 404 'user not found'). Define static projected routes BEFORE the
        # first route so they win; keep PARAM routes last so they never shadow the lane.
        static_blocks = [b for p, b in block_info if "{" not in p]
        param_blocks = [b for p, b in block_info if "{" in p]
        new_src = src
        top = ("# === BY-CONSTRUCTION (static-first): specific projected routes +\n"
               "# guarded deps, before the lane's catch-all param routes.\n"
               + guard
               + ("\n" + "\n\n\n".join(static_blocks) if static_blocks else ""))
        new_src = _insert_before_first_route(new_src, top)
        if param_blocks:
            new_src = _insert_before_main_guard(
                new_src,
                "# === BY-CONSTRUCTION: param routes the lane declared but did not\n"
                "# implement (appended last so /{id} patterns never shadow lane routes).\n"
                + "\n\n\n".join(param_blocks))
        main_py.write_text(new_src, encoding="utf-8")

    return {"projected": projected, "already": len(existing) - len(projected)}


# ---------------------------------------------------------------------------
# #556 — HEAL for the missing-write-path class (the #557 oracle's heal side)
# ---------------------------------------------------------------------------
# A STATE-BEARING entity (a table with a mutable data column — progress_seconds,
# a status/position/value/is_* toggle) that is READABLE (has a GET) but has NO
# write endpoint (no POST/PUT/PATCH) is non-functional: the feature only ever
# reflects seed data because there is no way to RECORD state (Netflix "resume
# watching" never updates progress). #557's oracle DETECTS this; the functions
# below are the framework HEAL: for each such entity they auto-project an
# idempotent UPSERT write handler (POST on the entity's collection) keyed off the
# table's natural owner+subject FKs, so the loop closes and the feature works.
# Generalizable — derived from the schema (mutable column(s) + owner/subject FKs),
# never from any product literal. Byte-identical when the entity already has a
# write or isn't state-bearing (the shared #557 classifier returns it empty).

def _fk_columns(meta: Dict[str, Any]) -> List[str]:
    """The table's foreign-key columns (schema order): a column declared with an
    explicit ``ForeignKey(...)`` OR whose name is ``<x>_id`` (the overwhelming FK
    convention). The bare ``id`` PK is never an FK."""
    cols = meta.get("cols", []) or []
    fks = meta.get("fks", {}) or {}
    out: List[str] = []
    for c in cols:
        cl = str(c).lower()
        if c in fks or (cl.endswith("_id") and cl != "id"):
            out.append(c)
    return out


def _state_write_collection_path(entity: str, endpoints: Any) -> str:
    """The FLAT collection path to hang the projected upsert on.

    Prefer the entity's own existing GET collection path (so the POST sits beside
    the GET the frontend already calls) — reusing the #557 oracle's token matcher
    so "the entity's endpoint" means exactly what the oracle counted. A by-id GET
    path is reduced to its collection (drop the trailing ``{param}``). Only a
    param-less path is reused (the projected upsert handler takes no path params);
    otherwise derive ``/api/<name kebab>`` from the table name (the projector's
    ``_match_model`` folds ``-``→``_`` so it still resolves the model)."""
    try:
        from .completeness_audit import (
            _entity_tokens, _iter_endpoints, _endpoint_touches, _norm)
    except Exception:
        _entity_tokens = _iter_endpoints = _endpoint_touches = _norm = None
    if _entity_tokens is not None:
        tokens = _entity_tokens(entity)
        for rec in _iter_endpoints(endpoints or {}):
            if _norm(rec.get("method")).upper() != "GET":
                continue
            raw = str(rec.get("path") or "")
            if not _endpoint_touches(raw, tokens):
                continue
            p = _express_to_fastapi(raw).rstrip("/")
            segs = p.split("/")
            if segs and segs[-1].startswith("{"):
                p = "/".join(segs[:-1])
            if p and "{" not in p:   # only a flat collection our handler can serve
                return p
    base = re.sub(r"[^a-z0-9]+", "-", str(entity or "").strip().lower()).strip("-")
    return f"/api/{base}"


def _generate_upsert_handler(method: str, path: str, cls: str, cols: List[str],
                             owner_fk: Optional[str], natural_keys: List[str],
                             auth: bool, idx: int) -> str:
    """Project an idempotent UPSERT handler for a state entity's write path.

    Semantics ("record/update progress"): insert the row, or — when a row already
    exists for the same NATURAL KEY (owner FK + subject FK(s), e.g. profile_id +
    title_id) — UPDATE its mutable columns from the request body. So a repeated
    write for the same (owner, subject) never duplicates and always reflects the
    latest state. Reuses the existing projected-handler patterns: body coercion
    (``_coerce_body``), owner-scoping (``_fw_owner_val`` injects the authenticated
    caller into the owner FK), the ORM model (schema-correct by construction), and
    the same 4xx re-raise / rollback envelope as the generic create handler."""
    path = _sanitize_path_params(path)
    fn = ("_projected_upsert_"
          + re.sub(r"[^a-zA-Z0-9]+", "_", f"{method}_{path}").strip("_").lower()
          + f"_{idx}")
    deps = "db=Depends(get_db)"
    if auth:
        deps += ", user=Depends(get_current_user)"
    sig = f"body: dict = None, {deps}"

    body_lines: List[str] = [
        "    payload = body if isinstance(body, dict) else {}",
        f"    valid = {{k: v for k, v in payload.items() if hasattr({cls}, k)}}",
        # drop unresolved verification-chain placeholders ("${x}" / "{x}") before the
        # ORM write — a literal token into a typed column 500s (mirrors the create path).
        "    valid = {k: v for k, v in valid.items() if not ("
        "isinstance(v, str) and v.endswith(\"}\") and (v.startswith(\"${\") or "
        "(v.startswith(\"{\") and v[1:-1].isidentifier())))}",
        f"    valid = _coerce_body({cls}, valid)",
    ]
    # OWNER-SCOPING: inject the authenticated caller into the owner FK so the row is
    # attributed to (and the natural-key lookup is scoped to) the caller — never trust
    # a client-supplied owner id. (This upsert path OVERRIDES the body owner FK, so it is
    # already safe against the #566s cross-user IDOR — no ownership check needed here.)
    if auth and owner_fk:
        body_lines.append(
            f'    valid["{owner_fk}"] = _fw_owner_val({cls}, "{owner_fk}", user)')

    footer = [
        "        db.commit()",
        "        db.refresh(obj)",
        f"        return {{\"item\": {_serialize_expr('obj', cols)}}}",
        "    except HTTPException:",
        "        raise",
        "    except IntegrityError:",
        "        db.rollback()",
        "        raise",
        "    except DataError:",
        "        db.rollback()",
        "        raise",
        "    except Exception as _exc:",
        "        db.rollback()",
        "        raise HTTPException(status_code=500, detail=f\"upsert failed: {_exc}\")",
    ]

    nk = [k for k in (natural_keys or []) if k]
    if nk:
        # UPSERT by natural key: find the existing (owner, subject...) row, else insert.
        body_lines += [
            "    try:",
            f"        _q = db.query({cls})",
            "        _have_key = True",
            f"        for _nk in {nk!r}:",
            "            _kv = valid.get(_nk)",
            "            if _kv is None:",
            "                _have_key = False",
            "                break",
            f"            _q = _q.filter(getattr({cls}, _nk) == _kv)",
            "        obj = _q.first() if _have_key else None",
            "        if obj is None:",
            f"            obj = {cls}(**valid)",
            "            db.add(obj)",
            "        else:",
            "            for _k, _v in valid.items():",
            "                setattr(obj, _k, _v)",
        ] + footer
    else:
        # No natural key (no FK columns) — a keyless state row: plain create.
        body_lines += [
            "    try:",
            f"        obj = {cls}(**valid)",
            "        db.add(obj)",
        ] + footer

    return (
        f'@app.{method.lower()}("{path}")\n'
        f"def {fn}({sig}):\n"
        + "\n".join(body_lines)
    )


def project_state_write_endpoints(
    backend_dir: Any,
    endpoints: Any,
    tables: Any,
    owner_scoped_tables: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """#556 HEAL: auto-project an idempotent UPSERT write handler into ``main.py``
    for every STATE-BEARING entity that is readable (GET) but has no write
    (POST/PUT/PATCH) — the exact set the #557 oracle flags.

    ``endpoints``: the ``registryhub.get_endpoints()`` map (``{id: rec}``).
    ``tables``:    the ``registryhub.list_tables()`` map (``{name: rec}``).

    Detection is delegated to ``completeness_audit.state_entities_missing_write``
    (the SINGLE source shared with the oracle), so the heal closes precisely what
    the oracle detects. Returns ``{"projected": [...], "endpoints": [descriptor,
    ...]}`` — the caller registers each descriptor in RegistryHub so coverage +
    the frontend see the new write route. Idempotent + best-effort: byte-identical
    when there is nothing to heal (no state entity missing a write) or no ORM model
    backs the entity; never raises.

    REGISTER-ONLY case: when a state entity's write already exists in the CODE
    (lane-authored or a prior projection) but the REGISTRY does not yet know about it,
    NO handler is projected (``projected`` stays empty, ``main.py`` byte-identical) but
    a descriptor IS still emitted (marked ``already_coded``) so the caller registers
    the already-coded write — otherwise heal-then-enforce (#557 R4-core) would
    false-block a feature that works in code merely because its write was unregistered."""
    result: Dict[str, Any] = {"projected": [], "endpoints": []}
    try:
        backend_dir = Path(backend_dir)
        main_py = backend_dir / "main.py"
        if not main_py.exists():
            result["error"] = "main.py absent"
            return result
        from .completeness_audit import state_entities_missing_write
        missing = state_entities_missing_write(tables or {}, endpoints or {})
        if not missing:
            return result  # nothing to heal → main.py untouched (byte-identical)

        src = main_py.read_text(encoding="utf-8")
        existing = _existing_routes(src)
        models = _orm_models(backend_dir)

        projected: List[str] = []
        synthesized: List[Dict[str, Any]] = []
        block_info: List[Tuple[str, str]] = []
        # Deterministic order so the emitted source is stable across runs.
        for i, (entity, state_cols) in enumerate(sorted(missing.items())):
            # Resolve the ORM model (schema-correct handler needs the class + cols).
            meta = models.get(entity)
            if meta is None:
                mm = _match_model(entity, models)
                meta = mm[1] if mm else None
            if not meta or not meta.get("cls"):
                continue  # no ORM model → cannot project a correct write; leave it

            path = _state_write_collection_path(entity, endpoints)
            # A write already routed at this exact path in the CODE (lane-authored, or a
            # prior projection) that the REGISTRY does not yet know about. The #557 oracle
            # + ``missing`` read the REGISTRY, so the write reads as absent there even though
            # the feature works in code. Do NOT project a duplicate handler (main.py stays
            # byte-identical), but STILL emit a descriptor so the caller REGISTERS the
            # already-coded write — otherwise heal-then-enforce (#557 R4-core) would
            # FALSE-BLOCK a working feature merely because its write was never registered.
            coded_write = next((m for m in ("POST", "PUT", "PATCH")
                                if (m, _norm_path(path)) in existing), None)

            cls = meta["cls"]
            m_cols = list(meta.get("cols", []) or [])
            owner_fk = _owner_fk(meta)  # profile_id / user_id / author_id / ...
            fk_cols = _fk_columns(meta)
            subject_fks = [c for c in fk_cols if c != owner_fk]
            natural_keys = ([owner_fk] if owner_fk else []) + subject_fks
            # A write is a mutation → resolve_endpoint_auth returns True; owner
            # injection then scopes the upsert to the caller.
            method = coded_write or "POST"
            auth = resolve_endpoint_auth(method, path, {}, None)

            if coded_write is None:
                handler = _generate_upsert_handler(
                    "POST", path, cls, m_cols, owner_fk, natural_keys, auth, i)
                block_info.append((path, handler))
                projected.append(f"POST {path}")
                existing.add(("POST", _norm_path(path)))
            synthesized.append({
                "method": method,
                "path": path,
                "table": entity,
                "cls": cls,
                "state_columns": list(state_cols),
                "owner_fk": owner_fk,
                "subject_fks": subject_fks,
                "natural_keys": natural_keys,
                "response_key": "item",
                "auth_required": auth,
                # True ⇒ the write already existed in code; we only REGISTER it (no new
                # handler written), so main.py is untouched (byte-identical).
                "already_coded": coded_write is not None,
            })

        if block_info:
            static_blocks = [b for p, b in block_info if "{" not in p]
            param_blocks = [b for p, b in block_info if "{" in p]
            new_src = src
            top = ("# === BY-CONSTRUCTION (#556 state-write heal): upsert write path\n"
                   "# for a state entity that had a GET but no write, + guarded deps.\n"
                   + _PROJECTOR_GUARD
                   + ("\n" + "\n\n\n".join(static_blocks) if static_blocks else ""))
            new_src = _insert_before_first_route(new_src, top)
            if param_blocks:
                new_src = _insert_before_main_guard(
                    new_src,
                    "# === BY-CONSTRUCTION (#556 state-write heal): param write routes.\n"
                    + "\n\n\n".join(param_blocks))
            main_py.write_text(new_src, encoding="utf-8")

        result["projected"] = projected
        result["endpoints"] = synthesized
    except Exception as exc:  # best-effort — never wedge the heal run
        result["error"] = str(exc)
    return result
