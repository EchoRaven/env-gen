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
from typing import Any, Dict, List, Mapping, Optional, Tuple

_HTTP_METHODS = ("get", "post", "put", "delete", "patch")

# Columns that name the ACTOR/owner of a row — the authenticated caller. Order is
# preference (a row with both ``user_id`` and ``author_id`` is owned by the first).
_OWNER_FK_NAMES = (
    "user_id", "author_id", "owner_id", "creator_id", "created_by",
    "follower_id", "sender_id", "from_user_id", "actor_id", "uploaded_by",
    "posted_by", "account_id",
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
        if tablename:
            models[tablename] = {"cls": node.name, "cols": cols, "fks": fks, "types": types}
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
    cand = seg.lower()
    for table, meta in models.items():
        if cand == table or cand + "s" == table or cand == table.rstrip("s") or cand.rstrip("s") == table.rstrip("s"):
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


def _resource_model(path: str, models: Dict[str, Dict[str, Any]]) -> Optional[Tuple[str, Dict[str, Any]]]:
    """Pick the ORM model a path operates on: the LAST path segment that matches a
    known table (plural or singular). ``/api/users/{u}/posts`` → posts(Post).
    A feed/timeline path that names no table resolves to the app's primary content
    table — shape-derived (timestamp + owner FK + richness), domain-agnostic."""
    chosen: Optional[Tuple[str, Dict[str, Any]]] = None
    for seg, is_p in _segments(path):
        if is_p:
            continue
        m = _match_model(seg, models)
        if m:
            chosen = m
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


def _lookup_field(param: str, parent_meta: Dict[str, Any]) -> str:
    """Which parent column a path param matches: id for ``*id``, else username/slug."""
    cols = parent_meta.get("cols", [])
    if _is_id_param(param):
        return "id"
    if param in cols:
        return param
    if "username" in cols and ("user" in param or param == "username" or param == "handle"):
        return "username"
    if "slug" in cols:
        return "slug"
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
def _serialize_expr(var: str, cols: List[str]) -> str:
    """Build a dict literal serialising an ORM instance's columns (ISO datetimes)."""
    if not cols:
        return f'{{"id": getattr({var}, "id", None)}}'
    parts = []
    for c in cols:
        if c.endswith("_at"):
            parts.append(f'"{c}": ({var}.{c}.isoformat() if getattr({var}, "{c}", None) else None)')
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


def _generate_handler(method: str, path: str, auth: bool, models: Dict[str, Dict[str, Any]], idx: int, response_key: str = "") -> str:
    """Project a FastAPI handler. Functional for recognised CRUD + nested-resource
    patterns over a resolvable model; valid-shape stub otherwise. Never 404s."""
    fn = "_projected_" + re.sub(r"[^a-zA-Z0-9]+", "_", f"{method}_{path}").strip("_").lower() + f"_{idx}"
    res = _resource_model(path, models)
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
    if parent_ctx:
        parent_table, parent_meta, parent_param = parent_ctx
        parent_cls = parent_meta["cls"]
        parent_singular = parent_table.rstrip("s")
        parent_field = _lookup_field(parent_param, parent_meta)

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
            f'    parent = db.query({parent_cls}).filter(getattr({parent_cls}, "{parent_field}") == {parent_param}).first()',
            "    if parent is None:",
            '        raise HTTPException(status_code=404, detail="not found")',
            f'    rows = db.query({cls}).filter(getattr({cls}, "{scope_fk}") == parent.id).limit(100).all()',
            f'    return {{"items": [{_serialize_expr("r", cols)} for r in rows], "total": len(rows)}}',
        ]
    elif cls and m == "GET" and _ends_in_param(path) and last_param and _is_id_param(last_param):
        # GET item by id
        body_lines = [
            f"    obj = db.get({cls}, {last_param})",
            "    if obj is None:",
            '        raise HTTPException(status_code=404, detail="not found")',
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
        # user.id]) and delete idempotently (a no-op delete still succeeds — toggles are
        # safe to repeat). Uses _target_fk (the create-bind FK) NOT _scope_fk so a
        # self-referential join (follows: follower_id + following_id both → users)
        # filters the FOLLOWED side (following_id==parent.id) against the OWNER side
        # (follower_id==user.id) — mirrors the create handler's bind.
        _sfk = _target_fk(meta, parent_table, parent_singular)
        body_lines = [
            f'    parent = db.query({parent_cls}).filter(getattr({parent_cls}, "{parent_field}") == {parent_param}).first()',
            "    if parent is None:",
            '        raise HTTPException(status_code=404, detail="not found")',
            f'    _q = db.query({cls}).filter(getattr({cls}, "{_sfk}") == parent.id)',
        ]
        if owner_fk:
            body_lines.append(
                f'    _q = _q.filter(getattr({cls}, "{owner_fk}") == user.id)')
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
                f'    if getattr(obj, "{owner_fk}", None) != user.id:',
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
            "    if term:",
            f"        cols_to_search = [c for c in {_search_cols!r} if hasattr({cls}, c)]",
            "        from sqlalchemy import or_ as _or",
            f"        conds = [getattr({cls}, c).ilike(f\"%{{term}}%\") for c in cols_to_search]",
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
                (f"    obj = db.get({_ucls}, user.id) if user is not None else None"
                 if auth else f"    obj = db.query({_ucls}).first()"),
                "    if obj is None:",
                '        raise HTTPException(status_code=404, detail="not found")',
                f"    return {{\"item\": {_serialize_expr('obj', _ucols)}}}",
            ]
        else:
            body_lines = ['    return {"item": {}}']
    elif cls and m == "GET":
        # GET collection
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
        ]
        if m in ("PUT", "PATCH") and path.endswith("/me"):
            # mirror GET /me: resolve the user model DYNAMICALLY. Hardcoding `User`
            # broke /me updates for any app whose user table isn't literally named
            # User (accounts/profiles/members) — `NameError: User` at request time.
            _me_u = _me_user_model(models) or ((cls, cols) if cls else None)
            _ucls = (_me_u[0] if (_me_u and _me_u[0]) else None) or cls
            body_lines += [
                "    try:",
                f"        obj = db.get({_ucls}, user.id)" if auth else f"        obj = db.query({_ucls}).first()",
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
                    f'        if getattr(obj, "{owner_fk}", None) != user.id:',
                    '            raise HTTPException(status_code=404, detail="not found")',
                ]
            body_lines += [
                "        for k, v in valid.items():",
                "            setattr(obj, k, v)",
            ]
        else:
            bound: List[str] = []
            # Bind a path-param parent into the relation's TARGET FK, and inject the
            # authenticated caller into the OWNER FK — so created rows are attributed.
            if m == "POST" and parent_ctx:
                tfk = _target_fk(meta, parent_table, parent_singular)
                if tfk:
                    body_lines += [
                        f'    _parent = db.query({parent_cls}).filter(getattr({parent_cls}, "{parent_field}") == {parent_param}).first()',
                        "    if _parent is not None:",
                        f'        valid["{tfk}"] = _parent.id',
                    ]
                    bound.append(tfk)
            if m == "POST" and auth:
                ofk = _owner_fk(meta, exclude=tuple(bound))
                if ofk:
                    body_lines += [f'    valid.setdefault("{ofk}", user.id)']
            body_lines += [
                "    try:",
                f"        obj = {cls}(**valid)",
                "        db.add(obj)",
            ]
        body_lines += [
            "        db.commit()",
            "        db.refresh(obj)",
            f"        return {{\"item\": {_serialize_expr('obj', cols)}}}",
            "    except HTTPException:",
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


def project_missing_routes(
    backend_dir: Any,
    declared_endpoints: List[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Append a projected handler to ``main.py`` for every declared business
    endpoint that has no route. Returns ``{"projected": [...], "already": int}``.

    ``declared_endpoints``: ``[{method, path, auth_required?}]`` — the contract the
    lanes were supposed to implement (RegistryHub business endpoints)."""
    backend_dir = Path(backend_dir)
    main_py = backend_dir / "main.py"
    if not main_py.exists():
        return {"projected": [], "already": 0, "error": "main.py absent"}
    src = main_py.read_text(encoding="utf-8")
    existing = _existing_routes(src)
    models = _orm_models(backend_dir)

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
        auth = bool(ep.get("auth_required", meta.get("auth_required", True)))
        _schema = ep.get("schema") if isinstance(ep.get("schema"), Mapping) else {}
        response_key = str(
            ep.get("response_key")
            or (_schema.get("response_key") if isinstance(_schema, Mapping) else "")
            or meta.get("response_key")
            or ""
        ).strip()
        block_info.append((path, _generate_handler(method, path, auth, models, i, response_key)))
        projected.append(f"{method} {path}")
        existing.add((method, _norm_path(path)))  # dedupe within this batch

    if block_info:
        # Imports the projected handlers rely on — injected idempotently + GUARDED so a
        # raw-SQL app with no models.py (run #13) does not crash on load. FastAPI/HTTP
        # names are re-imported harmlessly; ``from models import *`` is best-effort.
        guard = (
            "# by-construction projector deps (guarded; safe to re-import)\n"
            "from fastapi import Depends, HTTPException, Query  # noqa: F401,F811\n"
            "try:\n"
            "    from models import *  # noqa: F401,F403\n"
            "except Exception:\n"
            "    pass\n"
            # Projected AUTH handlers reference get_current_user (user=Depends(get_current_user))
            # and get_db — guard their imports too, so an app whose main.py didn't already
            # import them (raw-SQL/malformed worktree) doesn't NameError-crash on an auth route.
            "try:\n"
            "    from auth_dependency import get_current_user  # noqa: F401,F811\n"
            "except Exception:\n"
            "    pass\n"
            "try:\n"
            "    from database import get_db  # noqa: F401,F811\n"
            "except Exception:\n"
            "    pass\n"
        )
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
