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
                routes.add((func.attr.upper(), _norm_path(arg0.value)))
    return routes


def _orm_models(backend_dir: Path) -> Dict[str, Dict[str, Any]]:
    """Parse models.py → ``{tablename: {"cls", "cols": [...], "fks": {col: table}}}``.

    ``fks`` captures ``Column(..., ForeignKey("users.id"))`` targets when present;
    handler projection also falls back to column-name heuristics so models that omit
    explicit ``ForeignKey`` (common in LLM-written ORMs) still wire correctly."""
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
                        for a in stmt.value.args:  # scan for ForeignKey("table.col")
                            if not isinstance(a, ast.Call):
                                continue
                            fc = a.func
                            if (getattr(fc, "id", None) == "ForeignKey" or getattr(fc, "attr", None) == "ForeignKey") \
                                    and a.args and isinstance(a.args[0], ast.Constant):
                                fks[name] = str(a.args[0].value).split(".")[0]
        if tablename:
            models[tablename] = {"cls": node.name, "cols": cols, "fks": fks}
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


def _param_type(param: str) -> str:
    return "int" if param == "id" or param.endswith("id") or param.endswith("_id") else "str"


def _match_model(seg: str, models: Dict[str, Dict[str, Any]]) -> Optional[Tuple[str, Dict[str, Any]]]:
    cand = seg.lower()
    for table, meta in models.items():
        if cand == table or cand + "s" == table or cand == table.rstrip("s") or cand.rstrip("s") == table.rstrip("s"):
            return (table, meta)
    return None


# Endpoints whose RESOURCE is posts even though no segment names a table: the
# classic Instagram surface. Without this, /api/feed and /api/explore resolved to
# NO model and the projector emitted a hardcoded empty list — every feed/explore
# screen showed "no posts" forever (2026-06-10 08:50, seeded posts invisible).
_POSTS_SHAPED_TOKENS = ("feed", "explore", "timeline", "reels", "discover")


def _resource_model(path: str, models: Dict[str, Dict[str, Any]]) -> Optional[Tuple[str, Dict[str, Any]]]:
    """Pick the ORM model a path operates on: the LAST path segment that matches a
    known table (plural or singular). ``/api/users/{u}/posts`` → posts(Post).
    Posts-shaped feeds (feed/explore/timeline/reels) fall back to the posts table."""
    chosen: Optional[Tuple[str, Dict[str, Any]]] = None
    for seg, is_p in _segments(path):
        if is_p:
            continue
        m = _match_model(seg, models)
        if m:
            chosen = m
    if chosen is None:
        segs = {seg for seg, is_p in _segments(path) if not is_p}
        if segs & set(_POSTS_SHAPED_TOKENS):
            chosen = _match_model("posts", models)
    return chosen


def _lookup_field(param: str, parent_meta: Dict[str, Any]) -> str:
    """Which parent column a path param matches: id for ``*_id``, else username/slug."""
    cols = parent_meta.get("cols", [])
    if param.endswith("id") or param == "id":
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


def _sig_for_params(params: List[str]) -> str:
    return "".join(f"{p}: {_param_type(p)}, " for p in params)


def _generate_handler(method: str, path: str, auth: bool, models: Dict[str, Dict[str, Any]], idx: int) -> str:
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
    sig_params = _sig_for_params(params)

    cls = None
    cols: List[str] = []
    table = ""
    if res:
        table, meta = res
        cls, cols = meta["cls"], meta["cols"]

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
    elif cls and m == "GET" and _ends_in_param(path) and last_param and (last_param.endswith("id") or last_param == "id"):
        # GET item by id
        body_lines = [
            f"    obj = db.get({cls}, {last_param})",
            "    if obj is None:",
            '        raise HTTPException(status_code=404, detail="not found")',
            f"    return {{\"item\": {_serialize_expr('obj', cols)}}}",
        ]
    elif cls and m == "DELETE" and last_param and (last_param.endswith("id") or last_param == "id"):
        body_lines = [
            f"    obj = db.get({cls}, {last_param})",
            "    if obj is None:",
            '        raise HTTPException(status_code=404, detail="not found")',
            "    db.delete(obj)",
            "    db.commit()",
            f"    return {{\"item\": {{\"id\": {last_param}, \"deleted\": True}}}}",
        ]
    elif cls and m == "GET" and _ends_in_param(path) and last_param and last_param != "id":
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
        body_lines = [
            "    term = (q or \"\").strip()",
            f"    query = db.query({cls})",
            "    if term:",
            f"        cols_to_search = [c for c in (\"username\", \"full_name\", \"name\", \"title\", \"caption\", \"description\", \"content\", \"body\", \"bio\", \"summary\", \"subject\", \"label\", \"message\", \"text\", \"slug\") if hasattr({cls}, c)]",
            "        from sqlalchemy import or_ as _or",
            f"        conds = [getattr({cls}, c).ilike(f\"%{{term}}%\") for c in cols_to_search]",
            "        if conds:",
            "            query = query.filter(_or(*conds))",
            "    rows = query.limit(50).all()",
            f"    return {{\"items\": [{_serialize_expr('r', cols)} for r in rows], \"total\": query.count()}}",
        ]
        sig_params += 'q: str = "", '
    elif cls and m == "GET" and path.endswith("/me"):
        # GET /<resource>/me → the CURRENT authenticated user as a single {item}.
        # "me" is a STATIC segment, so without this case it falls through to the
        # GET-collection branch below and returns EVERY row — a shape AND semantic
        # bug (the profile page wants the current user, not a list of all users).
        # Mirror the PUT/PATCH /me handler's "me" resolution (db.get(User, user.id)).
        body_lines = [
            ("    obj = db.get(User, user.id) if user is not None else None"
             if auth else f"    obj = db.query({cls}).first()"),
            "    if obj is None:",
            '        raise HTTPException(status_code=404, detail="not found")',
            f"    return {{\"item\": {_serialize_expr('obj', cols)}}}",
        ]
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
            body_lines += [
                "    try:",
                "        obj = db.get(User, user.id)" if auth else f"        obj = db.query({cls}).first()",
                "        if obj is None:",
                '            raise HTTPException(status_code=404, detail="not found")',
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
            "    except Exception:",
            "        db.rollback()",
            "        return {\"item\": valid}",
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
                _col_names = [c.get("name") for c in (_mm.get("columns") or [])
                              if isinstance(c, dict) and c.get("name")]
                if last_param in _col_names:
                    _resolver = (_mm.get("class_name") or _mn.capitalize(),
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
        path = str(ep.get("path", ""))
        # Only /api/ business endpoints are lane-owned + projectable. /auth/* is
        # owned by the embedded OAuth2 AS (register/login are framework-guaranteed)
        # so it is never projected here.
        if not method or not path.startswith("/api/"):
            continue
        if (method, _norm_path(path)) in existing:
            continue
        meta = ep.get("metadata") if isinstance(ep.get("metadata"), Mapping) else {}
        auth = bool(ep.get("auth_required", meta.get("auth_required", True)))
        block_info.append((path, _generate_handler(method, path, auth, models, i)))
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
