from .safe_code_write import write_py_if_still_parses as _write_py_995

"""Framework-owned backend auth dependency — FIX #45.

The business handlers gate on ``Depends(get_current_user)``, but the lane writes a
PLACEHOLDER ``get_current_user`` that IGNORES the token and returns
``db.query(User).order_by(User.id).first()`` — so any request with a user in the
DB is "authenticated" (auth_enforced_401 → 200, an info-disclosure hole). The
lane even SAYS so: *"The full auth dependency is provided elsewhere in the
complete scaffold."* So the framework owns it (like it owns /auth/register): write
a real ``auth_dependency.py`` (verify the RS256 JWT minted by the AS, load the
user, else 401) and rewrite each route file's local placeholder into an import of
it. Deterministic + best-effort.
"""

import ast
import re
from pathlib import Path
from typing import Dict, List, Optional
try:  # #1202cw
    from .path_routed_workspace import framework_write_1202cw as _fw_write_1202cw
except ImportError:  # pragma: no cover - only when this file is loaded BY PATH (two tests)
    def _fw_write_1202cw(_p, _text, **_kw):
        from pathlib import Path as _P
        _P(str(_p)).write_text(_text, encoding=_kw.get("encoding", "utf-8"))  # raw: shim
        return True

_AUTH_DEPENDENCY_PY = '''"""Framework-owned auth dependency: real RS256 JWT verification.

Verifies the RS256 access token minted by the embedded OAuth2 AS (jwt_manager),
loads the user whose id == the token ``sub``, else raises 401. The business
handlers import ``get_current_user`` from here so auth is enforced by construction.
"""

import jwt as _pyjwt
from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from sqlalchemy import text


class _AuthUser(dict):
    """A user record supporting BOTH attribute (``user.id``) and item (``user["id"]``)
    access — handlers across runs use either, so this is compatible with both and with
    raw-SQL apps that have no ORM User model."""
    def __getattr__(self, k):
        try:
            return self[k]
        except KeyError as exc:
            raise AttributeError(k) from exc


try:
    from jwt_manager import JWTManager, ALGORITHM
    _JWT = JWTManager()
    # public_pem is a @property in the AS scaffold (bytes); tolerate a method too.
    _pp = _JWT.public_pem
    _PUBLIC_PEM = _pp() if callable(_pp) else _pp
except Exception:  # pragma: no cover - AS modules must be present in a real env
    _PUBLIC_PEM = None
    ALGORITHM = "RS256"


def get_current_user(authorization: str = Header(default=None), db: Session = Depends(get_db)):
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    if not _PUBLIC_PEM:
        raise HTTPException(status_code=401, detail="auth unavailable")
    try:
        claims = _pyjwt.decode(
            token, _PUBLIC_PEM, algorithms=[ALGORITHM],
            options={"verify_aud": False},
        )
    except Exception:
        raise HTTPException(status_code=401, detail="invalid token")
    sub = claims.get("sub")
    if sub is None:
        raise HTTPException(status_code=401, detail="invalid token subject")
    # Load via raw SQL so this works whether or not the app defines an ORM User model.
    try:
        row = db.execute(
            text("SELECT * FROM users WHERE id = :id"), {"id": int(sub)}
        ).mappings().first()
    except Exception:
        row = None
    if not row:
        raise HTTPException(status_code=401, detail="unknown user")
    return _AuthUser(dict(row))
'''

def _module_get_current_user(tree: ast.Module) -> Optional[ast.FunctionDef]:
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and \
                node.name == "get_current_user":
            return node
    return None


def _is_placeholder_auth(func: ast.AST) -> bool:
    """A broken ``get_current_user`` does NOT validate the bearer JWT. Two shapes:
    (1) the classic placeholder — no token param, pulls an arbitrary user via
    ``.first()``/``order_by``; (2) a wrongly-implemented dependency that reads identity
    from a SIDE CHANNEL such as an ``X-User-Id`` header (instagram MM run #11: every
    authed endpoint 401'd 'missing user context' because the token was never read). A
    REAL one — has a token-carrying param (``authorization``/``token``/…) OR decodes the
    JWT (``jwt``/``decode``/``bearer``/``public_pem``) — is left untouched; rewriting it
    would DELETE working auth (and broke main.py once already)."""
    args = func.args
    if args.vararg or args.kwarg:
        return False  # too dynamic to reason about — leave alone
    dumped = ast.dump(func).lower()
    # Real auth DECODES the bearer JWT. Only STRONG decode signals count — a token
    # param or the words 'authorization'/'bearer' are too weak: run #13's broken
    # get_current_user READ the Authorization header but used the raw token as a SQL
    # lookup value (``WHERE id = :token``), never decoding it → 401 on every authed
    # endpoint (and api_smoke passed it as <500). If the function does not actually
    # decode/verify the JWT, normalise it to the framework auth dependency.
    if any(k in dumped for k in ("jwt", "decode(", "verify_token", "public_pem",
                                 "public_key", "jwtmanager", "jwks", "pyjwt")):
        return False  # decodes the token → real auth, leave alone
    return True


def _rewrite_local_get_current_user(src: str) -> str:
    """AST-precise: if the module defines a PLACEHOLDER ``get_current_user``,
    replace exactly its line range (decorators..end, multi-line safe) with an
    import of the framework one. No-op otherwise."""
    if "from auth_dependency import get_current_user" in src:
        return src
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return src
    func = _module_get_current_user(tree)
    if func is None or not _is_placeholder_auth(func):
        return src
    lines = src.splitlines()
    start = (func.decorator_list[0].lineno if func.decorator_list else func.lineno) - 1
    end = getattr(func, "end_lineno", func.lineno)  # 1-based inclusive → slice end
    new = (lines[:start]
           + ["from auth_dependency import get_current_user  # canonical framework auth"]
           + lines[end:])
    return "\n".join(new) + ("\n" if src.endswith("\n") else "")


def repair_backend_auth_dependency(backend_dir) -> Dict[str, object]:
    """Write the framework auth dependency + point any PLACEHOLDER
    get_current_user at it (real, token-reading ones are left alone).
    Best-effort, never raises."""
    try:
        be = Path(backend_dir)
        # Only database.py is required now — the framework auth loads the user via raw
        # SQL, so a raw-SQL app with NO models.py (instagram MM run #13) must still get
        # its broken get_current_user normalised (previously this bailed → auth stayed
        # broken on every authed endpoint).
        if not (be / "database.py").exists():
            return {"repaired": False, "reason": "no database"}
        py_files = [p for p in be.glob("*.py")
                    if p.name not in ("auth_dependency.py", "jwt_manager.py",
                                      "oauth_store.py", "oauth_routes.py")]
        placeholder_files: List[Path] = []
        for p in py_files:
            try:
                tree = ast.parse(p.read_text(encoding="utf-8", errors="ignore"))
            except Exception:
                continue
            func = _module_get_current_user(tree)
            if func is not None and _is_placeholder_auth(func):
                placeholder_files.append(p)
        if not placeholder_files:
            return {"repaired": False, "reason": "no placeholder get_current_user"}
        _write_py_995((be / "auth_dependency.py"), _AUTH_DEPENDENCY_PY, what="repair_backend_auth_dependency")
        rewritten: List[str] = []
        for p in placeholder_files:
            src = p.read_text(encoding="utf-8", errors="ignore")
            new = _rewrite_local_get_current_user(src)
            if new != src:
                _write_py_995(p, new, what="repair_backend_auth_dependency")
                rewritten.append(p.name)
        return {"repaired": bool(rewritten), "auth_dependency": True,
                "rewritten": rewritten}
    except Exception as exc:
        return {"repaired": False, "error": f"{type(exc).__name__}: {exc}"}


# Runtime-owned auth infra — the framework writes these; never rewrite their imports.
_AUTH_INFRA_FILES = (
    "auth_dependency.py", "jwt_manager.py", "oauth_store.py", "oauth_routes.py",
)


def _normalize_auth_imports_in_src(src: str) -> str:
    """FIX #48 (AST-precise): repoint any ``from <X> import ... get_current_user ...``
    where ``X != auth_dependency`` to import ``get_current_user`` from
    ``auth_dependency`` (the module the framework actually scaffolds it into).
    Co-imported names stay on the original module; an alias is preserved. Idempotent
    (a canonical import is a no-op); no-op on a syntax error. Replaces ONLY the affected
    import statement's line range, so the rest of the file's formatting is untouched."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return src
    edits = []  # (start_idx, end_idx_exclusive, [new_lines])
    for node in tree.body:
        if not isinstance(node, ast.ImportFrom):
            continue
        # Already canonical → leave it (idempotent).
        if node.level == 0 and node.module == "auth_dependency":
            continue
        gcu = [a for a in node.names if a.name == "get_current_user"]
        if not gcu:
            continue
        alias = gcu[0].asname
        gcu_line = "from auth_dependency import get_current_user" + (
            f" as {alias}" if alias else "")
        others = [a for a in node.names if a.name != "get_current_user"]
        start = node.lineno - 1
        end = getattr(node, "end_lineno", node.lineno)  # 1-based inclusive → slice end
        new_lines = []
        if others:
            mod = ("." * node.level) + (node.module or "")
            parts = ", ".join(
                a.name + (f" as {a.asname}" if a.asname else "") for a in others)
            new_lines.append(f"from {mod} import {parts}")
        new_lines.append(gcu_line)
        edits.append((start, end, new_lines))
    if not edits:
        return src
    lines = src.splitlines()
    for start, end, new_lines in sorted(edits, reverse=True):  # bottom-up: indices stable
        lines[start:end] = new_lines
    return "\n".join(lines) + ("\n" if src.endswith("\n") else "")


_ROUTER_USE_RE = re.compile(r"^\s*@router\.", re.M)
_ROUTER_DEF_RE = re.compile(r"^\s*router\s*=", re.M)


def repair_custom_routes_router_prologue(backend_dir) -> Dict[str, object]:
    """custom_routes.py uses ``@router.<verb>`` but never DEFINES ``router`` (outlook
    run-34, live): the module raises NameError at import, main.py's include swallows it,
    and the WHOLE custom router silently vanishes — the lane's properly OWNER-SCOPED
    by-id reads with it, so the unscoped projected reads leaked cross-user rows →
    isolation probes failed 7 cycles → STUCK abort. The missing prologue is mechanical:
    insert the canonical ``router = APIRouter()`` after the last top-level import.
    Idempotent; best-effort."""
    out: Dict[str, object] = {"repaired": False}
    try:
        p = Path(backend_dir) / "custom_routes.py"
        if not p.exists():
            # #1149c: r13 logged this heal as "(no cause reported)" 19 times. Both no-op
            # paths are healthy, and they mean different things about the lane.
            return {"repaired": False, "reason": "no custom_routes.py"}
        src = p.read_text(encoding="utf-8")
        if not _ROUTER_USE_RE.search(src) or _ROUTER_DEF_RE.search(src):
            return {"repaired": False,
                    "reason": ("router already defined"
                               if _ROUTER_DEF_RE.search(src)
                               else "no @router use to support")}
        lines = src.split("\n")
        last_import = max((i for i, l in enumerate(lines)
                           if l.startswith("import ") or l.startswith("from ")), default=-1)
        # #979: land after the last import STATEMENT, not the last import LINE. 26 of the
        # corpus's custom_routes.py end their imports with an unclosed `from models import (`
        # — inserting at line+1 puts `router = APIRouter()` INSIDE the parentheses, a
        # SyntaxError that kills the backend outright. Same shape as #970 one language over:
        # there the generated source was minified, here it is parenthesised, and both break a
        # rule that counts lines instead of statements.
        #
        # Latent rather than observed: the repair only runs when the file USES `router.`
        # without defining it, which is rare. It is a landmine precisely because it fires in
        # an already-broken state, where a SyntaxError reads as the lane's own fault.
        if last_import >= 0:
            _bal = 0
            for _i in range(last_import, len(lines)):
                _bal += lines[_i].count("(") - lines[_i].count(")")
                if _bal <= 0:
                    last_import = _i
                    break
            else:
                last_import = len(lines) - 1
        lines[last_import + 1:last_import + 1] = [
            "", "from fastapi import APIRouter", "router = APIRouter()", ""]
        _write_py_995(p, "\n".join(lines), what="repair_custom_routes_router_prologue")
        out["repaired"] = True
    except Exception:
        pass
    return out


def repair_auth_import_paths(backend_dir) -> Dict[str, object]:
    """FIX #48: lanes import the canonical auth dependency from the WRONG module —
    ``from oauth_routes import get_current_user`` (oauth_routes only exposes
    ``build_router``) — so the backend crashes on startup (ImportError) and
    backend_health fails forever (run #12 / run #18). The framework scaffolds the real
    ``get_current_user`` in ``auth_dependency.py``; repoint every wrong-module import at
    it. Unlike ``repair_backend_auth_dependency`` (which only rewrites a placeholder
    DEFINITION), this normalizes IMPORT statements, so it fixes the run #18 case where
    the route files only import (wrong) and define nothing. Best-effort, idempotent.

    Note: ``get_current_user_id`` (a different local helper some lanes invent) is OUT of
    scope — it is a local def with its own signature, not an ImportError; leave it."""
    try:
        be = Path(backend_dir)
        # The canonical home must exist (the skeleton writes it). Without it there is no
        # safe target to repoint to — guard rather than create a divergent one here.
        if not (be / "auth_dependency.py").exists():
            return {"repaired": False, "reason": "no auth_dependency.py"}
        rewritten: List[str] = []
        for p in be.glob("*.py"):
            if p.name in _AUTH_INFRA_FILES:
                continue
            src = p.read_text(encoding="utf-8", errors="ignore")
            if "get_current_user" not in src:
                continue
            new = _normalize_auth_imports_in_src(src)
            if new != src:
                _write_py_995(p, new, what="repair_auth_import_paths")
                rewritten.append(p.name)
        # #1149c: an empty `rewritten` is a healthy no-op — say which kind.
        if not rewritten:
            return {"repaired": False, "rewritten": rewritten,
                    "reason": "no wrong-module get_current_user import"}
        return {"repaired": bool(rewritten), "rewritten": rewritten}
    except Exception as exc:
        return {"repaired": False, "error": f"{type(exc).__name__}: {exc}"}


# A handler that fake-parses a ``user:<id>`` token instead of decoding the JWT.
_FAKE_PARTS_MARKER = '!= "user"'
_FAKE_SPLIT_RE = re.compile(r'parts\s*=\s*(\w+)\.split\(\s*":"\s*(?:,\s*1\s*)?\)')
_JWT_SUB_HELPER = '''

def _framework_jwt_sub(token):
    """Validate the AS-minted RS256 bearer JWT and return its subject (the user id).
    Injected (instagram MM run #12) to repair handlers that fake-parsed a 'user:<id>'
    token instead of decoding the real JWT — every authed endpoint 401'd because the
    AS mints an ``eyJ…`` JWT, never ``user:<id>``."""
    import jwt as _pyjwt
    try:
        from jwt_manager import JWTManager as _JM, ALGORITHM as _ALG
        _pp = _JM().public_pem
        _pem = _pp() if callable(_pp) else _pp
    except Exception:
        _pem, _ALG = None, "RS256"
    if not _pem:
        raise HTTPException(status_code=401, detail="auth unavailable")
    try:
        _claims = _pyjwt.decode(token, _pem, algorithms=[_ALG], options={"verify_aud": False})
    except Exception:
        raise HTTPException(status_code=401, detail="invalid token")
    _sub = _claims.get("sub")
    if _sub is None:
        raise HTTPException(status_code=401, detail="invalid token subject")
    return int(_sub)
'''


def repair_inline_token_auth(backend_dir) -> Dict[str, object]:
    """ROOT FIX (instagram MM run #12, 2026-06-09): the lane fake-parsed the bearer
    token INLINE across handlers — ``parts = raw_token.split(":", 1); if parts[0] !=
    "user": raise 'invalid token'`` — so it expected ``user:<id>`` and rejected the real
    RS256 JWT. There is no shared get_current_user to rewrite (the existing auth repair
    can't catch it). Minimal, structure-preserving repair: replace the fake
    ``<tok>.split(":")`` with ``["user", str(_framework_jwt_sub(<tok>))]`` (an injected
    helper that decodes the real JWT) so the rest of each handler's logic (``parts[0] ==
    "user"``, ``int(parts[1])``) yields the true user id. Idempotent; best-effort."""
    try:
        be = Path(backend_dir)
        main_py = be / "main.py"
        if not main_py.exists():
            return {"fixed": 0, "reason": "no main.py"}
        src = main_py.read_text(encoding="utf-8", errors="ignore")
        if _FAKE_PARTS_MARKER not in src or "_framework_jwt_sub(" in src:
            # #1149: name the two very different causes apart — the lane never wrote
            # the fake shape (healthy) vs. we already repaired it (also healthy).
            return {"fixed": 0, "reason": ("already repaired"
                                          if "_framework_jwt_sub(" in src
                                          else "no inline fake-token parse")}
        new_src, n = _FAKE_SPLIT_RE.subn(
            r'parts = ["user", str(_framework_jwt_sub(\1))]', src)
        if n == 0:
            return {"fixed": 0, "reason": "marker present but no rewritable split site"}
        # inject the helper after the import block (before the first def/class/@/app=)
        lines = new_src.splitlines(keepends=True)
        insert_at = 0
        for i, ln in enumerate(lines):
            s = ln.lstrip()
            if s.startswith(("def ", "class ", "@", "app =")):
                insert_at = i
                break
            if s.startswith(("import ", "from ")) or s.strip() == "" or s.startswith("#"):
                insert_at = i + 1
        new_src = "".join(lines[:insert_at]) + _JWT_SUB_HELPER + "".join(lines[insert_at:])
        _write_py_995(main_py, new_src, what="repair_inline_token_auth")
        return {"fixed": n}
    except Exception as exc:
        return {"fixed": 0, "error": f"{type(exc).__name__}: {exc}"}


_AUTH_MIDDLEWARE = '''

# === BY-CONSTRUCTION auth enforcement (FIX #47, instagram MM run #16) ===
# Some lanes write business handlers with NO auth at all (e.g. ``db.query(User).first()``
# to fetch "the current user"), so an endpoint returns 200 with no token → api_smoke
# ``auth_enforced_401`` fails and the milestone stalls. This middleware enforces a valid
# RS256 bearer token on every /api/ business route (the AS mints them); /auth/*, /api/v1/*
# infra, health/docs, and the OAuth/JWKS surface stay public. Handlers that ALSO depend on
# get_current_user are unaffected (the inner check just re-validates).
#
# #1202kh: ...EXCEPT the routes the CONTRACT declares public. #47's blanket rule predates the
# per-endpoint `auth_required` the rest of the framework now runs on, and the three layers had
# drifted apart: the projector builds a contract-public handler with NO guard, #1202ih stopped
# the validator demanding a 401 from one, and this middleware denied it anyway. On tiktok-r114
# the feed endpoint was registered auth_required=false and projected with no user dependency,
# and an unauthenticated request to the running container still came back 401 -- so the
# logged-out landing page never loaded. 77 of the 153 corpus runs declare at least one public
# /api/ endpoint (451 in total, 412 of them GET) and every one was denied here. That is the
# mechanism behind the top ui_flow failure signature (401, 21 of 54 recent failures).
#
# FAIL CLOSED: the list below is emitted by the skeleton from the SAME auth decision the
# handler was built with, so it holds only routes projected with no actor. Absent -- including
# a main.py the skeleton did not render (the repair_auth_enforcement_middleware heal path) --
# leaves the set empty and this guard exactly as #47 wrote it.
import jwt as _fw_jwt
import re as _fw_re
from fastapi.responses import JSONResponse as _FWJSONResponse

try:
    _FW_PUBLIC_API_1202KH
except NameError:
    _FW_PUBLIC_API_1202KH = []
_FW_PUBLIC_RE_1202KH = [
    (str(_m).upper(),
     _fw_re.compile("^" + _fw_re.sub(r"\\\\{[^}]*\\\\}", "[^/]+", _fw_re.escape(str(_p).rstrip("/") or "/")) + "/?$"))
    for _m, _p in _FW_PUBLIC_API_1202KH]


def _fw_contract_public_1202kh(method, path):
    """The CONTRACT says this exact (method, path) needs no token."""
    m = str(method).upper()
    return any(m == _m and _rx.match(path) for _m, _rx in _FW_PUBLIC_RE_1202KH)
try:
    from jwt_manager import JWTManager as _FWJM, ALGORITHM as _FWALG
    _fw_pp = _FWJM().public_pem
    _FW_PEM = _fw_pp() if callable(_fw_pp) else _fw_pp
except Exception:
    _FW_PEM, _FWALG = None, "RS256"


@app.middleware("http")
async def _framework_auth_guard(request, call_next):
    # #1190: publish the caller's ACTIVE sub-entity for this request. The frontend sends
    # `X-Profile-ID` on every call and the server has never read it, so every profile of one
    # account resolved to the same owner value and read the others' rows (measured on
    # netflix-r22's delivered release). Only a ContextVar is set here — `_fw_owner_val`
    # decides whether to honour it, and only after `_fw_owns` confirms the caller owns that
    # sub-entity, so this can never widen access. Best-effort: a missing ContextVar (an
    # older skeleton) or any failure leaves resolution exactly as it was.
    try:
        _FW_PROFILE_CTX_1190.set((request.headers.get("x-profile-id") or "").strip() or None)
    except Exception:
        pass
    p = request.url.path
    public = (
        p in ("/", "/health", "/openapi.json", "/docs", "/redoc", "/favicon.ico")
        or p.startswith("/auth/") or p.startswith("/api/v1/")
        or p.startswith("/.well-known") or p.startswith("/oauth")
        # #64 (outlook run-48, live): the frontend's api.js prefixes EVERY call
        # with /api, so its login/register hit /api/auth/login|register — which
        # the guard walled (only /auth/* was public under the /api umbrella) →
        # 401 on the UI login → auth_ok=False + login-wall on every protected
        # page even though the API /auth/login 200s. The unauthenticated auth
        # entry points must be public under BOTH prefixes; /api/auth/me stays
        # guarded by its own Depends(get_current_user).
        # #235 (tiktok r25, live): the contract's bootstrap may use any SYNONYM of
        # login/register — r25 declared POST /api/auth/signup, which the literal
        # whitelist walled → 401 on the token-minting step of every chain, and the
        # lane's fix was overwritten each tick by this framework-owned skeleton
        # (108-min livelock). An auth ENTRY point (mints/refreshes credentials,
        # terminal segment below) is public by construction under /api/auth/;
        # /api/auth/me and anything else stays guarded.
        or (p.startswith("/api/auth/") and p.rstrip("/").rsplit("/", 1)[-1] in (
            "login", "register", "signup", "signin", "token", "refresh", "logout"))
    )
    # #1202kh: the contract's own answer, checked here so the guard cannot contradict the
    # handler the framework built from the same record.
    if not public and _fw_contract_public_1202kh(request.method, p):
        public = True
    if p.startswith("/api/") and not public and request.method != "OPTIONS":
        ok = False
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer ") and _FW_PEM:
            try:
                _fw_claims = _fw_jwt.decode(
                    auth.split(" ", 1)[1].strip(), _FW_PEM,
                    algorithms=[_FWALG], options={"verify_aud": False})
                ok = True
                # FIX #109 (instagram run-28, live): lanes routinely write handlers
                # that read request.state.user_id, believing the middleware injects
                # it (their own comments say so) — it never did, so those handlers
                # 401'd VALID tokens. Make the convention true: expose the sub claim
                # (int-coerced when numeric) on request.state.
                try:
                    _fw_sub = _fw_claims.get("sub")
                    request.state.user_id = (int(_fw_sub) if str(_fw_sub).isdigit()
                                             else _fw_sub)
                    request.state.user = {"id": request.state.user_id}
                except Exception:
                    pass
            except Exception:
                ok = False
        if not ok:
            return _FWJSONResponse(status_code=401, content={"detail": "missing or invalid token"})
    return await call_next(request)
# === end auth enforcement ===
'''


def repair_auth_enforcement_middleware(backend_dir) -> Dict[str, object]:
    """ROOT FIX (instagram MM run #16, 2026-06-09): a lane wrote business handlers with NO
    auth — ``GET /api/users/me`` did ``db.query(User).order_by(User.id).first()`` and
    returned 200 with no token → api_smoke ``auth_enforced_401`` failed → milestone stalled
    (the gate correctly refused to ship an auth-bypassed app). There was no get_current_user
    to rewrite, so inject a FastAPI middleware that enforces a valid bearer JWT on every
    /api/ business route. Idempotent; only when the AS (jwt_manager) is present."""
    try:
        be = Path(backend_dir)
        main_py = be / "main.py"
        if not main_py.exists() or not (be / "jwt_manager.py").exists():
            return {"injected": False, "reason": "no main.py / no AS"}
        src = main_py.read_text(encoding="utf-8")
        if "_framework_auth_guard" in src:
            return {"injected": False, "reason": "already present"}
        if "app = FastAPI" not in src and "app=FastAPI" not in src:
            return {"injected": False, "reason": "no FastAPI app"}
        # insert after the app's CORS/middleware setup → just before the first route, or
        # before the main guard if no route yet.
        m = re.search(r"^@app\.(?:get|post|put|delete|patch)\(", src, re.M)
        if m:
            at = m.start()
            new_src = src[:at] + _AUTH_MIDDLEWARE.lstrip("\n") + "\n\n" + src[at:]
        else:
            marker = 'if __name__ == "__main__":'
            idx = src.rfind(marker)
            new_src = (src[:idx] + _AUTH_MIDDLEWARE + "\n\n" + src[idx:]) if idx != -1 \
                else src.rstrip() + "\n" + _AUTH_MIDDLEWARE
        _write_py_995(main_py, new_src, what="repair_auth_enforcement_middleware")
        return {"injected": True}
    except Exception as exc:
        return {"injected": False, "error": f"{type(exc).__name__}: {exc}"}


_INTEGRITY_HANDLER = '''

# === BY-CONSTRUCTION IntegrityError → REST-status mapping (FIX #82, instagram run-2) ===
# Lane-written action handlers (POST /api/users/{id}/follow) INSERT a row whose FK comes
# from the path WITHOUT checking the target exists, so a missing target escapes as a raw
# 500 (psycopg ForeignKeyViolation) — but verifier chains tolerate [..., 404] on by-id
# actions, so the 500 wedges business_chain forever on a semantically-reasonable app.
# Map DB integrity errors to the statuses REST (and the chains) expect:
# foreign-key violation (23503) → 404, unique violation (23505) → 409, other → 400.
from fastapi.responses import JSONResponse as _FWIntegrityJSON
try:
    from sqlalchemy.exc import IntegrityError as _FWIntegrityError
except Exception:
    _FWIntegrityError = None

if _FWIntegrityError is not None:
    @app.exception_handler(_FWIntegrityError)
    async def _framework_integrity_error_handler(request, exc):
        _orig = getattr(exc, "orig", None)
        # psycopg2 carries pgcode; psycopg 3 (the pyproject driver) carries sqlstate.
        code = (getattr(_orig, "pgcode", None) or getattr(_orig, "sqlstate", None) or "")
        text = str(_orig or exc).lower()
        if code == "23503" or "foreign key" in text:
            status, detail = 404, "referenced resource not found"
        elif code == "23505" or "unique constraint" in text or "duplicate key" in text:
            status, detail = 409, "duplicate resource"
        elif code == "23502" or "null value in column" in text:
            # FIX #411 (netflix r7/r8, live): a NOT-NULL violation names a REQUIRED
            # request field the client OMITTED (r8: POST /api/my-list with no title_id).
            # Surfacing WHICH column is legitimate required-field feedback — a 422 would
            # say the same — NOT the FK/constraint/table internals #282 keeps generic. The
            # verifier's chain (and the lane) can then auto-fill that field and retry
            # instead of wedging business_chain on a permanently-empty create body.
            import re as _fw_re
            _nn = _fw_re.search(r'null value in column "?([a-z_][a-z0-9_]*)', text)
            status, detail = 400, (
                'null value in column "%s" violates not-null constraint' % _nn.group(1)
                if _nn else "integrity constraint violated")
        else:
            status, detail = 400, "integrity constraint violated"
        # FIX #282 (tiktok r67, live): the mapping above is right, but returning ONLY the
        # fixed prose destroyed WHICH constraint failed. r67: POST /api/videos/1/like →
        # 404 "referenced resource not found" while GET /api/videos/1 → 200 — the video
        # EXISTED; the FK that actually failed was the OTHER column. Nothing said so: not
        # the response, not the container log (verified by hand — grep for foreign key /
        # IntegrityError / 23503 came back EMPTY). So the lane read "referenced resource
        # not found" as "the video is missing", chased a video that was right there, and
        # the run burned 7 post-cap cycles → FAIL-FAST abort. The driver's own message
        # names the constraint/table/column: log it. The RESPONSE stays byte-identical —
        # no contract change, no DB internals leaked to API clients — diagnosis goes to
        # the server log the lane can actually read. Best-effort: never let a logging
        # failure turn a correctly-mapped 404 into a 500.
        try:
            import logging as _fw_logging
            _fw_logging.getLogger("app.integrity").error(
                "IntegrityError on %s %s -> %s: code=%s orig=%s",
                getattr(request, "method", "?"),
                getattr(getattr(request, "url", None), "path", "?"),
                status, code or "?", _orig or exc)
        except Exception:
            pass
        return _FWIntegrityJSON(status_code=status, content={"detail": detail})

# Audit rank-4 (whack-a-mole eradication): a DataError is a value that doesn't fit the
# column TYPE — InvalidDatetimeFormat, invalid integer/numeric text, value out of range.
# It is CLIENT-DATA (a chain POSTing a bad datetime/int), not a server fault, but without
# a handler it escaped the write handler's try/except as a raw 500 — in NO chain's expect
# list -> business_chain wedge, exactly like the FK-500 that #82 fixed. _coerce_body now
# fixes the common int/numeric/bool cases up-front; this maps whatever is left to 400,
# symmetric with the IntegrityError mapping. Response prose is fixed (no DB internals
# leaked); the driver detail goes to the log the owning lane can read.
try:
    from sqlalchemy.exc import DataError as _FWDataError
except Exception:
    _FWDataError = None

def _fw_data_error_hint_1202ma(orig) -> str:
    """#1202ma: the part of a driver DataError a caller can ACT on, without the value.

    The response prose here is deliberately fixed ("no DB internals leaked") and the driver
    text goes to `logging.getLogger("app.integrity")` — "the log the owning lane can read".
    Measured across four tiktok runs (r117/r119/r120/r121): `docker_logs` was called ZERO
    times in any of them. Nobody has ever read that log. Meanwhile r121's test-user filed
    `POST /api/feed -> 400 ({"detail":"invalid field value"})` six times with nothing to act
    on.

    So the actionable half comes back in a SECOND field. Postgres says "invalid input syntax
    for type integer: \"abc\"" — the part before the colon names the type and is safe; the
    part after is the value and stays out. Bounded, single-line, and never raises: this runs
    on an already-failing path.
    """
    try:
        _t = str(orig or "").strip().splitlines()[0]
        for _cut in ('"', "'"):
            _i = _t.find(_cut)
            if _i > 0:
                _t = _t[:_i]
        _t = _t.rstrip(" :,")
        return _t[:120] or "no driver detail"
    except Exception:
        return "no driver detail"


if _FWDataError is not None:
    @app.exception_handler(_FWDataError)
    async def _framework_data_error_handler(request, exc):
        try:
            import logging as _fw_logging
            _fw_logging.getLogger("app.integrity").error(
                "DataError on %s %s -> 400: orig=%s",
                getattr(request, "method", "?"),
                getattr(getattr(request, "url", None), "path", "?"),
                getattr(exc, "orig", None) or exc)
        except Exception:
            pass
        return _FWIntegrityJSON(status_code=400, content={
            "detail": "invalid field value",
            # #1202ma: name the TYPE that rejected the value. `detail` is unchanged on
            # purpose — chain_executor matches it as a substring — and the value itself is
            # still withheld, so the "no DB internals leaked" rule above holds.
            "field_hint": _fw_data_error_hint_1202ma(getattr(exc, "orig", None) or exc)})
# === end integrity mapping ===
'''


def repair_integrity_error_handler(backend_dir) -> Dict[str, object]:
    """FIX #82 (instagram-core-di run-2, 2026-07-06, live): the business_chain hardcoded a
    by-id action on a row that doesn't exist (POST /api/users/1001/follow) and correctly
    tolerated a 404 — but the lane handler INSERTs the path id as an FK unchecked, so the
    DB's ForeignKeyViolation surfaced as a raw 500 (in NO expect list) → validation wedged
    7 post-cap cycles → STUCK abort. Inject a framework-owned global IntegrityError
    exception handler into main.py (23503→404, 23505→409, other→400). Idempotent,
    best-effort, never raises."""
    try:
        be = Path(backend_dir)
        main_py = be / "main.py"
        if not main_py.exists():
            return {"injected": False, "reason": "no main.py"}
        src = main_py.read_text(encoding="utf-8")
        if "_framework_integrity_error_handler" in src:
            return {"injected": False, "reason": "already present"}
        if "app = FastAPI" not in src and "app=FastAPI" not in src:
            return {"injected": False, "reason": "no FastAPI app"}
        m = re.search(r"^@app\.(?:get|post|put|delete|patch)\(", src, re.M)
        if m:
            at = m.start()
            new_src = src[:at] + _INTEGRITY_HANDLER.lstrip("\n") + "\n\n" + src[at:]
        else:
            marker = 'if __name__ == "__main__":'
            idx = src.rfind(marker)
            new_src = (src[:idx] + _INTEGRITY_HANDLER + "\n\n" + src[idx:]) if idx != -1 \
                else src.rstrip() + "\n" + _INTEGRITY_HANDLER
        _write_py_995(main_py, new_src, what="repair_integrity_error_handler")
        return {"injected": True}
    except Exception as exc:
        return {"injected": False, "error": f"{type(exc).__name__}: {exc}"}


def repair_custom_routes_db_handle(backend_dir) -> Dict[str, object]:
    """FIX #86 (instagram run-7 M3 STUCK, live traceback): custom_routes.py defined its
    OWN ``get_db()`` yielding a RAW psycopg connection, shadowing the framework's
    SQLAlchemy Session — while its business handlers were written SQLAlchemy-style
    (``db.execute(text(...)).mappings()``), so psycopg's _convert_query raised
    ``TypeError: TextClause has no len()`` → unfollow/explore 500 → the validation
    wedged 7 post-cap cycles. Rewrite the lane's psycopg get_db into a delegation to
    the framework's database.get_db (whose _Session serves BOTH styles: native
    TextClause/ORM, .cursor(), and — with the FIX #86 execute shim — plain-str SQL).
    AST-precise, idempotent, best-effort, never raises."""
    import ast
    try:
        be = Path(backend_dir)
        cr = be / "custom_routes.py"
        if not cr.exists():
            return {"repaired": False, "reason": "no custom_routes.py"}
        src = cr.read_text(encoding="utf-8")
        if "_framework_get_db" in src:
            return {"repaired": False, "reason": "already delegated"}
        tree = ast.parse(src)
        target = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "get_db":
                body_src = ast.get_source_segment(src, node) or ""
                if "psycopg" in body_src and ".connect(" in body_src:
                    target = node
                    break
        if target is None:
            return {"repaired": False, "reason": "no lane psycopg get_db"}
        lines = src.splitlines(keepends=True)
        indent = " " * target.col_offset
        repl = (
            f"{indent}def get_db():\n"
            f"{indent}    # framework-normalized (FIX #86): the canonical Session serves both\n"
            f"{indent}    # SQLAlchemy-style and raw psycopg-style handlers; a lane-local raw\n"
            f"{indent}    # psycopg connection breaks every text()/.mappings() call with a 500.\n"
            f"{indent}    from database import get_db as _framework_get_db\n"
            f"{indent}    yield from _framework_get_db()\n"
        )
        start = target.lineno - 1
        end = target.end_lineno
        new_src = "".join(lines[:start]) + repl + "".join(lines[end:])
        ast.parse(new_src)   # never write a syntax error
        _write_py_995(cr, new_src, what="repair_custom_routes_db_handle")
        return {"repaired": True}
    except Exception as exc:
        return {"repaired": False, "error": f"{type(exc).__name__}: {exc}"}


# Framework-owned backend files a lane repair must never rewrite.
_FRAMEWORK_OWNED_BACKEND = {
    "auth_dependency.py", "jwt_manager.py", "main.py", "database.py",
    "oauth_routes.py", "seed_loader.py"}


def repair_jwt_decode_audience(backend_dir) -> Dict[str, object]:
    """FIX #118 (instagram run-33, 2026-07-08, root PROVEN in-container): the framework
    AS mints proper OAuth2 RS256 tokens WITH an ``aud`` claim, and PyJWT REJECTS any
    aud-carrying token when the caller passes no ``audience=`` (InvalidAudienceError).
    A lane that writes its OWN guard — ``jwt.decode(token, key, algorithms=[ALG])`` —
    therefore 401s EVERY valid token ("Invalid token") and business_chain wedges on a
    healthy app (GET /api/feed → 401; decode-with-audience returned the sub fine).
    Same class as #109: the lane's belief about auth is foreseeably wrong, so the
    framework owns the floor. Append ``options={"verify_aud": False}`` to lane
    ``jwt.decode`` calls that verify a signature but pass neither ``audience=`` nor
    ``options=`` — signature verification is untouched; audience enforcement stays the
    framework guard's job (auth_dependency verifies aud correctly). AST-located,
    surgical text insertion (no reformat), bottom-up (positions stay valid),
    idempotent, best-effort, never raises; framework-owned files are never touched."""
    import ast
    result: Dict[str, object] = {"repaired": []}
    try:
        be = Path(backend_dir)
        if not be.is_dir():
            return result
        touched: List[str] = []
        for f in sorted(be.glob("*.py")):
            if f.name in _FRAMEWORK_OWNED_BACKEND:
                continue
            try:
                src = f.read_text(encoding="utf-8")
                tree = ast.parse(src)
            except Exception:
                continue
            sites = []
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and node.func.attr == "decode"
                        and isinstance(node.func.value, ast.Name)
                        and node.func.value.id in ("jwt", "pyjwt")):
                    continue
                kwnames = {k.arg for k in node.keywords if k.arg}
                if "audience" in kwnames or "options" in kwnames:
                    continue  # already audience-aware / introspection decode
                # only a VERIFYING decode (key present) is a guard worth repairing
                if not ("algorithms" in kwnames or len(node.args) >= 2):
                    continue
                if node.end_lineno is None or node.end_col_offset is None:
                    continue
                sites.append((node.end_lineno, node.end_col_offset))
            if not sites:
                continue
            lines = src.splitlines(keepends=True)
            for (el, ec) in sorted(sites, reverse=True):
                line = lines[el - 1]
                # ec is just past the closing ')': insert before it
                lines[el - 1] = (line[:ec - 1]
                                 + ', options={"verify_aud": False}'
                                 + line[ec - 1:])
            new_src = "".join(lines)
            try:
                ast.parse(new_src)   # never write a syntax error
            except Exception:
                continue
            _write_py_995(f, new_src, what="repair_jwt_decode_audience")
            touched.append(f.name)
        result["repaired"] = touched
    except Exception as exc:  # never break generation/validation
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def _route_param_annotations(src: str) -> Dict[tuple, Dict[str, str]]:
    """(method, path-template) → {param_name: 'int'|'str'} for every decorated route
    whose decorator is ``@<obj>.<verb>('<path>')``. Best-effort; ignores routes whose
    annotations aren't simple Names."""
    import ast
    out: Dict[tuple, Dict[str, str]] = {}
    try:
        tree = ast.parse(src)
    except Exception:
        return out
    verbs = {"get", "post", "put", "patch", "delete"}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if not (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)
                    and dec.func.attr in verbs and dec.args
                    and isinstance(dec.args[0], ast.Constant)
                    and isinstance(dec.args[0].value, str)):
                continue
            path = dec.args[0].value
            params = {s[1:-1] for s in path.strip("/").split("/")
                      if s.startswith("{") and s.endswith("}")}
            if not params:
                continue
            anns: Dict[str, str] = {}
            for arg in list(node.args.args) + list(node.args.kwonlyargs):
                if (arg.arg in params and isinstance(arg.annotation, ast.Name)
                        and arg.annotation.id in ("int", "str")):
                    anns[arg.arg] = arg.annotation.id
            if anns:
                out[(dec.func.attr, path)] = anns
    return out


def _narrowing_is_evidenced_1202pk(models_src: str, path: str, param: str) -> bool:
    """#1202pk: may #119 rewrite ``<param>: str`` to ``int`` on ``path``?

    Widening (int -> str) never breaks a request; narrowing 422s every id that is
    not a number. r125's `/api/videos/{video_id}/like` was projected with ``int``
    while ``videos.id`` is a String uuid PK (its twin ``video`` is the integer
    one); #119 narrowed it 28 times, the lane restored ``str`` each time, and
    ``str`` is what shipped. Narrow only when models.py says the resource table
    (the segment before the first path param, exact name first) has an integer PK
    and the param is not named after one of its textual columns."""
    import ast as _ast
    try:
        tree = _ast.parse(models_src)
    except Exception:
        return False
    int_pk, known = set(), set()
    for node in tree.body:
        if not isinstance(node, _ast.ClassDef):
            continue
        tname, pk_int = None, False
        for st in node.body:
            seg = _ast.get_source_segment(models_src, st) or ""
            m = re.search(r"__tablename__\s*=\s*['\"]([^'\"]+)", seg)
            if m:
                tname = m.group(1).lower()
            if "primary_key" in seg and re.search(r"\b(Integer|BigInteger|SmallInteger)\b", seg):
                pk_int = True
        if tname:
            known.add(tname)
            if pk_int:
                int_pk.add(tname)
    segs = [x for x in path.strip("/").split("/") if x and x != "api"]
    idx = next((i for i, x in enumerate(segs) if x.startswith("{")), 0)
    if idx < 1:
        return False
    res = segs[idx - 1].lower().replace("-", "_")
    cands = [res] if res in known else [c for c in (res.rstrip("s"), res + "s") if c in known]
    if not cands:
        return False
    table = cands[0]
    if param in _string_columns_1104(models_src).get(table, set()):
        return False
    return table in int_pk


def repair_custom_routes_param_types_vs_projection(backend_dir) -> Dict[str, object]:
    """FIX #119 (instagram run-35 M4 STUCK, 2026-07-09, live-diagnosed): the lane's
    custom GET /api/users/{username} annotated the param ``int`` while the contract
    (and the framework PROJECTION in main.py) is string-keyed — the custom router
    overrides the projected route by design, so every real username 422/500'd and the
    run aborted on business_endpoints_reachable. FIX #106's table-PK heuristic covers
    only the ``str``-on-integer-PK direction; the PROJECTED signature is the
    contract-derived source of truth for BOTH directions. For each custom route whose
    (method, path-template) EXACTLY matches a projected route, rewrite any path-param
    annotation that differs from the projection's. AST-anchored surgical edit
    (bottom-up, no reformat), parse-guarded, idempotent, best-effort, never raises."""
    import ast
    try:
        be = Path(backend_dir)
        cr, mn = be / "custom_routes.py", be / "main.py"
        if not cr.exists() or not mn.exists():
            return {"fixed": 0, "reason": "missing files"}
        projected = _route_param_annotations(mn.read_text(encoding="utf-8"))
        if not projected:
            return {"fixed": 0, "reason": "no projected routes"}
        src = cr.read_text(encoding="utf-8")
        try:
            tree = ast.parse(src)
        except Exception:
            return {"fixed": 0, "reason": "custom_routes unparseable"}
        verbs = {"get", "post", "put", "patch", "delete"}
        try:
            _models_src_1202pk = (be / "models.py").read_text(encoding="utf-8")
        except Exception:
            _models_src_1202pk = ""   # no evidence -> never narrow (#1202pk)
        edits = []  # (lineno, col0, col1, old, new)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for dec in node.decorator_list:
                if not (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)
                        and dec.func.attr in verbs and dec.args
                        and isinstance(dec.args[0], ast.Constant)
                        and isinstance(dec.args[0].value, str)):
                    continue
                want = projected.get((dec.func.attr, dec.args[0].value))
                if not want:
                    continue
                for arg in list(node.args.args) + list(node.args.kwonlyargs):
                    tgt = want.get(arg.arg)
                    if (tgt and isinstance(arg.annotation, ast.Name)
                            and arg.annotation.id in ("int", "str")
                            and arg.annotation.id != tgt):
                        if tgt == "int" and not _narrowing_is_evidenced_1202pk(
                                _models_src_1202pk, dec.args[0].value, arg.arg):
                            continue  # #1202pk: unevidenced str -> int narrowing
                        edits.append((arg.annotation.lineno - 1,
                                      arg.annotation.col_offset,
                                      arg.annotation.end_col_offset,
                                      arg.annotation.id, tgt))
        if not edits:
            return {"fixed": 0}
        lines = src.splitlines(keepends=True)
        for (ln, c0, c1, old, new) in sorted(edits, reverse=True):
            if lines[ln][c0:c1] == old:
                lines[ln] = lines[ln][:c0] + new + lines[ln][c1:]
        new_src = "".join(lines)
        ast.parse(new_src)   # never write a syntax error
        _write_py_995(cr, new_src, what="repair_custom_routes_param_types_vs_projection")
        return {"fixed": len(edits)}
    except Exception as exc:
        return {"fixed": 0, "error": f"{type(exc).__name__}: {exc}"}


def _string_columns_1104(models_src: str) -> Dict[str, set]:
    """``{tablename: {column names whose type is textual}}`` from models.py.

    #106 only asks models.py whether a table's PK is an integer. The reverse
    direction needs finer evidence — whether the COLUMN a path param is named
    after holds text — so that ``/api/users/{username}`` can be judged on
    ``users.username`` rather than on ``users.id``.
    """
    import ast as _ast
    import re as _re2
    _TEXTUAL = ("String", "Text", "Unicode", "VARCHAR", "CHAR", "UUID")
    out: Dict[str, set] = {}
    try:
        tree = _ast.parse(models_src)
    except Exception:
        return out
    for node in tree.body:
        if not isinstance(node, _ast.ClassDef):
            continue
        tname, cols = None, set()
        for st in node.body:
            seg = _ast.get_source_segment(models_src, st) or ""
            m = _re2.search(r"__tablename__\s*=\s*['\"]([^'\"]+)", seg)
            if m:
                tname = m.group(1).lower()
            if (isinstance(st, _ast.Assign) and "Column(" in seg
                    and st.targets and isinstance(st.targets[0], _ast.Name)
                    and any(_re2.search(r"\b%s\b" % t, seg) for t in _TEXTUAL)):
                cols.add(st.targets[0].id)
        if tname and cols:
            out[tname] = cols
    return out


def repair_custom_routes_param_types(backend_dir) -> Dict[str, object]:
    """FIX #106 (instagram run-23, live): the lane annotated a by-id path param as ``str``
    while the column is an INTEGER PK → SQLAlchemy compared ``posts.id = '20'::VARCHAR`` →
    Postgres 'operator does not exist: integer = character varying' → 500 on EVERY by-id
    read. And by DESIGN the lane's by-id GET shadows the safe projected read (the
    isolation tradeoff in _custom_route_overrides_projected), so the type bug wedged the
    run. Deterministic repair: parse the framework-generated models.py for integer-PK
    tables, then rewrite ``<param>: str`` to ``<param>: int`` on every custom route whose
    path's resource segment maps to such a table. AST-anchored, idempotent, best-effort."""
    import ast
    import re as _re
    try:
        be = Path(backend_dir)
        cr, mp = be / "custom_routes.py", be / "models.py"
        if not cr.exists() or not mp.exists():
            return {"fixed": 0, "reason": "missing files"}
        int_pk_tables: set = set()
        mtree = ast.parse(mp.read_text(encoding="utf-8"))
        for node in ast.walk(mtree):
            if not isinstance(node, ast.ClassDef):
                continue
            tname, pk_int = None, False
            for st in node.body:
                seg = ast.get_source_segment(mp.read_text(encoding="utf-8"), st) or ""
                if "__tablename__" in seg:
                    m = _re.search(r"__tablename__\s*=\s*['\"]([^'\"]+)", seg)
                    if m:
                        tname = m.group(1).lower()
                if "primary_key" in seg and _re.search(r"\b(Integer|BigInteger)\b", seg):
                    pk_int = True
            if tname and pk_int:
                int_pk_tables.add(tname)
        # #1104: NOT an early return any more. The reverse flip below is judged on
        # textual columns and the projected signature, neither of which needs an
        # integer PK anywhere in the schema — bailing here would skip it entirely.
        _string_cols = _string_columns_1104(mp.read_text(encoding="utf-8"))
        if not int_pk_tables and not _string_cols:
            return {"fixed": 0, "reason": "no typed columns"}

        src = cr.read_text(encoding="utf-8")
        tree = ast.parse(src)
        lines = src.splitlines(keepends=True)
        # #338: defer to #119 wherever main.py PROJECTS the route. This guess
        # (`the segment before the first path param names the table, so that
        # param is its PK`) is false for a NATURAL KEY: on
        # /api/users/{username}/follow it reads `users`, sees users.id is an
        # INTEGER pk, and rewrites `username: str` -> `username: int`, which
        # 422s on every real username. r92's repo carries the flip and the lane
        # having to undo it (35022b3 `-username: int` / `+username: str`).
        # Where a route IS projected, the projected signature is authoritative
        # and this heuristic can only corrupt it; where it is NOT projected,
        # this stays the only signal and still applies (the run-23 wedge).
        _projected_routes: set = set()
        _projected_param_types: Dict[tuple, Dict[str, str]] = {}
        try:
            _mn = be / "main.py"
            if _mn.exists():
                _projected_param_types = _route_param_annotations(
                    _mn.read_text(encoding="utf-8"))
                _projected_routes = set(_projected_param_types.keys())
        except Exception:
            _projected_routes, _projected_param_types = set(), {}
        fixed = 0
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            # route path from a @router.<verb>('<path>') decorator
            path = None
            _verb = None
            for dec in node.decorator_list:
                if (isinstance(dec, ast.Call) and dec.args
                        and isinstance(dec.args[0], ast.Constant)
                        and isinstance(dec.args[0].value, str)):
                    path = dec.args[0].value
                    if isinstance(dec.func, ast.Attribute):
                        _verb = dec.func.attr
                    break
            if not path:
                continue
            segs = [s for s in path.strip("/").split("/") if s and s != "api"]
            params = [s[1:-1] for s in segs if s.startswith("{") and s.endswith("}")]
            if not params:
                continue
            # resource = segment before the FIRST param
            try:
                first_param_idx = next(i for i, s in enumerate(segs) if s.startswith("{"))
            except StopIteration:
                continue
            res = segs[first_param_idx - 1].lower() if first_param_idx >= 1 else ""
            # #1104: the REVERSE flip, which #106 never handled. A param annotated
            # `int` whose column holds TEXT 422s on every real value — r74 and r50
            # both ship `username: int` on /api/users/{username}, so the profile page
            # cannot load for any user. #338's own comment names this exact shape as
            # the thing its deferral was added to stop the framework from CAUSING;
            # the corpus still carries 21 of them across 7 runs (3 delivered) because
            # a lane writes it unprompted too. Judged on evidence, never on the name:
            # the projected signature where main.py projects the route (#338's own
            # authority — and the lane's handler is the one that SERVES when it
            # survives the override filter, so deferring here would ship the 422),
            # otherwise the column's own type.
            for arg in list(node.args.args) + list(node.args.kwonlyargs):
                if not (arg.arg in params and isinstance(arg.annotation, ast.Name)
                        and arg.annotation.id == "int"):
                    continue
                want_str = False
                if _verb and (_verb, path) in _projected_routes:
                    want_str = _projected_param_types.get(
                        (_verb, path), {}).get(arg.arg) == "str"
                else:
                    for _cand in (res, res.rstrip("s"), res + "s", res.replace("-", "_")):
                        if arg.arg in _string_cols.get(_cand, set()):
                            want_str = True
                            break
                if not want_str:
                    continue
                ln = arg.annotation.lineno - 1
                c0, c1 = arg.annotation.col_offset, arg.annotation.end_col_offset
                line = lines[ln]
                if line[c0:c1] == "int":
                    lines[ln] = line[:c0] + "str" + line[c1:]
                    fixed += 1
            if _verb and (_verb, path) in _projected_routes:
                continue  # #338: #119 owns this route's STR->INT direction
            # the forward flip below additionally requires an integer-PK resource
            if res not in int_pk_tables:
                continue
            for arg in list(node.args.args) + list(node.args.kwonlyargs):
                if (arg.arg in params and isinstance(arg.annotation, ast.Name)
                        and arg.annotation.id == "str"):
                    # #1104: never flip a NATURAL KEY. The forward rule asks only
                    # whether the resource's PK is an integer, which is exactly the
                    # guess #338 documents as false for /api/users/{username}: it
                    # reads `users`, sees users.id is an integer, and 422s every real
                    # username. Asking whether the PARAM's own column holds text
                    # settles it directly — and without this the two directions
                    # oscillate, the reverse pass rewriting to str and this one
                    # rewriting straight back (caught by the idempotence test).
                    if any(arg.arg in _string_cols.get(_c, set())
                           for _c in (res, res.rstrip("s"), res + "s",
                                      res.replace("-", "_"))):
                        continue
                    ln = arg.annotation.lineno - 1
                    c0, c1 = arg.annotation.col_offset, arg.annotation.end_col_offset
                    line = lines[ln]
                    if line[c0:c1] == "str":
                        lines[ln] = line[:c0] + "int" + line[c1:]
                        fixed += 1
        if fixed:
            new_src = "".join(lines)
            ast.parse(new_src)   # never write a syntax error
            _write_py_995(cr, new_src, what="repair_custom_routes_param_types")
        # #1149c: 0 here means every path param already carried the right annotation.
        if not fixed:
            return {"fixed": 0, "reason": "no str-annotated integer-PK path param"}
        return {"fixed": fixed}
    except Exception as exc:
        return {"fixed": 0, "error": f"{type(exc).__name__}: {exc}"}


def repair_backend_packaging(backend_dir) -> Dict[str, object]:
    """Make the backend pip-installable in docker. The lane variably writes a
    pyproject.toml with ``build-backend = "hatchling.build"`` but a FLAT module
    layout (main.py/models.py at the root — no ``src/<pkg>`` and no ``<pkg>/``
    dir matching the project name). The backend Dockerfile then runs
    ``uv pip install --system .`` BEFORE the .py files are COPYed, so hatchling
    cannot determine which package to build and the wheel build fails — the whole
    docker build dies (instagram MM, 2026-06-08: M5's backend never built →
    docker_up timeout → no delivery → no projection → declared endpoints stranded).

    The app does NOT need to BE a package: the Dockerfile COPYs the .py files and
    runs ``main.py`` directly; ``pip install .`` is only there to install
    [project.dependencies]. So when hatchling is the build backend and there is no
    resolvable package, add ``[tool.hatch.build.targets.wheel] bypass-selection =
    true`` — hatchling then builds an empty wheel and installs the deps, and the
    build succeeds. Idempotent (no-op once configured); best-effort; never raises."""
    try:
        be = Path(backend_dir)
        pp = be / "pyproject.toml"
        if not pp.exists():
            return {"repaired": False, "reason": "no pyproject.toml"}
        src = pp.read_text(encoding="utf-8", errors="ignore")
        if "hatchling" not in src:
            return {"repaired": False, "reason": "not a hatchling build"}
        # already has an explicit wheel/sdist target (lane configured it) → leave alone
        if "[tool.hatch.build.targets." in src or "bypass-selection" in src:
            return {"repaired": False, "reason": "already configured"}
        # A resolvable package needs an actual IMPORTABLE package matching the name —
        # i.e. an ``__init__.py`` under ``<pkg>/`` or ``src/<pkg>/``. Merely having a
        # ``src/`` dir is NOT enough: instagram MM run #14 had ``src/{config,routes,…}``
        # with NO ``__init__.py`` anywhere, so hatchling could not select a package and
        # ``uv pip install .`` failed — yet the old dir-only check skipped the repair
        # ("package layout resolvable") → docker_up stalled the whole milestone.
        pkg_name = ""
        m = re.search(r'(?m)^\s*name\s*=\s*["\']([^"\']+)["\']', src)
        if m:
            pkg_name = m.group(1).replace("-", "_")
        resolvable = bool(pkg_name) and (
            (be / pkg_name / "__init__.py").exists()
            or (be / "src" / pkg_name / "__init__.py").exists()
        )
        if resolvable:
            return {"repaired": False, "reason": "package layout resolvable"}
        addition = (
            "\n[tool.hatch.build.targets.wheel]\n"
            "# Framework fix: flat-layout app (main.py at the repo root, run directly).\n"
            "# The Dockerfile COPYs the .py files + runs them, so the wheel only needs\n"
            "# the dependencies. bypass-selection makes hatchling build an empty wheel\n"
            "# so `pip install .` installs the deps without failing on package detection.\n"
            "bypass-selection = true\n"
        )
        _fw_write_1202cw(pp, src.rstrip() + "\n" + addition, encoding="utf-8")
        return {"repaired": True, "pyproject": str(pp)}
    except Exception as exc:
        return {"repaired": False, "error": f"{type(exc).__name__}: {exc}"}


# FIX #189: real distributions the backend scaffold/Dockerfile stack actually
# uses — NEVER stripped even when a lane shadows one with a local file (removing
# the real install would break transitive imports; the shadow is a different
# bug that surfaces elsewhere).
_KNOWN_REAL_DISTS = {
    "fastapi", "uvicorn", "starlette", "pydantic", "psycopg", "psycopg2",
    "psycopg2-binary", "sqlalchemy", "alembic", "python-jose", "passlib",
    "python-multipart", "httpx", "requests", "bcrypt", "pyjwt", "jinja2",
    "aiofiles", "email-validator", "python-dotenv", "orjson",
}

# FIX #189 (r5 actual root): module names the backend skeleton OWNS by
# construction — incl. custom_routes, the one lane-override hook main.py
# imports under an except-ImportError guard. When the file is ABSENT at
# render time, _lane_third_party_imports used to see that import as
# third-party and the FRAMEWORK ITSELF wrote "custom_routes" into pyproject
# deps → uv resolution failed → docker_up wedged → STUCK-ABORT (tiktok-r5).
# Reserved names never become pip deps, file present or not.
_SKELETON_LOCAL_MODULES = {
    "database", "models", "seed_data", "main", "schemas", "auth_dependency",
    "custom_routes", "jwt_manager", "oauth_routes", "oauth_store",
    "user_bootstrap",
}


def _pep503(name: str) -> str:
    """PEP-503 normalization: case-insensitive, runs of -_. collapse to '-'."""
    return re.sub(r"[-_.]+", "-", str(name).strip().lower())


def sanitize_pyproject_local_deps(backend_dir) -> Dict[str, object]:
    """FIX #189 (tiktok-r5 STUCK-ABORT, 2026-07-18): the lane hallucinated the
    app's OWN ``custom_routes.py`` into a pip dependency (``custom-routes``) —
    uv resolution failed ("was not found in the package registry") → the backend
    image never built → docker_up wedged 7 post-cap cycles → abort, while the
    lane never landed the one-line fix. A dependency whose PEP-503 name matches
    a LOCAL module/package of the backend can never need installing (the local
    file shadows site-packages at runtime) — strip it DETERMINISTICALLY at heal
    time instead of waiting on a lane. Conservative: _KNOWN_REAL_DISTS are never
    stripped. Idempotent; best-effort; never raises."""
    try:
        be = Path(backend_dir)
        pp = be / "pyproject.toml"
        if not pp.exists():
            return {"repaired": False, "reason": "no pyproject.toml"}
        # skeleton-reserved names count as local even when the FILE is absent
        # (r5: the dep referenced a custom_routes.py that was never written).
        local = {_pep503(n) for n in _SKELETON_LOCAL_MODULES}
        for f in be.glob("*.py"):
            local.add(_pep503(f.stem))
        for d in be.iterdir():
            if d.is_dir() and (d / "__init__.py").exists():
                local.add(_pep503(d.name))
        src_pkg_root = be / "src"
        if src_pkg_root.is_dir():
            for sub in src_pkg_root.iterdir():
                if sub.is_dir() and (sub / "__init__.py").exists():
                    local.add(_pep503(sub.name))
        src = pp.read_text(encoding="utf-8", errors="ignore")
        # closing ] anchored at line start — a mid-entry ']' (uvicorn[standard])
        # must not close the list early. Single-line dep lists don't match → safe
        # no-op (generated pyprojects are pretty-printed multi-line).
        m = re.search(r"(?ms)^(\s*dependencies\s*=\s*\[)(.*?)(^\s*\])", src)
        if not m:
            return {"repaired": False, "reason": "no [project] dependencies list"}
        head, body, tail = m.group(1), m.group(2), m.group(3)
        kept_lines: List[str] = []
        dropped: List[str] = []
        for line in body.splitlines():
            entry = line.strip().strip(",").strip("\"'")
            if not entry or entry.startswith("#"):
                kept_lines.append(line)
                continue
            dep_name = _pep503(re.split(r"[<>=!~\[; ]", entry, 1)[0])
            if dep_name in local and dep_name not in _KNOWN_REAL_DISTS:
                dropped.append(entry)
                continue
            # #242 (tiktok r32 STUCK-ABORT): a dep whose PEP-503-normalized name is
            # not a valid distribution name (leading/trailing separator, e.g. the
            # lane's hallucinated '_framework' → '-framework') can NEVER resolve on
            # PyPI → `pip install .` fails → docker build fails → build:docker_build
            # → verification_checklist_not_ready → no-convergence abort. #189 stripped
            # only LOCAL-module deps; this strips the invalid-NAME hallucination class
            # too. Deterministic + safe: a real PyPI dist cannot have an invalid name.
            if dep_name and not re.match(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$", dep_name):
                dropped.append(entry)
                continue
            kept_lines.append(line)
        if not dropped:
            return {"repaired": False, "reason": "no local-module deps"}
        new_src = src[:m.start()] + head + "\n".join(kept_lines) + tail + src[m.end():]
        _fw_write_1202cw(pp, new_src, encoding="utf-8")
        return {"repaired": True, "dropped": dropped, "pyproject": str(pp)}
    except Exception as exc:
        return {"repaired": False, "error": f"{type(exc).__name__}: {exc}"}


__all__ = ["repair_backend_auth_dependency", "repair_auth_import_paths",
           "repair_backend_packaging"]
