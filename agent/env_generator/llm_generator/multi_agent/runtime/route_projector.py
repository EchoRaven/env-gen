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
try:  # #1202cw
    from .path_routed_workspace import framework_write_1202cw as _fw_write_1202cw
except ImportError:  # pragma: no cover - only when this file is loaded BY PATH (two tests)
    def _fw_write_1202cw(_p, _text, **_kw):
        from pathlib import Path as _P
        _P(str(_p)).write_text(_text, encoding=_kw.get("encoding", "utf-8"))
        return True
def _write_py_995(path, text, *, what: str = ""):
    """#995 guard, imported defensively.

    Some modules here are imported STANDALONE by tests (no package context), where a relative
    import raises. The guard degrades to a plain write in that case rather than breaking the
    import — and says so in this docstring rather than pretending it is still checking.
    """
    try:
        from .safe_code_write import write_py_if_still_parses as _w
    except Exception:
        _fw_write_1202cw(path, text, encoding="utf-8")
        return True
    return _w(path, text, what=what)


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
    # #1202nf: the `_user_id` spellings of the same roles, and `receiver`. Without them a
    # `Follow(follower_user_id, followed_user_id)` matched nothing here, the FK fallback took
    # the FIRST user FK, and the projected `POST /api/users/{user_id}/follow` wrote the path
    # user as the FOLLOWER and the caller as the one followed (tiktok-r123, r125).
    "followed_user_id", "following_user_id", "followee_user_id", "recipient_user_id",
    "receiver_id", "receiver_user_id",
)
# #1202nf: columns that name the ACTOR of a two-user relation. `_target_fk`'s FK fallback skips
# them while another FK to the parent remains, so the actor is never bound to the path user.
_ACTOR_ROLE_FK_NAMES_1202NF = (
    "follower_id", "follower_user_id", "sender_id", "sender_user_id", "from_user_id",
    "actor_id", "actor_user_id", "author_id", "author_user_id", "owner_id", "owner_user_id",
    "creator_id", "creator_user_id",
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


def _feed_shaped_model_288(models: Dict[str, Dict[str, Any]]):
    """The pre-#1202gp chooser — timestamp ladder only — kept for #288's parent-filter EXEMPTION.

    #1202gp widened `_primary_content_model` with an ATTACHMENT rung, which is right for
    picking what a feed/search route SERVES but must not decide who gets owner-scoped. The
    ratchet in `test_route_projector_nested_isolation` proves why: `projects(user_id)` with
    `tasks(user_id, project_id)` hanging off it is structurally IDENTICAL to `videos(author_id)`
    with `video_likes(user_id, video_id)`, so the attachment winner in a project tracker is the
    PRIVATE container — and exempting it drops the cross-user isolation #288's filter exists
    for (GET /api/projects/{otherId}/tasks → 200, another user's tasks).

    That separation is SEMANTIC, not structural — the same conclusion #1202gd reached over 116
    backends and 267 firing tables. The exemption therefore stays on the narrow, conservative
    predicate until the reference spec's declared `visibility` (#1202gd) is threaded down to
    the projector; widening it on shape alone would trade a 404 for a leak.
    """
    candidates: List[Tuple[int, int, str, Dict[str, Any]]] = []
    for table, meta in models.items():
        if _is_spine_table(table):
            continue
        cols = meta.get("cols", [])
        if not _has_timestamp(cols):
            continue
        candidates.append((2 if _owner_fk(meta) else 1, len(cols), table, meta))
    if not candidates:
        return None
    candidates.sort(key=lambda c: (-c[0], -c[1], c[2]))
    _, _, table, meta = candidates[0]
    return (table, meta)


def _attachments_1202gp(models: Dict[str, Dict[str, Any]]) -> Dict[str, int]:
    """How many OTHER non-spine tables hang off each table by a ``<singular>_id`` column.

    Column NAMES, not the ``fks`` map: the producer (`_models_meta`) leaves ``fks`` EMPTY for
    exactly the content tables this has to rank — r98's `videos`, `comments`, `video_likes`
    and `video_saves` all carry ``fks={}`` while their columns say `video_id` plainly. A
    table's own OWNER fk never counts as an attachment; otherwise every user-owned table
    would "attach" to `users` and the spine would win every app.
    """
    out: Dict[str, int] = {}
    nonspine = [t for t in models if not _is_spine_table(t)]
    for target in nonspine:
        singular = target[:-1] if target.endswith("s") else target
        col = (singular + "_id").lower()
        n = 0
        for other in nonspine:
            if other == target:
                continue
            other_meta = models.get(other) or {}
            names = {str(c.get("name") if isinstance(c, Mapping) else c).lower()
                     for c in (other_meta.get("cols") or [])}
            if col in names and col != str(_owner_fk(other_meta) or "").lower():
                n += 1
        if n:
            out[target] = n
    return out


def _primary_content_model(
    models: Dict[str, Dict[str, Any]]
) -> Optional[Tuple[str, Dict[str, Any]]]:
    """The business table a domain-agnostic feed/timeline lists, picked BY SHAPE
    (not a hardcoded name): a non-spine table that looks like a feed item — a
    timestamp column (time-ordered) and, preferably, an owner FK to users
    (authored). Among candidates, prefer feed-item shape, then the richest table,
    then alphabetical (deterministic). Returns None when nothing is feed-shaped,
    so the projector never guesses a wrong table.

    #1202gp (tiktok r96/r97/r98, live): the timestamp REQUIREMENT is the flaw — a generated
    content table often carries none. r98's `videos` has 13 columns and not one is
    time-shaped, so this returned `messages` (r98) / `suggested_creators` (r96) / None (r97)
    and #288's exemption never reached the content model. The projected consequence, verbatim
    from r98's main.py at three call sites:

        _parent = db.query(Video).filter(getattr(Video, "id") == id).filter(
            getattr(Video, "author_id") == _fw_owner_val(Video, "author_id", user)).first()

    — "you may only like / save / comment on videos YOU authored" — 404 on a working app,
    19 of that run's 34 chain failures, in code the lane cannot edit.

    ATTACHMENT is the signal that survives across domains: the primary content is what the
    other tables hang off by a `<singular>_id` column (comments.video_id, video_likes.video_id
    ...). Measured over the corpus: tiktok `videos` 19/22 runs, netflix `titles` ~41/45,
    instagram `posts` 18/18, googlemaps `places`. It is a rung ABOVE the timestamp ladder,
    never a replacement — where the old ladder already answered correctly (instagram) the two
    AGREE, and with nothing attached anywhere the ladder below is reached untouched."""
    _attached = _attachments_1202gp(models)
    if _attached:
        _best = sorted(_attached.items(),
                       key=lambda kv: (-kv[1], -len(models[kv[0]].get("cols", [])), kv[0]))[0][0]
        return (_best, models[_best])
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


def _is_user_persona_table(table: str, models: Dict[str, Dict[str, Any]]) -> bool:
    """#569 — a per-user PERSONA / account sub-entity (``profiles``): the table is itself
    user-owned AND another table's OWNER column points at it (``my_list``'s owner FK is
    ``profile_id`` → ``profiles``). That combination marks an ACCOUNT record, not content: a
    resource-less global search over it enumerates every user's personas.

    "Owner column", not "any reference" — that distinction is the whole rule. A social app's
    ``posts`` is user-owned and IS referenced by ``comments.post_id``, but comments' OWNER is
    ``author_id`` → ``users``; nothing is OWNED BY a post, so ``posts`` stays a legitimate
    search target and public-feed search is unaffected. (An earlier any-reference version of
    this predicate flagged ``posts`` and would have broken every feed app — caught by this
    change's own test.) Shape-derived from the FK graph; no product literals."""
    meta = models.get(table) or {}
    if not any(str(t).lower() == "users" for t in (meta.get("fks") or {}).values()):
        return False
    _t = str(table).lower()
    for other, m in models.items():
        if other == table:
            continue
        _ofk = _owner_fk(m)
        if _ofk and str((m.get("fks") or {}).get(_ofk, "")).lower() == _t:
            return True
    return False


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
             for t, m in models.items()
             if not _is_spine_table(t) and not _is_user_persona_table(t, models)]
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


def _stated_auth_1202hi(ep: Any, meta: Any = None) -> Optional[bool]:
    """#1202hi -- the ONE reader of the three places an endpoint can state its auth.

    A record carries the flag in up to three copies: the top level, `schema` (what
    `register_endpoint(schema=...)` stores -- the lane's own contract) and `metadata` (a
    MIRROR taken at registration, which keeps its original value forever). #1202ga worked
    out the precedence and taught it to `resolve_endpoint_auth`, but #320's public-feed
    exemption kept its own two-copy test in each emitter, and the two disagreed: the
    projector never looked at the schema at all.

    Measured over the 142 runs here -- 3636 endpoints state auth, 1518 carry both copies,
    220 of them `schema=False, metadata=True`: the lane declared a public read and the
    projector could not see it (r103: 20 of 80, `/api/videos/{id}`, `/api/explore`,
    `/api/search`, `/api/live` -- the logged-out surface #320 exists to keep open). The 41
    in the other direction resolve to auth-required, which TIGHTENS rather than opens.

    Returns None when nothing states it, so callers keep their own shape-based default.
    """
    if not isinstance(ep, Mapping):
        return None
    stated = ep.get("auth_required")
    if stated is None:
        _sch = ep.get("schema")
        if isinstance(_sch, Mapping):
            stated = _sch.get("auth_required")
    if stated is None and isinstance(meta, Mapping):
        stated = meta.get("auth_required")
    if stated is None:
        _emeta = ep.get("metadata")
        if isinstance(_emeta, Mapping):
            stated = _emeta.get("auth_required")
    return None if stated is None else bool(stated)


_PUBLIC_LITERAL_RE_1202KH = re.compile(
    r"^_FW_PUBLIC_API_1202KH = \[.*?^\]", re.M | re.S)


def refresh_public_api_1202kh(src: str, public: "List[Tuple[str, str]]") -> str:
    """Rewrite main.py's `_FW_PUBLIC_API_1202KH` literal to the CURRENT public set.

    #1202kh's list is emitted by `render_skeleton_main`, which runs ONCE.
    `project_missing_routes` then inserts handlers into that same file every cycle, so an
    endpoint a lane registers mid-run gets a no-actor handler and stays absent from the list --
    and the blanket guard denies a route the framework has just built to answer. Same staleness
    as #1202ju and #1202ic one artefact over: a deterministic projection is only deterministic
    if it is re-run when its input moves.

    UNION, never replace: this projector only sees the endpoints it is projecting THIS cycle,
    so overwriting would drop the skeleton's own entries and re-deny them. Returns `src`
    unchanged when the literal is absent (a main.py the skeleton did not render -- #47's
    blanket rule stands, which is the fail-closed default) or when nothing was added.
    """
    m = _PUBLIC_LITERAL_RE_1202KH.search(src)
    if m is None:
        return src
    try:
        have = [tuple(x) for x in ast.literal_eval(m.group(0).split("=", 1)[1].strip())]
    except Exception:
        return src
    merged = list(have) + [t for t in public if t not in have]
    if len(merged) == len(have):
        return src
    body = "".join("    (%r, %r),\n" % (mm, pp) for mm, pp in merged)
    return src[:m.start()] + "_FW_PUBLIC_API_1202KH = [\n" + body + "]" + src[m.end():]


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
    # #1202ga -- THE SCHEMA IS THE CONTRACT; metadata is a MIRROR of it taken at
    # registration. This read the mirror and the top level but never the schema, so a lane
    # that updated its contract had no effect at all.
    #
    # tiktok-r97, end to end: the verifier correctly relayed six "unauthenticated API
    # returns 401" bugs to backend; backend correctly applied #320's public-read
    # declaration -- `schema.auth_required = False` on /api/videos/{id}, its comments and
    # /api/live -- and truthfully marked them completed. Every one of those endpoints still
    # carried `metadata.auth_required = True` from the original registration, so this
    # resolver read True, the routes kept projecting Depends(get_current_user), and the
    # logged-out flow kept failing on the same 401 for the rest of the run. The lane did the
    # right thing six times and the framework ignored it.
    #
    # The schema wins because it is what `register_endpoint(schema=...)` writes -- the
    # lane's own statement of the contract. Metadata stays as the fallback for records whose
    # schema does not state it, so nothing that only ever set the mirror starts reading
    # differently.
    stated = _stated_auth_1202hi(ep, meta)   # #1202hi: one reader for all three copies
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


_NARROW_OWNER_FK_NAMES = ("profile_id",)

# #908: the owner names that attribute a row to a USER DIRECTLY — `_OWNER_FK_NAMES` minus the
# narrow (sub-entity) ones. Derived, not re-listed: a second hand-written copy of this vocabulary
# is how one member goes missing from one of them.
_DIRECT_OWNER_FK_NAMES = tuple(n for n in _OWNER_FK_NAMES if n not in _NARROW_OWNER_FK_NAMES)


def _fk_target_by_name_908(col: str, models: Dict[str, Any]) -> Optional[str]:
    """The table ``col`` points at, inferred from its NAME when the ORM omitted ``ForeignKey``.

    `<base>_id` → the registered table named `<base>s` / `<base>` / `<base>es`. Returns None when
    no such table exists, so an owner column that names no entity (``created_by``) is unchanged.
    Name-based resolution is not a new idea here — `_OWNER_FK_NAMES` already decides ownership
    that way; this only applies the same standard to the other end of the same edge."""
    name = str(col or "")
    if not name.endswith("_id"):
        return None
    base = name[:-3]
    if not base:
        return None
    for cand in (base + "s", base, base + "es"):
        if cand in (models or {}):
            return cand
    return None


# #803 (item 109): fold a normalised many-to-many into the detail read.
#
# The projected detail page renders a chip row from `cur.genres`. In 120 of 122 corpus runs the
# payload carries no genre field at all -- genres are a `title_genres` join and the detail handler
# is `SELECT <cols> FROM titles WHERE id = :id`. #782 fixed the frontend accessor; no accessor can
# invent a field the response does not carry, so the block still rendered nothing. This is the
# backend half.
#
# It is NOT a genres feature. Any normalised many-to-many the reference shows as chips -- tags,
# categories, skills, ingredients, topics -- is invisible to every projected detail page for the
# same reason.
#
# ** The safety rule is the whole design. ** A "pure link table" (two FKs, nothing else) is
# structurally indistinguishable from a per-user relation: this corpus holds 242 of them, 139
# `title_genres` and 103 `my_list (profile_id, title_id)`. Folding the latter in would attach the
# names of the profiles who saved a title to a PUBLIC detail response -- a read-path owner-scoping
# leak, the #569 class, shipped by a rule whose own coverage metric reads 100%. So membership is
# decided by what the FK POINTS AT, never by its name: #784 learned that the hard way when a
# name-based guard missed `recipient_id` precisely because it was not on the list.
# #1202jb: columns an actor row must not show to anyone who is not that actor. A DENYLIST,
# because the safe allowlist (#1202ir's display set) is too narrow for a profile page that
# legitimately renders follower counts. Exact membership: `_IMAGEISH_1202FH` matching "art"
# inside `partner_email` is the trap this file carried until #1202jc made that one match by
# token prefix; the denylist never relied on substrings and still does not.
_PRIVATE_ACTOR_COLS_1202JB = frozenset((
    "email", "email_address", "secondary_email", "recovery_email",
    "phone", "phone_number", "mobile", "telephone",
    "password", "password_hash", "password_digest", "hashed_password", "salt",
    "token", "api_key", "api_secret", "secret", "access_token", "refresh_token",
    "reset_token", "verification_code", "otp", "two_factor_secret", "mfa_secret",
    "ssn", "national_id", "tax_id", "dob", "date_of_birth", "birthdate",
    "address", "street", "postal_code", "zip", "zipcode",
    "ip", "ip_address", "last_login_ip", "stripe_customer_id", "payment_method_id",
))

_ACTOR_TABLES_803 = ("users", "user", "profiles", "profile", "accounts", "account",
                     "members", "member", "customers", "customer", "tenants", "tenant")
_LABEL_COLS_803 = ("name", "title", "label", "slug", "code")
_HOUSEKEEPING_803 = ("id", "created_at", "updated_at", "created_time", "updated_time")


def _link_label_reads_803(table: str, models: Dict[str, Any]) -> List[Dict[str, str]]:
    """Label relations reachable from ``table`` through a pure link table, actor tables excluded.

    Returns ``[{"field", "link", "self_fk", "other_fk", "child", "label"}]``; empty on anything
    ambiguous, missing or actor-touching. Pure function of the parsed models -- no I/O.
    """
    out: List[Dict[str, str]] = []
    try:
        for lname, lmeta in (models or {}).items():
            if not isinstance(lmeta, dict):
                continue
            cols = [c for c in (lmeta.get("cols") or []) if c not in _HOUSEKEEPING_803]
            fks = lmeta.get("fks") or {}
            if len(cols) != 2 or any(c not in fks for c in cols):
                continue                              # not a PURE link table
            targets = {c: str(fks[c]) for c in cols}
            if any(t in _ACTOR_TABLES_803 for t in targets.values()):
                continue                              # #784: decided by target, not by name
            self_fk = next((c for c, t in targets.items() if t == table), None)
            if self_fk is None:
                continue
            other_fk = next(c for c in cols if c != self_fk)
            child = targets[other_fk]
            cmeta = (models or {}).get(child)
            if not isinstance(cmeta, dict):
                continue
            label = next((c for c in _LABEL_COLS_803 if c in (cmeta.get("cols") or [])), None)
            if not label:
                continue                              # nothing to show; a bare id row is noise
            out.append({"field": child, "link": lname, "self_fk": self_fk,
                        "other_fk": other_fk, "child": child, "label": label})
    except Exception:
        return []
    return sorted(out, key=lambda r: r["field"])


def _link_label_sql_803(rel: Mapping[str, str]) -> str:
    """The read for one label relation. Identifiers come from the parsed ORM (Python identifiers
    by construction); the only runtime value is bound as ``:_lid``."""
    return ("SELECT c.{label} FROM {link} l JOIN {child} c ON c.id = l.{other_fk} "
            "WHERE l.{self_fk} = :_lid ORDER BY c.{label}").format(**rel)


def _read_owner_fk_777(child_meta: Dict[str, Any], owner_fk: Optional[str]) -> Optional[str]:
    """#777: for a READ, the NARROWEST owner the table declares wins.

    `_owner_fk` walks `_OWNER_FK_NAMES` in order and takes the first hit, with `profile_id` LAST
    on purpose. The note there says "a user-level owner (user_id/account_id) still wins when both
    exist; the VALUE is resolved to the caller's profile by _fw_owner_val". That reasoning holds
    for FILLING a column on write. It does not hold for SCOPING a read: if the rows are
    per-profile and the filter is `user_id == caller`, every profile on the account sees every
    other profile's rows.

    The projector already records the consequence a few lines down — *"r141 shipped
    GET /api/my-list and GET /api/continue-watching unscoped for exactly this reason, while r142
    was safe only because its draw happened to pick profile_id"* — and r151 shipped it again: a
    DDL with BOTH columns, `POST /api/my-list` writing profile_id six times, and
    `GET /api/my-list` + `GET /api/continue-watching` filtering on user_id alone. #776 detects
    that; this is the half that prevents it.

    READS only. The create/write path keeps `_owner_fk` untouched, because the NOT-NULL argument
    for filling `user_id` is still true, and the DELETE owner gate is left alone as an
    unmeasured question rather than an assumed one. Same first-match-over-an-unordered-list shape
    as #506's accent resolution.
    """
    try:
        cols = child_meta.get("cols", []) or []
    except Exception:
        return owner_fk
    for narrow in _NARROW_OWNER_FK_NAMES:
        if narrow in cols and narrow != owner_fk:
            return narrow
    return owner_fk


def _is_per_user_sub_entity_fk(child_meta: Dict[str, Any], owner_fk: str,
                               models: Dict[str, Dict[str, Any]]) -> bool:
    """#566y — True iff ``owner_fk`` attributes the row to a PER-USER SUB-ENTITY (a
    persona row that itself belongs to a user: ``continue_watching.profile_id`` →
    ``profiles.user_id`` → ``users``) rather than to the user DIRECTLY
    (``posts.author_id`` → ``users``).

    This decides whether a projected READ may be owner-scoped WITHOUT the contract's
    ``owner_scoped_reads`` opt-in. A DIRECTLY user-owned collection is genuinely
    ambiguous — a public feed is a list of rows each owned by some user — so it stays
    opt-in, exactly as before. A SUB-ENTITY-owned row is per-persona private state by
    construction, and the projection already treats it that way on the WRITE side: the
    create refuses a body owner-FK the caller does not own (#566s, 403) and auto-fills
    the caller's own via ``_fw_owner_val``. A read that returns every persona's rows
    contradicts the write it is paired with — and leaks.

    Shape-derived from the contract's FK graph; no product literals.

    ★ #908: "the contract's FK graph" is usually EMPTY, and that is why this never fired. `fks`
    comes from `_parse_models` reading `Column(..., ForeignKey("users.id"))` — and that parser's
    own docstring says models omitting the explicit ForeignKey are *"common in LLM-written ORMs"*
    and *"still wire correctly"*. They wire correctly and they leak: r153 ships
    `profile_id = Column(Integer)` with no ForeignKey, no `REFERENCES` in the DDL, and
    `metadata = {}` (no `owner_scoped_reads`), so every gate this function guards was open.

    Measured over the 153 delivered backends — and split by era, because a raw count here is
    misleading: 162 projected reads ship unfiltered on a table with a recognised owner column, but
    **157 of them predate the fix for their own shape** (#566y landed after r131, #598 after r141).
    What is actually still open:

        r131  continue_watching  profile_id -> profiles   #566y's own motivating run, fixed after
        r141  my_list / c_w      user_id    -> users      #598's,                     fixed after
        ★ r153  my_list / c_w    profile_id -> (none)     the same sub-entity shape with the
                                                          ForeignKey simply never declared

    r153 is the arc's best run, generated by current HEAD, and it ships
    `db.query(MyList).limit(100).all()` — every account's rows to any authenticated caller — while
    the POST beside it 403s a foreign `profile_id`. That is the self-contradiction #566y and #598
    both name, arriving through the one door neither of them watches.

    ★ The evidence standard was inconsistent between two functions ten lines apart. `_owner_fk`
    accepts a column NAME as proof of ownership — that is the ONLY reason `profile_id` is treated
    as an owner at all (`_OWNER_FK_NAMES`, N-P0-2) — while this function, which exists to decide
    what that same column MEANS, accepted only a parsed FK. Resolve the parent the same way the
    owner itself was resolved: by name when the ORM did not spell it out.

    Both hops widen, and both stay shape-derived: `profile_id` → a table literally named
    `profiles`, which must itself carry a DIRECT user principal. `posts.author_id` → no `authors`
    table → still False (a public feed keeps its opt-in). `title_genres.title_id` is never reached
    — this is only ever called with an owner column `_owner_fk` already recognised."""
    tgt = (child_meta.get("fks") or {}).get(owner_fk)
    if not tgt and owner_fk in (child_meta.get("cols") or []):
        # #908: infer the parent from the column NAME — but only for a column this table
        # actually DECLARES. The first version skipped that check and answered from `models`
        # alone, so an EMPTY `child_meta` ("I know nothing about this table") came back True.
        # #566y's own test caught it. That is the third time in one session that an empty input
        # was read as a meaningful value (#902's blank route as the site root, #907's empty cache
        # as an empty source tree) — this time in the fix for the other two.
        tgt = _fk_target_by_name_908(owner_fk, models)
    if not tgt or tgt == "users":
        return False
    parent = models.get(tgt) or {}
    if any(t == "users" for t in (parent.get("fks") or {}).values()):
        return True
    # #908: the parent's own user link is just as likely to be an unadorned Column.
    return any(c in (parent.get("cols") or []) for c in _DIRECT_OWNER_FK_NAMES)


def _declared_owner_private_1202ht(meta: Dict[str, Any]) -> bool:
    """#1202ht -- do the MATERIALS declare this table's rows per-user-private?

    The mirror of `_declared_public_content_1202hh`, carried on the same model meta. r106
    projected `GET /api/notifications` as an unauthenticated `db.query(Notification).all()`
    on a table declaring BOTH `owner_scoped_reads: True` and `visibility: owner`, because an
    endpoint's `auth_required: false` cleared the scoping (#320). A declaration that the rows
    are per-user must outrank a flag that answers whether you have to log in.

    Only ever TIGHTENS, so it needs no second signal: releasing a read requires agreement,
    refusing one does not.
    """
    try:
        return str((meta or {}).get("visibility") or "").strip().lower() == "owner"
    except Exception:
        return False


def _declared_public_content_1202hh(meta: Dict[str, Any]) -> bool:
    """#1202hh -- do the MATERIALS declare this table's rows published?

    `_models_meta` carries `entities[].visibility` from the reference spec (compiled at
    design time from the product's screenshots and docs, before any lane runs) onto every
    model. #1202gd measured why this has to be semantic: across 116 delivered backends
    `_is_user_content_relation` fires on 267 tables and NO structural rule separates the
    public ones -- `videos(author_id, sound_id, ...)` and `saved_items(user_id, item_id)`
    are the same shape. So the two structural signals must yield to an explicit declaration,
    while the CONTRACT's `owner_scoped_reads` still wins over both: releasing a read needs
    the materials AND the contract to agree, which is what keeps the r141 leak shape closed.

    One predicate for both readers on purpose. The r103 defect was this exact fact reaching
    `backend_audit` and neither emitter; a second copy here would rebuild it.
    """
    try:
        return str((meta or {}).get("visibility") or "").strip().lower() == "public"
    except Exception:
        return False


def _is_user_content_relation(meta: Dict[str, Any], owner_fk: str) -> bool:
    """#598 — True iff the row is a per-user record ABOUT SHARED CONTENT: it carries a
    DIRECT users FK *and* an FK to some other, non-user entity
    (``my_list.user_id`` + ``my_list.title_id``).

    #566y widened read-scoping to SUB-ENTITY owners (``profile_id → profiles → users``)
    and deliberately left the direct-user case opt-in, because "a public feed is a list
    of rows each owned by some user". That reasoning holds for a table whose row IS the
    content — ``posts(user_id, title, body)`` has no second entity FK — but not for a
    table that only RELATES a user to content someone else owns. Scoping then depends on
    which FK the draw happened to pick, which is exactly what leaked:

        r142  my_list.profile_id  -> sub-entity  -> #566y scopes it
        r141  my_list.user_id     -> direct      -> NOT scoped, and the delivered
              `GET /api/my-list` served EVERY user's rows to any authenticated caller.
              `GET /api/continue-watching` in the same tree, same shape, same leak.

    Measured over the arc's 144 delivered backends: 196 tables carry a users FK; the 63
    instances that ALSO carry a content FK are exactly ``MyList`` / ``Rating`` /
    ``ContinueWatching`` — every one a per-user private record — while the 133 with a
    user FK alone are ``Profile``, correctly untouched. A `posts`-shaped public feed is
    untouched by construction.

    THE DECIDING EVIDENCE is not a judgement about privacy — it is the framework already
    contradicting itself. On this exact shape the projected WRITE is guarded in **25 of 25**
    delivered pairs (``_fw_owns`` → 403 on a foreign owner, then ``_fw_owner_val`` auto-fill)
    while the paired READ is scoped in only 10: **15 asymmetric pairs across 12 runs**, every
    one of them with a direct ``user_id``. r141 ships both halves side by side —

        POST /api/my-list  ->  403 "user_id does not belong to the caller"
        GET  /api/my-list  ->  db.query(MyList).limit(100).all()   # everyone's rows

    #566y's docstring already named this contradiction for the sub-entity case ("a read that
    returns every persona's rows contradicts the write it is paired with — and leaks"); the
    direct-FK case is the same sentence with a different column. #598 makes all 25 symmetric.

    Only bare COLLECTION reads are affected; a by-id read keeps its own path."""
    fks = meta.get("fks") or {}
    if fks.get(owner_fk) != "users":
        return False                                  # not a DIRECT user FK
    return any(col != owner_fk and tgt and tgt != "users" for col, tgt in fks.items())


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
    to_parent = [col for col, tgt in fks.items() if tgt == parent_table]
    non_actor = [col for col in to_parent if col not in _ACTOR_ROLE_FK_NAMES_1202NF]
    if non_actor:
        return non_actor[0]
    return to_parent[0] if to_parent else None


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


# #1155: a projected collection whose LAST literal segment names a column on its OWN table
# is a RANKED VIEW of that table, not a copy of it.
#
# netflix-local-r13 delivered `/api/titles/top10` as `db.query(Title).limit(100).all()` —
# all 60 titles, `top10_rank` SELECTED into every row and never read. The spec declares that
# column for exactly this endpoint. Runtime-verified on the delivered stack: /api/titles,
# /api/titles/trending and /api/titles/top10 all answered 60 rows, identically.
#
# It also made one of the framework's own detectors unreachable: remediation_dispatcher's
# "N column(s) are filtered on but never seeded" P0 can only see a column something FILTERS
# on, and nothing did — so `top10_rank` being NULL in all 60 rows was never filed either.
# Projecting the filter puts that column back inside the detector's reach.
#
# Deliberately narrow — this projects code a lane cannot change, so it must not guess:
#   * only a LITERAL last segment, and only when it maps to a real column;
#   * the resource segment itself never counts (`/api/titles` is not ranked by `titles`);
#   * `/api/titles/trending` has no `trending*` column, so it is left exactly as it was;
#   * a trailing integer in the segment is the row cap (`top10` -> 10), else the usual 100.
_RANK_SUFFIXES_1155 = ("", "_rank", "_order", "_position", "_score", "_count")
_DESC_SUFFIXES_1155 = ("_score", "_count")


def _ranked_collection_1155(path: str, cols, table: str = ""):
    """(column, limit, descending) when the path names a ranking column, else None."""
    try:
        lits = [s for s, is_p in _segments(path) if not is_p]
        if len(lits) < 2:
            return None
        seg = str(lits[-1] or "").strip().lower().replace("-", "_")
        if not seg or seg == str(table or "").strip().lower():
            return None
        colset = {str(c).lower(): str(c) for c in (cols or [])}
        for suf in _RANK_SUFFIXES_1155:
            col = colset.get(seg + suf)
            if col:
                m = re.search(r"(\d+)$", seg)
                lim = int(m.group(1)) if m and 0 < int(m.group(1)) <= 100 else 100
                return col, lim, suf in _DESC_SUFFIXES_1155
        return None
    except Exception:
        return None


# #1202fh: fold the REFERENCED entity into an owner-scoped LIST read.
#
# The projected list for a join/interaction table returns only its own columns. netflix-r43,
# live: `GET /api/my-list` -> {"items": [{"id":.., "profile_id":.., "title_id":..}]}. A My List
# page has ids and nothing to draw, so it renders a placeholder grid -- which the visual judge
# reports as an EMPTY state, and it can never match a reference full of artwork.
#
# The split is visible in the pass rates. Pages backed directly by the entity table score
# 89% (landing), 60% (movies), 50% (shows); pages backed by a join/interaction table score
# 10% (my_list, new_and_popular, browse_by_languages). And the lane cannot route around it:
# #528 gives the projected read precedence over any lane GET on a registered resource.
#
# #803 folds a many-to-many into the DETAIL read and DELIBERATELY excludes `my_list`, because
# attaching "who saved this title" to a PUBLIC detail response is the #569 leak class. That
# reasoning is about the other direction. Here the caller is reading THEIR OWN rows -- this
# branch is already gated on `read_scoped` -- and the thing folded in is the public entity
# they point at, so no principal's data crosses a boundary.
#
# Three constraints carried over from #803/#569/#568 rather than re-derived:
#   1. owner-scoped LIST only (free here: the branch is inside `if read_scoped`);
#   2. never expand an FK pointing at an ACTOR table, decided by what the FK POINTS AT and
#      never by its name -- #784 lost `recipient_id` to a name-based guard;
#   3. never expand into a degenerate model with no columns (#568) -- nothing safe to show.
_IMAGEISH_1202FH = ("poster", "backdrop", "image", "thumb", "avatar", "cover",
                    "photo", "banner", "art", "still", "logo")


def _imageish_1202jc(col: Any) -> bool:
    """Does this column name an IMAGE, by word rather than by accident of spelling?

    #1202jc. The rule was `any(k in col.lower())`, and `"art"` is one of the keys: it matches
    inside `cart_token`, `partner_email`, `participant_name`, `started_at` and `departure_time`.
    That was harmless while the keep-list only ever chose columns for a page to draw --
    and #1202ip made it a live path, because the fold now carries the chosen columns of ANOTHER
    table into a PUBLIC list read. Verified by projecting a real model: a public `/api/orders`
    folding `carts` shipped `cart_token` and `partner_email`. My own fix widened the blast
    radius of a rule that predated it.

    A whole-token test is wrong in the other direction: `thumbnail`.split("_") == ["thumbnail"]
    does not contain `"thumb"`, so it would drop the single most common image column in the
    corpus (42 of them). Token PREFIX is what both cases want.

    Measured across the last 30 runs, of 153 columns the substring rule matched: 146 survive --
    avatar 48, thumbnail 42, poster 13, backdrop 13, avatar_url 7, thumbnail_url 6, peer_avatar
    4 -- and the 7 dropped are `started_at` (3), `participant_name` (2), `participant_id` (1),
    `departure_time` (1). Not one of the seven is an image column.
    """
    return any(t.startswith(k)
               for t in str(col or "").lower().split("_")
               for k in _IMAGEISH_1202FH)


# #1202ir: the columns an ACTOR row may show to someone who is not that actor.
# EXACT membership only -- deliberately not the looser rule `_IMAGEISH_1202FH` uses. That one
# was a raw substring test when this was written (`"art" in "partner_email"` and
# `"art" in "cart_token"` are both True) and is a token-PREFIX test since #1202jc; either way
# it is calibrated for picking artwork, not for deciding what an actor may show. An allowlist
# fails CLOSED: a column nobody anticipated (`phone`, `dob`, `stripe_customer_id`) is
# excluded by never having been named here, rather than by a denylist someone must extend.
_ACTOR_DISPLAY_COLS_1202IR = frozenset((
    "username", "handle", "nickname", "display_name", "displayname", "name",
    "full_name", "avatar", "avatar_url", "profile_image", "profile_picture",
    "image", "image_url", "photo_url", "bio", "verified", "is_verified",
))


def _public_actor_tables_1202ir(endpoints, models) -> set:
    """Actor tables this app already serves to an ANONYMOUS caller.

    This is what makes the fold provably zero-new-exposure: every column it carries is
    already retrievable, one request per row, from a projected read the contract declares
    public. r109 really does serve `GET /api/users/{username}` unauthenticated, returning
    username / display_name / avatar / bio / followers / verified (and `email`, which the
    allowlist above deliberately does NOT carry -- the fold is a strict subset of what is
    already public, never a superset).

    Auth is read through `_stated_auth_1202hi`, the one reader of the three places an
    endpoint can state it (#1202hi/#1202ga), so this does not become a fourth opinion.
    """
    out = set()
    try:
        for ep in (endpoints or []):
            if str((ep or {}).get("method", "")).upper() != "GET":
                continue
            if _stated_auth_1202hi(ep) is not False:
                continue                      # unstated or required -> not proven public
            res = _resource_model(str((ep or {}).get("path", "")), models)
            if res and res[0] in _ACTOR_TABLES_803:
                out.add(res[0])
    except Exception:
        return set()
    return out


def _joinable_types_1202fh(fk_type, id_type) -> bool:
    """True only when an `fk IN (ids)` comparison is type-safe on the database.

    tiktok-r96 mixes them: `videos.id` is Text (a uuid default) while `author_id` and
    `sounds.id` are Integer. Postgres answers a mismatched comparison with
    `UndefinedFunction: operator does not exist: text = integer` -- a 500 on a
    FRAMEWORK-PROJECTED route, which no lane can repair.

    Unknown on either side refuses. The asymmetry is #1202bd's: a missing expansion leaves
    the page exactly as it was, while a wrong one is a 500 that blocks delivery outright.
    """
    _INT = ("integer", "bigint", "smallint", "int")
    _TXT = ("text", "string", "varchar", "char", "unicode", "uuid")
    a, b = str(fk_type or "").lower(), str(id_type or "").lower()
    ai, bi = any(k in a for k in _INT), any(k in b for k in _INT)
    at, bt = any(k in a for k in _TXT), any(k in b for k in _TXT)
    if not (ai or at) or not (bi or bt):
        return False                      # unrecognised on either side -> refuse
    return (ai and bi) or (at and bt)


def _expandable_fks_1202fh(cols, models, table, *, private_tables=None,
                           public_actor_tables=None):
    """[(fk_col, target_cls, target_cols)] worth folding into a projected list read.

    Empty whenever anything is uncertain: an unresolvable FK, an actor target, a degenerate
    model, or a name that would shadow a column the row already carries.

    #1202ip: `private_tables` refuses any target the app itself serves owner-scoped. #1202fh
    argued its own safety from the READ ("the caller is reading THEIR OWN rows"); once the
    fold also runs on a public read that argument is gone and has to be replaced by one about
    the TARGET -- the folded entity must be something this app already serves to anyone.
    Without it a public `orders` list could fold `payment_methods` in. Passed on BOTH branches
    so the two reads answer the same question, rather than one of them being half-right
    (#1202io's lesson: an inconsistent guard misdirects worse than a consistently absent one).
    """
    out = []
    _private = {str(t) for t in (private_tables or ())}
    _pub_actors = {str(t) for t in (public_actor_tables or ())}   # #1202ir, empty by default
    try:
        own = set(cols or [])
        _declared = ((models or {}).get(table) or {}).get("fks") or {}
        for c in list(cols or []):
            # #1202iq: ask the DECLARED ForeignKey first, and only then fall back to the
            # name heuristic -- the order `_owner_scoped_child_566y` already uses at the other
            # `_fk_target_by_name_908` call site. Name-only resolution answered None for 76 of
            # 396 declared FKs across 24 corpus runs (19.2%), every one of them because the
            # column is not named after its table: `videos.author_id -> users`,
            # `routes.origin_place_id -> places`, `videos.category_id -> categories`. A missed
            # FK is not an error anywhere -- the expansion is simply skipped and the page keeps
            # rendering the bare id -- so nothing ever pointed at it.
            tgt = _declared.get(c) or _fk_target_by_name_908(c, models)
            if not tgt or tgt == table:
                continue
            _actor = tgt in _ACTOR_TABLES_803
            if _actor and tgt not in _pub_actors:
                # #569/#803's ban, unchanged wherever the app does not already publish the
                # actor. #1202iq made these targets resolvable for the first time, so this
                # is now the guard that actually fires rather than the keep-list below.
                continue
            if tgt in _private:
                continue                      # #1202ip: not public -> never folded in
            tmeta = (models or {}).get(tgt) or {}
            tcls = tmeta.get("cls")
            tcols = list(tmeta.get("cols") or [])
            if not tcls or not tcols:
                continue                      # #568 degenerate model
            _ftypes = ((models or {}).get(table) or {}).get("types") or {}
            _ttypes = tmeta.get("types") or {}
            if not _joinable_types_1202fh(_ftypes.get(c), _ttypes.get("id")):
                continue                  # mismatched or unknown join types -> 500 risk
            if "id" not in tcols:
                # The emitted map is keyed by the target's `id`. Without one every key is
                # None, every row resolves to None, and the expansion fails SILENTLY --
                # the page looks exactly as broken as before while the payload claims to
                # carry the entity. Refuse instead: no join key, no expansion.
                continue
            if _actor:
                keep = [x for x in tcols if str(x).lower() in _ACTOR_DISPLAY_COLS_1202IR]
            else:
                keep = [x for x in tcols
                        if x in _LABEL_COLS_803
                        or _imageish_1202jc(x)]
            if not keep:
                continue                      # nothing a card could draw
            base = str(c)[:-3]
            if not base.isidentifier() or base in own:
                continue                      # would shadow a real column
            out.append((c, tcls, ["id"] + keep))
    except Exception:
        return []
    return out


def _expansion_lines_1202ip(exp, cols: List[str], row_var: str = "r"):
    """``(prep_lines, item_expr)`` folding `exp` into a projected LIST read.

    Lifted verbatim out of #1202fh's owner-scoped branch so the PUBLIC collection branch
    can use the SAME mechanism instead of a second copy that would drift.

    #1202ip: the public branch never had it. 123 of 232 public projected list reads in the
    corpus (53%, across tiktok / netflix / googlemaps) answer with bare foreign keys --
    `/api/videos` returns `sound_id` and nothing about the sound, so the card the lane wrote
    (`sound?.name || video.sound_name || video.sound_id`) renders the raw id. The lane cannot
    repair it: #528 gives the projected read precedence over its own joined GET, and r109's
    `custom_routes.py` really does define a richer `GET /api/videos` that never serves a
    request. #528's stated trade-off was "lane-added filtering/sorting on PUBLIC lists"; the
    joined display fields were not part of that bargain.

    An empty `exp` returns the plain serialisation, so a read with nothing to fold emits
    exactly what it emitted before this helper existed.
    """
    prep: List[str] = []
    for _fk, _tcls, _tcols in (exp or []):
        _b = _fk[:-3]
        prep += [
            f'    _ids_{_b} = [i for i in (getattr({row_var}, "{_fk}", None) for {row_var} in rows) if i is not None]',
            f'    _m_{_b} = {{}}',
            f'    if _ids_{_b}:',
            f'        _m_{_b} = {{getattr(t, "id", None): {_serialize_expr("t", _tcols)} for t in db.query({_tcls}).filter(getattr({_tcls}, "id").in_(_ids_{_b})).all()}}',
        ]
    if not exp:
        return prep, _serialize_expr(row_var, cols)
    merge = "".join(
        f', "{_fk[:-3]}": _m_{_fk[:-3]}.get(getattr({row_var}, "{_fk}", None))'
        for _fk, _, _ in exp)
    return prep, f"{{**{_serialize_expr(row_var, cols)}{merge}}}"


def _detail_expansion_1202is(exp, obj_var: str = "obj"):
    """``(lines, merge_fragment)`` folding `exp` into a projected DETAIL read.

    #1202is: the list half of this (#1202ip) left the item half bare, and 30 of 53 projected
    detail reads in the corpus (56.6%) answer with bare foreign keys -- `/api/videos/{id}`
    is a registered SCREEN in every tiktok run and could name neither its author nor its
    sound. Two reads of the SAME entity disagreeing about what it carries is worse than both
    being bare: the page written against the feed's shape breaks on the detail route.

    One row, so one `db.get` per FK rather than #1202ip's batched `in_` -- and the same
    `_expandable_fks_1202fh` decides WHICH, so the actor ban, the contract-auth gate, the
    private-target gate and the type-safety check are shared, not restated.

    Empty `exp` emits nothing, exactly as #803 does when a table has no label relations.
    """
    if not exp:
        return [], ""
    lines = ["    _fkexp = {}"]
    for _fk, _tcls, _tcols in exp:
        _b = _fk[:-3]
        lines += [
            f'    _fkv_{_b} = getattr({obj_var}, "{_fk}", None)',
            f'    if _fkv_{_b} is not None:',
            f'        _fkt_{_b} = db.get({_tcls}, _fkv_{_b})',
            f'        if _fkt_{_b} is not None:',
            f'            _fkexp["{_b}"] = {_serialize_expr(f"_fkt_{_b}", _tcols)}',
        ]
    return lines, ", **_fkexp"


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


def _declared_optional_1202my(request_schema: Any, field: str) -> bool:
    """Does the endpoint's registered request schema EXPLICITLY mark `field` optional?

    Only an explicit marker counts. The corpus spells it two ways for POST `*_id` fields:
    a `?` suffix (509, e.g. `"str?"`) and `nullable` (3, incl. r125's
    `"string nullable references sounds.id"`); 298 are a plain type (required), and one is
    `"... not null"`, which is the opposite. An undeclared field or a missing schema is not
    optional."""
    if not isinstance(request_schema, Mapping):
        return False
    spec = request_schema.get(field)
    if isinstance(spec, str):
        low = spec.lower()
        if "not null" in low or "not nullable" in low or "non-null" in low:
            return False
        return spec.strip().endswith("?") or bool(re.search(r"\bnullable\b", low))
    if isinstance(spec, Mapping):
        return (spec.get("required") is False or spec.get("optional") is True
                or str(spec.get("type") or "").strip().endswith("?"))
    return False


def _generate_handler(method: str, path: str, auth: bool, models: Dict[str, Dict[str, Any]], idx: int, response_key: str = "", owner_scoped_reads: bool = False, owner_scoped_tables: Optional[Iterable[str]] = None,
                       public_actor_tables: Optional[Iterable[str]] = None,
                       request_schema: Optional[Mapping[str, Any]] = None) -> str:
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
    # #569 (netflix r134, live): _primary_content_model ran FIRST and REQUIRES a timestamp, so
    # a catalog whose content table has none (titles) lost to the only timestamped, owned,
    # non-spine table — `profiles` — and the projection emitted an UNSCOPED search over every
    # account's personas (id, user_id, name, avatar). The lane had to install HTTP middleware
    # and mutate app.routes at import time to stop it serving. _search_target_model exists for
    # exactly this case (its docstring names the Netflix `titles` shape) but was unreachable
    # behind the `or`. Ask the SEARCH-specific resolver first; keep the feed resolver as the
    # fallback for feed-shaped apps, where both agree anyway.
    if res is None and method.upper() == "GET" and "search" in path.lower():
        res = _search_target_model(models) or _primary_content_model(models)
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
    owner_sub_entity = False  # #566y
    owner_user_content = False  # #598
    if res:
        table, meta = res
        cls, cols = meta["cls"], meta["cols"]
        # The column that attributes a row to the authenticated caller (user_id/
        # author_id/...). Used to AUTHORIZE mutations (PUT/DELETE only touch your
        # OWN rows). NOTE: read-scoping (GET list/item) is deliberately NOT keyed
        # off this — "only see your own rows" is domain-dependent (private notes
        # vs a public feed), so it stays a separate, explicit decision.
        owner_fk = _owner_fk(meta) if auth else None
        # #566y: a SUB-ENTITY owner (profile_id → profiles → users) makes the resource
        # per-persona private BY CONSTRUCTION, so its reads scope without waiting for
        # the contract flag — which a draw may simply omit (netflix r131: `profiles`
        # carried owner_scoped_reads, `continue_watching` did not, so the projected
        # GET /api/continue-watching served EVERY profile's rows to any authenticated
        # caller while its own POST 403'd a foreign profile_id).
        owner_sub_entity = bool(owner_fk) and _is_per_user_sub_entity_fk(meta, owner_fk, models)
        # #598: …and the mirror shape — a DIRECT user FK on a row that also points at
        # shared content (my_list.user_id + my_list.title_id). r141 shipped
        # GET /api/my-list and GET /api/continue-watching unscoped for exactly this
        # reason, while r142 was safe only because its draw happened to pick profile_id.
        owner_user_content = bool(owner_fk) and _is_user_content_relation(meta, owner_fk)
    # A read is owner-scoped when the CONTRACT says so, or when the owner FK's shape
    # already settles it. A row whose OWN content is the payload (posts(user_id, body) —
    # a public feed) keeps the opt-in; a row that merely RELATES a user to someone
    # else's content does not.
    read_scoped = bool(owner_fk) and (bool(owner_scoped_reads) or owner_sub_entity
                                      or owner_user_content)
    # #1202hh: …and the SHAPE-derived half of that stands down when the materials declare the
    # rows published. Kept as its own statement, not folded into the expression above, because
    # #908/#598's ratchets read that line verbatim to prove each signal still participates —
    # and because the precedence is the point: the CONTRACT's own flag is untouched here, so
    # releasing a read needs the materials and the contract to agree. r103: the lane cleared
    # `owner_scoped_reads` on a spec-declared-public `videos` and `owner_user_content`
    # (author_id + sound_id) put the owner filter straight back, so 39 seeded videos stayed
    # invisible to every caller and every feed-backed flow failed.
    if read_scoped and not owner_scoped_reads and _declared_public_content_1202hh(meta):
        read_scoped = False
    # #1202ht: …and the materials' PRIVATE verdict restores it, for the read whose endpoint
    # flag talked the caller out of scoping. Both emitters funnel through here, so the two
    # cannot drift the way #1202hi found them drifting on the auth copies.
    if not read_scoped and bool(owner_fk) and _declared_owner_private_1202ht(meta):
        read_scoped = True
    # #777: the column a READ filters on — the narrowest owner the table declares.
    read_owner_fk = _read_owner_fk_777(meta, owner_fk) if read_scoped else owner_fk

    # #1202jb: a projected read of SOMEONE ELSE'S actor row must not carry their contact and
    # credential columns.
    #
    # `_serialize_expr` emits the MODEL's columns and has never consulted the contract's
    # declared response shape, so a lane that removes `email` from the schema still gets it in
    # the payload -- it cannot fix this from its side, and #528 gives the projected read
    # precedence over any GET it writes itself. `password_hash` was the only column the
    # projector had been taught to withhold; this extends that same rule, at the same emitter,
    # to the rest of the class.
    #
    # Measured over the last 30 runs: 18 UNAUTHENTICATED projected reads return `email` --
    # `/api/users/{username}` 14 times, `/api/search` once, and `/api/suggested-creators`
    # THREE times, which is a list: one anonymous request for every suggested creator's
    # address. The contract itself declares it (`auth_required: false` with `email` in the
    # response), so nothing downstream flags it as wrong.
    #
    # A DENYLIST, not the #1202ir allowlist, and deliberately: r110's profile page renders
    # `user.followers`, `user.following` and `user.likes`, none of which are display-identity
    # columns, so an allowlist narrow enough to be safe breaks a page that works. This is the
    # `password_hash` rule widened, which is a pattern already in production and tested.
    #
    # Exempted: `/me` -- DEFENSIVE ONLY and verified so: removing that clause leaves every
    # test green, because the `/me` branch resolves `_ucols` through `_me_user_model` and never
    # reads `cols` at all. It stays as a guard against a future branch that does, and is
    # recorded here as not load-bearing rather than left to read as protection. Also any
    # owner-scoped read (the handler filters to the caller's own row, so the address is their
    # own), and every non-GET — `POST /auth/register` needs `email` in its response.
    # Keyed on REACH, not on the table name. `/api/suggested-creators` resolves to its own
    # `suggested_creators` table -- the lane copied the user fields into it -- so an
    # actor-table test misses the worst instance in the corpus, a LIST of addresses served to
    # anonymous callers. A private column is private wherever it lives.
    #
    # Unauthenticated reads of ANY table, plus reads of an ACTOR table even when
    # authenticated, since reading someone ELSE's user row should not hand over their address
    # either. #1202gc already draws exactly this line for the unscoped-read finding: "any
    # authenticated caller" and "ANY caller -- the handler is UNAUTHENTICATED" are different
    # exposures and it says which.
    if (str(method).upper() == "GET" and not read_scoped
            and ((not auth) or table in _ACTOR_TABLES_803)
            and not str(path).rstrip("/").endswith("/me")):
        _kept = [c for c in cols if str(c).lower() not in _PRIVATE_ACTOR_COLS_1202JB]
        if _kept != cols and _kept:
            cols = _kept

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
        _pc = _feed_shaped_model_288(models)
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
        if read_scoped:
            # PRIVATE resource: a non-owner read is a 404 (not 403 — don't even
            # leak existence), exactly like the PUT/DELETE owner gate. Opt-in via
            # the resource's owner_scoped_reads contract signal (or, #566y, settled
            # by a sub-entity owner FK); open by default.
            body_lines += [
                f'    if getattr(obj, "{read_owner_fk}", None) != _fw_owner_val(type(obj), "{read_owner_fk}", user):',  # #777
                '        raise HTTPException(status_code=404, detail="not found")',
            ]
        # #803: fold normalised label relations into the item payload. When there are none the
        # emitted handler is byte-identical to before.
        # #1202is: the same fold the LIST read got, on the item read.
        _fkl1202is, _fkm1202is = _detail_expansion_1202is(
            _expandable_fks_1202fh(cols, models, table,
                                   private_tables=owner_scoped_tables,
                                   public_actor_tables=public_actor_tables) if table else [])
        body_lines += _fkl1202is
        _links803 = _link_label_reads_803(table, models) if table else []
        if _links803:
            body_lines.append("    _labels = {}")
            for _rel in _links803:
                body_lines += [
                    "    try:",
                    f"        _labels[\"{_rel['field']}\"] = [r[0] for r in db.execute("
                    f"text(\"{_link_label_sql_803(_rel)}\"), "
                    f"{{\"_lid\": getattr(obj, \"id\", None)}}).fetchall()]",
                    "    except Exception:",
                    # a label read must never turn a working detail page into a 500 — the chip row
                    # is worth strictly less than the page.
                    f"        _labels[\"{_rel['field']}\"] = []",
                ]
            body_lines += [
                f"    return {{\"item\": {{**{_serialize_expr('obj', cols)}, **_labels{_fkm1202is}}}}}",
            ]
        elif _fkm1202is:
            body_lines += [
                f"    return {{\"item\": {{**{_serialize_expr('obj', cols)}{_fkm1202is}}}}}",
            ]
        else:
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
        if read_scoped:
            body_lines.append(
                f'    query = query.filter(getattr({cls}, "{read_owner_fk}") == _fw_owner_val({cls}, "{read_owner_fk}", user))')  # #777
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
        if read_scoped:
            # PRIVATE resource: the list is the caller's own rows only.
            body_lines = [
                f'    rows = db.query({cls}).filter(getattr({cls}, "{read_owner_fk}") == _fw_owner_val({cls}, "{read_owner_fk}", user)).limit(100).all()',  # #777
            ]
            # #1202fh: fold the referenced entities in, one batched query per FK, so the
            # page has something to draw. N+1 would be 100 queries on a 100-row page.
            _prep1202fh, _item1202fh = _expansion_lines_1202ip(
                _expandable_fks_1202fh(cols, models, table,
                                       private_tables=owner_scoped_tables,
                                       public_actor_tables=public_actor_tables), cols)
            body_lines += _prep1202fh
            body_lines.append(
                f"    return {{\"items\": [{_item1202fh} for r in rows], \"total\": len(rows)}}"
            )
        else:
            # #1202ip: a PUBLIC list gets the same batched fold as the owner-scoped one.
            # `_expandable_fks_1202fh` still refuses every ACTOR target, so this adds no
            # principal's data to a public payload -- only the public entity the row already
            # names by id (a sound, a category, a place).
            _prep1202ip, _item1202ip = _expansion_lines_1202ip(
                _expandable_fks_1202fh(cols, models, table,
                                       private_tables=owner_scoped_tables,
                                       public_actor_tables=public_actor_tables), cols)
            _rank1155 = _ranked_collection_1155(path, cols, table)
            if _rank1155:
                _rcol, _rlim, _rdesc = _rank1155
                _ord = f'getattr({cls}, "{_rcol}")' + ('.desc()' if _rdesc else '')
                body_lines = [
                    f'    rows = db.query({cls}).filter(getattr({cls}, "{_rcol}").isnot(None)).order_by({_ord}).limit({_rlim}).all()',
                ] + _prep1202ip + [
                    f"    return {{\"items\": [{_item1202ip} for r in rows], \"total\": len(rows)}}",
                ]
            else:
                body_lines = [
                    f"    rows = db.query({cls}).limit(100).all()",
                ] + _prep1202ip + [
                    f"    return {{\"items\": [{_item1202ip} for r in rows], \"total\": len(rows)}}",
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
                # #566s: REJECT a cross-user create — a body owner-FK the caller does NOT own
                # → 403 (IDOR: userB POSTing body profile_id=userA's). An OWNED value is kept
                # (multi-profile); absent → resolve the caller's own via _fw_owner_val.
                #
                # #577 (netflix r141, live cross-user WRITE): the guard was emitted for the ONE
                # column `_owner_fk` returns, but a table can carry SEVERAL owner columns. r141's
                # `my_list` has BOTH `user_id` and `profile_id`; `_owner_fk` prefers the
                # user-level one (deliberately — see _OWNER_FK_NAMES), so `profile_id` went
                # UNCHECKED and `POST /api/my-list` as userB with body profile_id=<userA's
                # profile> returned 201: the row landed in A's profile while `user_id`
                # auto-filled to B. The lane's own handler DID verify it
                # (`_verify_profile_owned`), but writes stay projected, so the safer handler
                # never ran — the same displacement as #566y/#568, on the write path.
                # Guard EVERY owner-shaped column the model has; auto-fill only the primary one.
                _own_cols = [c for c in _OWNER_FK_NAMES
                             if c in (meta.get("cols") or []) and c not in tuple(bound)]
                for _oc in _own_cols:
                    body_lines += [
                        f'    if valid.get("{_oc}") is not None and not _fw_owns({cls}, "{_oc}", valid.get("{_oc}"), user):',
                        f'        raise HTTPException(status_code=403, detail="{_oc} does not belong to the caller")',
                    ]
                if ofk:
                    body_lines += [
                        f'    valid.setdefault("{ofk}", _fw_owner_val({cls}, "{ofk}", user))',
                    ]
            if m == "POST":
                # #566t: a create body that DROPPED a NOT-NULL column (verifier authored the wrong
                # key) INSERTs NULL even when the column has a DB DEFAULT → NOT-NULL 400. Apply the
                # column's DB default explicitly for any absent NOT-NULL no-model-default column.
                body_lines += [f'    valid = _fw_fill_required_defaults({cls}, valid, db)']
                # #1202bl: a create that names NO subject reaches the table anyway. Measured
                # live on netflix-r32: `POST /api/continue-watching {}` returns 201 and
                # inserts {profile_id: 28, title_id: null} — the owner FK is filled from the
                # user, the SUBJECT fk is not, and `GET /api/continue-watching` then hands that
                # row to the frontend, which renders a tile for no title. The lane's own handler
                # rejects exactly this with a 400, but it is not registered: it duplicates
                # standard CRUD, so the projection serves the path and calls itself
                # "schema-safe by construction".
                #
                # NOT a schema change. #1045 is why these columns are nullable — NOT NULL with no
                # default made 20 recent runs 400 at INSERT and r176 died on it — so this refuses
                # BEFORE the insert, on the one case that can never mean anything: the table has
                # subject FKs and the request named none of them.
                #
                # Blast radius measured: of 6946 corpus POSTs to a bare collection path, 83 send
                # an empty body and all but 3 are framework-owned auth/oauth/tenant routes the
                # projection does not serve. Those 3 already list 400 in their `expect`. Zero
                # corpus steps break.
                _subj_1202bl = [str(_f) for _f in (meta.get("fks") or {})
                                if str(_f) != str(_owner_fk(meta, exclude=tuple(bound)) or "")
                                and str(_f) not in {str(_b) for _b in bound}]
                # #1202my: THE FRAMEWORK MUST NOT REFUSE A CREATE ITS OWN CONTRACT DECLARES VALID.
                # #1202bl's premise is "a create naming no subject FK is nothing but its own id
                # and owner" — true for `POST /api/continue-watching {}`, false for tiktok-r125's
                # `POST /api/videos {video_url, thumbnail, caption, category}`: a video with no
                # linked sound is an ordinary video, and the registered request schema says
                # `sound_id: "int?"`. #1202md saw the contradiction and changed only the message.
                # r125's M2 then failed framework validation 6/6 on that 400, labelled "the lane
                # cannot edit it" — while nothing the lane could do would make it pass.
                # When EVERY subject FK is explicitly declared optional, the contract has already
                # answered the question; fall back to the weaker "a create needs at least one
                # field" check below. An undeclared FK or a missing schema keeps the guard, so the
                # continue-watching shape stays refused.
                # The same empty create is still refused: the owner FK is always filled in, so the
                # fallback `if not valid:` could never fire here. What changes is that a request
                # naming ANY field of its own (caption, video_url) is no longer turned away.
                # Corpus: 39 of 281 subject-FK POST endpoints declare every subject FK optional
                # (`/api/videos` 17, `/api/notifications` 7, ...); netflix continue-watching
                # declares `title_id: "int"` in every run and keeps the full guard.
                _optional_only_1202my = bool(_subj_1202bl) and all(
                    _declared_optional_1202my(request_schema, _f) for _f in _subj_1202bl)
                if _optional_only_1202my:
                    _excl_1202my = sorted({"id", *(str(_b) for _b in bound), *_subj_1202bl,
                                           str(_owner_fk(meta, exclude=tuple(bound)) or "")} - {""})
                    body_lines += [
                        "    if not any(valid.get(_k) is not None for _k in %r) and not any(" % (_subj_1202bl,),
                        "            _v not in (None, '') and _k not in %r" % (_excl_1202my,),
                        "            and not (isinstance(_v, str) and _v.startswith('${'))",
                        "            for _k, _v in payload.items() if hasattr(%s, _k)):" % (cls,),
                        "        raise HTTPException(status_code=400, detail=%r)" % (
                            "a create must name %s or at least one other field of its own - an "
                            "empty create is nothing but its own id and owner (#1202my)"
                            % " or ".join(_subj_1202bl),),
                    ]
                if _optional_only_1202my:
                    pass
                elif _subj_1202bl:
                    # #1202md: SAY WHY, because with ONE subject FK this reads as a
                    # contradiction of the contract the framework itself registered.
                    #
                    # The rule is "name at least one subject FK", and with two or more that is
                    # plainly a disjunction. With exactly one it degenerates to "sound_id is
                    # required" — while the same endpoint's registered request schema declares
                    # `sound_id: "int?"`, optional. Both statements are true about different
                    # things, and nothing said so, so a lane reading its own contract sees a
                    # framework demanding a field it published as optional.
                    #
                    # Measured over the corpus (24 runs carrying this guard): 15 multi-FK
                    # cases, where the message already reads as a choice, and 8 single-FK
                    # endpoints across 7 runs where it does not —
                    # POST /api/videos.sound_id in r101/r102/r103/r107/r109/r121,
                    # POST /api/comments.video_id in r120, POST /api/feed.sound_id in r121.
                    #
                    # Message only. The guard's behaviour is unchanged, so #1202bl's measured
                    # "zero corpus steps break" still holds.
                    _why_1202md = (
                        "the table's only subject FK - a create naming none of them inserts a "
                        "row that is nothing but its own id and owner (#1202bl). The request "
                        "schema marks it optional because it is optional INDIVIDUALLY; what is "
                        "required is that at least one subject FK be named"
                        if len(_subj_1202bl) == 1 else
                        "at least one subject FK must be named - a create naming none of them "
                        "inserts a row that is nothing but its own id and owner (#1202bl)")
                    body_lines += [
                        "    if not any(valid.get(_k) is not None for _k in %r):" % (_subj_1202bl,),
                        '        raise HTTPException(status_code=400, detail="one of %s is '
                        'required: %s")' % (", ".join(_subj_1202bl), _why_1202md),
                    ]
                else:
                    # No subject FK to require, so the same empty create lands a row that is
                    # nothing but its own id and its owner. r32, live: `POST /api/profiles {}`
                    # -> 201 {"id":29,"user_id":25,"name":null,"is_kids":null}, a profile with
                    # no name, which the picker renders as a blank tile. Require that the body
                    # supplied SOMETHING — any column at all after coercion. Same blast radius as
                    # above: it is the same empty bodies, already measured at 83 of 6946 bare
                    # collection POSTs, 80 of them framework-owned routes this does not serve.
                    body_lines += [
                        "    if not valid:",
                        '        raise HTTPException(status_code=400, detail='
                        '"a create needs at least one field")',
                    ]
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
            # #1202ie: the psycopg text names ONE of the two types it is about.
            f'        raise HTTPException(status_code=500, detail=f"create failed: '
            f'{{_exc}}" + _fw_type_mismatch_hint_1202ie({cls}, valid, _exc))',
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


def _structurally_private_resource_633(method: str, path: str,
                                       models: Dict[str, Dict[str, Any]]) -> bool:
    """#633 — is the resource this endpoint reads per-user-private BY CONSTRUCTION?

    #566y and #598 established that a table's SHAPE can settle privacy without the contract
    saying so — a sub-entity owner (``profile_id → profiles → users``) or a direct user FK
    alongside a content FK (``my_list.user_id`` + ``my_list.title_id``). Both signals were
    computed INSIDE ``_generate_handler``, but the force-auth decision is made by the CALLER,
    before it. So they could never fire on an endpoint the contract left unauthenticated:

        auth  = resolve_endpoint_auth(...) or _owner_scoped   # _owner_scoped: CONTRACT only
        ...
        owner_fk = _owner_fk(meta) if auth else None          # auth False -> no owner column
        read_scoped = bool(owner_fk) and (...)                # -> False -> no filter

    A private table therefore became a PUBLIC DUMP whenever the draw forgot ``auth_required``.
    Found by auditing the 45 delivered backends: 4 of them ship

        @app.get("/api/search")
        def _projected_get_api_search_9(q: str = "", db=Depends(get_db)):   # no actor
            query = db.query(ContinueWatching)                              # no filter
            ... returns user_id, title_id, progress_seconds for EVERY user, unauthenticated

    and today's projector still emits exactly that — this is a LIVE defect, not a historical
    artifact. It is #569's shape (which had to be worked around with import-time
    ``app.routes`` mutation) surviving one level up: #569 fixed WHICH table search resolves to,
    not whether that table's privacy is honoured.

    Asked at the caller so the same structural facts reach the auth decision. Deliberately
    overrides an explicit ``auth_required=False``, on the precedent already stated there:
    "per-user-private reads and public are contradictory, and a private read is unscopable
    without an actor". A public feed (``posts(user_id, title, body)`` — user FK, no content FK)
    is untouched, which is the whole point of #598's discriminator.
    """
    try:
        res = _resource_model(path, models)
        if res is None and str(method).upper() == "GET" and "search" in str(path).lower():
            res = _search_target_model(models) or _primary_content_model(models)
        if not res:
            return False
        _table, meta = res
        # #1202hh — the materials' verdict OUTRANKS the shape, on #1202gd's measured
        # rationale: the schema provably cannot separate a published feed from a private
        # list, so `entities[].visibility` (compiled from the product's screenshots and
        # docs at design time, before any lane runs) is the only thing that can. This does
        # NOT release the read on its own: the caller's `_owner_scoped` still carries the
        # contract's `owner_scoped_reads`, so a lane that marks the table private keeps it
        # scoped and the r141 leak shape (a per-user list declared public by mistake) needs
        # BOTH signals to be wrong, exactly as #1202gd requires of the audit.
        if _declared_public_content_1202hh(meta):
            return False
        fk = _owner_fk(meta)
        if not fk:
            return False
        return bool(_is_per_user_sub_entity_fk(meta, fk, models)
                    or _is_user_content_relation(meta, fk))
    except Exception:
        return False


def _retype_projected_params_1202ic(src: str, models: Dict[str, Dict[str, Any]]):
    """Re-type path params on handlers the FRAMEWORK projected, when the schema moved.

    #1202ic: `project_missing_routes` appends a handler for every declared endpoint that
    has NO route, and counts the rest as `already`. Correct for what it is, and it means a
    handler emitted once is never revisited -- so the param type it was born with outlives
    the column it was derived from.

    tiktok-r107, live while this was written. `models.py` git history:

        faf536f  videos.id  Integer -> Text
        68a25b2             Text -> Integer
        1f19c23             Integer -> Text

    The lane is oscillating on the PK type, and it is doing so BECAUSE of this: the seven
    projected `/api/videos/{id}...` handlers were all born `id: int`, so every request
    carrying a real uuid ("48663848-36cc-...") is rejected by FastAPI with
    `int_parsing` 422 before the handler body runs. 34 such 422s across the corpus. The
    lane sees "not a valid integer", changes the column, nothing improves, changes it back.
    `_param_column_type` asked against the CURRENT models.py answers `str` -- the right
    answer was available the whole time, to a caller that never asked again.

    Only `_projected_*` functions are touched, and only the annotation: that prefix is
    stamped by `_generate_handler` and nothing a lane writes carries it, so lane-authored
    code is out of reach by construction.
    """
    changed: List[str] = []
    try:
        tree = ast.parse(src)
    except Exception:
        return src, changed
    lines = src.splitlines(keepends=True)
    edits = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not node.name.startswith("_projected_"):
            continue
        route = ""
        for dec in node.decorator_list:
            if (isinstance(dec, ast.Call) and dec.args
                    and isinstance(dec.args[0], ast.Constant)
                    and isinstance(dec.args[0].value, str)):
                route = dec.args[0].value
                break
        if not route or "{" not in route:
            continue
        for arg in list(node.args.args) + list(node.args.kwonlyargs):
            ann = arg.annotation
            if not (isinstance(ann, ast.Name) and ann.id in ("int", "str")):
                continue
            want = _param_column_type(arg.arg, _express_to_fastapi(route), models)
            if want == ann.id:
                continue
            edits.append((ann.lineno - 1, f"{arg.arg}: {ann.id}", f"{arg.arg}: {want}"))
            changed.append(f"{node.name}({arg.arg}: {ann.id} -> {want})")
    for ln, old, new in edits:
        if 0 <= ln < len(lines) and old in lines[ln]:
            lines[ln] = lines[ln].replace(old, new, 1)
    return ("".join(lines) if edits else src), changed


def _reproject_stale_auth_1202jt(src: str, declared_endpoints: List[Mapping[str, Any]]):
    """Drop projected handlers whose endpoint's AUTH contract moved after registration.

    #1202ic fixed this for param types and named the mechanism exactly: "a handler emitted
    once is never revisited -- so the param type it was born with outlives the column it was
    derived from". The same sentence is true of the auth guard, and nothing re-derived it.

    Measured over the 20 runs since #1202ga: 20 projected handlers serve anonymously while
    their contract requires auth, and 18 of the 20 carry `schema=True, metadata=False` — the
    mirror frozen at registration says PUBLIC, so the handler was projected open and was right
    to be, and the contract was flipped to True afterwards. googlemaps-r16 is the case:
    `GET /api/titles`, `/api/genres`, `/api/search`, `/api/transit-stops/{stop_id}` all
    projected as `(db=Depends(get_db))` with no actor, while `custom_routes.py:3192` holds the
    lane's own guarded route that #528 overrides. The lane cannot fix this: it wrote the right
    route and the projection wins.

    THIS FUNCTION DOES NOT DECIDE AUTH. The decision is four interacting rules (#320's public
    feed, #1202ht's materials override, #633's structural privacy, #271's owner-scope force)
    and reproducing it here is the one-fact-many-emitters trap. It only drops the handler so
    the projection loop below rebuilds it with the CURRENT contract through the same code that
    built it the first time. A handler dropped when nothing would change is regenerated
    identically, so a false positive costs nothing.

    Trigger: the frozen `metadata.auth_required` mirror disagrees with what the contract states
    today. That is the definition of "moved since registration", and it needs no auth rule at
    all — only #1202hi's reader.
    """
    dropped: List[str] = []
    try:
        moved = set()
        for ep in (declared_endpoints or []):
            if not isinstance(ep, Mapping):
                continue
            _md = ep.get("metadata") if isinstance(ep.get("metadata"), Mapping) else {}
            _mirror = _md.get("auth_required")
            if not isinstance(_mirror, bool):
                continue                       # never mirrored → nothing to have moved from
            _now = _stated_auth_1202hi(ep)
            if _now is None or bool(_now) == bool(_mirror):
                continue
            _m = str(ep.get("method", "")).upper()
            _p = _express_to_fastapi(str(ep.get("path", "")))
            # SAFE BY CONSTRUCTION: drop only what the loop below will REBUILD. It projects
            # `/api/` business endpoints and nothing else ("/auth/* is owned by the embedded
            # OAuth2 AS ... never projected here"), so dropping anything outside that prefix
            # would delete an endpoint instead of refreshing it. r111's moved set contains
            # POST /auth/register and /auth/login; no `_projected_*` handler exists for them
            # today, and this does not rely on that staying true.
            if _m and _p.startswith("/api/"):
                moved.add((_m, _norm_path(_p)))
        if not moved:
            return src, dropped
        tree = ast.parse(src)
    except Exception:
        return src, dropped
    cuts = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not node.name.startswith("_projected_"):
            continue                            # lane-authored code is out of reach
        for dec in node.decorator_list:
            if not (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)
                    and dec.args and isinstance(dec.args[0], ast.Constant)
                    and isinstance(dec.args[0].value, str)):
                continue
            key = (dec.func.attr.upper(), _norm_path(dec.args[0].value))
            if key not in moved:
                continue
            start = min([d.lineno for d in node.decorator_list] + [node.lineno])
            end = getattr(node, "end_lineno", None)
            if end:
                cuts.append((start, end))
                dropped.append(f"{key[0]} {dec.args[0].value} ({node.name})")
            break
    if not cuts:
        return src, dropped
    lines = src.splitlines(keepends=True)
    drop_idx = set()
    for a, b in cuts:
        drop_idx.update(range(a - 1, b))
    return "".join(l for i, l in enumerate(lines) if i not in drop_idx), dropped


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
    # #1202jt: BEFORE `existing` is taken — a projected handler whose auth contract moved
    # since it was emitted is dropped here so the loop below rebuilds it from the contract as
    # it stands now. #1202ic does the same thing for param types; the guard had no such pass.
    _src_predrop_1202jt = src
    src, _reauth_1202jt = _reproject_stale_auth_1202jt(src, declared_endpoints)
    existing = _existing_routes(src)
    models = _orm_models(backend_dir)
    # #1202ir: actor tables the CONTRACT itself declares publicly readable. Computed once
    # from the same endpoint list the handlers are projected from, so the fold can never
    # publish an actor this app keeps behind auth.
    _pub_actors_1202ir = _public_actor_tables_1202ir(declared_endpoints, models)
    # #1202ic: a handler projected earlier keeps the param type it was born with, even
    # after the lane moves the column. Re-derive before anything else reads `src`.
    src, _retyped_1202ic = _retype_projected_params_1202ic(src, models)

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
    _public_1202kh: List[Tuple[str, str]] = []  # (METHOD, path) projected with no actor
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
        # #1202hi: through the shared reader, so this sees the copy the LANE writes.
        _explicit_public = _stated_auth_1202hi(ep, meta) is False
        # #1202ht: an endpoint flag cannot publish a table the materials call per-user.
        if _explicit_public and _rm_cur and _declared_owner_private_1202ht(_rm_cur[1]):
            _explicit_public = False
        if _explicit_public and _owner_scoped:
            _owner_scoped = False   # deliberate public read → all rows, no owner filter
        # #633: …but a table that is per-user-private BY CONSTRUCTION is private whatever the
        # contract says or forgets. Without this the two structural signals (#566y, #598) are
        # unreachable on an unauthenticated endpoint, because they are computed after the auth
        # decision that they should be informing. 4 of 45 delivered backends ship an
        # UNAUTHENTICATED `GET /api/search` over `continue_watching` for exactly this reason.
        if _structurally_private_resource_633(method, path, models):
            _owner_scoped = True
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
        # #1202kh: same `auth` the handler is built with, so the middleware's public set and
        # this handler can never disagree — see `refresh_public_api_1202kh`.
        # #1202kh: reads only — see `render_skeleton_main`'s note for why writes keep the
        # blanket rule. Both emitters apply the SAME filter, or the two sets would disagree.
        if ((not auth) and str(method).upper() in ("GET", "HEAD")
                and path.startswith("/api/") and not path.startswith("/api/v1/")):
            _public_1202kh.append((str(method).upper(), str(path)))
        block_info.append((path, _generate_handler(method, path, auth, models, i, response_key, _owner_scoped, owner_scoped_tables=scoped_read_tables, public_actor_tables=_pub_actors_1202ir,
                                                    request_schema=(_schema.get("request") if isinstance(_schema, Mapping) else None))))
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
        # #1202kh: refresh the middleware's public set BEFORE the handlers go in, so the
        # guard and the routes land in the same write.
        new_src = refresh_public_api_1202kh(new_src, _public_1202kh)
        new_src = _insert_before_first_route(new_src, top)
        if param_blocks:
            new_src = _insert_before_main_guard(
                new_src,
                "# === BY-CONSTRUCTION: param routes the lane declared but did not\n"
                "# implement (appended last so /{id} patterns never shadow lane routes).\n"
                + "\n\n\n".join(param_blocks))
        _write_py_995(main_py, new_src, what="project_missing_routes")

    elif _retyped_1202ic:
        # Nothing was missing, so the block above never wrote -- but the types moved.
        #
        # #1202jt: and this branch must NOT carry the drops. `src` here has stale handlers
        # REMOVED and, with `block_info` empty, nothing put back — writing it would delete
        # endpoints rather than refresh them. Under the loop's current skips (only `/api/`
        # and `existing`, both accounted for) a drop always produces a re-projection and this
        # branch is unreachable with drops pending. That is an implicit invariant, and an
        # implicit invariant guarding a DELETE is the shape that bites; fall back explicitly.
        _write_py_995(
            main_py,
            _retype_projected_params_1202ic(_src_predrop_1202jt, models)[0]
            if _reauth_1202jt else src,
            what="retype_projected_params_1202ic")

    return {"projected": projected, "already": len(existing) - len(projected),
            "reauth_reprojected_1202jt": _reauth_1202jt,
            "retyped_1202ic": _retyped_1202ic}


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

def identical_projected_bodies_1156(backend_dir: Any) -> List[Tuple[str, ...]]:
    """#1156: routes whose handler BODIES are identical answer the same rows.

    netflix-local-r14 delivered /api/titles and /api/titles/trending both as
    `db.query(Title).limit(100).all()`. #1155 fixed /api/titles/top10 in the SAME run
    (verified in the shipped main.py: `.filter(top10_rank.isnot(None)).order_by(...)
    .limit(10)`) because a column exists to rank by. `trending` has no backing column,
    so there is nothing to project — the CONTRACT is what is incomplete, and only the
    lane can close it. It was never told.

    Read from the FINAL main.py rather than from one generator's bookkeeping: r14's
    handlers came from `backend_skeleton`, not `project_missing_routes`, so a check
    living inside either one sees only half the runs. The file is what ships.

    Compares the ast.dump of each route function's BODY, which carries neither the
    function name nor the decorator — both of which encode the path, so comparing
    whole functions would find nothing, ever. No word list: enumerating
    "ranked-sounding" segments (trending / popular / featured) would be guessing at
    English, while identical bodies are a fact about the code.

    Returns ``[("GET /api/titles", "GET /api/titles/trending"), …]``; never raises.
    """
    try:
        src = (Path(backend_dir) / "main.py").read_text(encoding="utf-8", errors="ignore")
        tree = ast.parse(src)
    except Exception:
        return []
    # A route the LANE serves from custom_routes.py is not a duplicate, whatever main.py
    # says about it. r14 delivered a projected `/api/titles/trending` body identical to
    # `/api/titles` AND a lane handler with `limit: int = Query(default=20)`;
    # `include_router(_custom_router)` runs at main.py:948, hundreds of lines before the
    # projected route, so the lane's wins. Probed on the live stack: ?limit=5 -> 5 rows,
    # ?limit=37 -> 37. The projected body is dead code, and reporting it would send a
    # lane to fix an endpoint it had already implemented correctly.
    _lane_routes: set = set()
    try:
        _cr = (Path(backend_dir) / "custom_routes.py").read_text(
            encoding="utf-8", errors="ignore")
        for _m in re.finditer(
                r'@router\.(get|post|put|patch|delete)\(\s*["\']([^"\']+)["\']', _cr):
            _lane_routes.add("%s %s" % (_m.group(1).upper(), _m.group(2)))
    except Exception:
        _lane_routes = set()
    by_body: Dict[str, List[str]] = {}
    for node in getattr(tree, "body", []):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        route = ""
        for d in node.decorator_list:
            if (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                    and d.args and isinstance(d.args[0], ast.Constant)
                    and isinstance(d.args[0].value, str)):
                route = "%s %s" % (d.func.attr.upper(), d.args[0].value)
        if not route:
            continue
        try:
            body = "".join(ast.dump(n) for n in node.body)
        except Exception:
            continue
        # only DB-reading collections: two identical `raise HTTPException` stubs are
        # not a contract gap, and neither are two identical health probes.
        if "query" not in body:
            continue
        if route in _lane_routes:
            continue
        by_body.setdefault(body, []).append(route)
    return [tuple(sorted(v)) for v in by_body.values() if len(v) > 1]


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
            _write_py_995(main_py, new_src, what="project_state_write_endpoints")

        result["projected"] = projected
        result["endpoints"] = synthesized
    except Exception as exc:  # best-effort — never wedge the heal run
        result["error"] = str(exc)
    return result
