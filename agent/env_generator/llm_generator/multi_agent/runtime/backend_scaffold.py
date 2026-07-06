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
        (be / "auth_dependency.py").write_text(_AUTH_DEPENDENCY_PY, encoding="utf-8")
        rewritten: List[str] = []
        for p in placeholder_files:
            src = p.read_text(encoding="utf-8", errors="ignore")
            new = _rewrite_local_get_current_user(src)
            if new != src:
                p.write_text(new, encoding="utf-8")
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
            return out
        src = p.read_text(encoding="utf-8")
        if not _ROUTER_USE_RE.search(src) or _ROUTER_DEF_RE.search(src):
            return out
        lines = src.split("\n")
        last_import = max((i for i, l in enumerate(lines)
                           if l.startswith("import ") or l.startswith("from ")), default=-1)
        lines[last_import + 1:last_import + 1] = [
            "", "from fastapi import APIRouter", "router = APIRouter()", ""]
        p.write_text("\n".join(lines), encoding="utf-8")
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
                p.write_text(new, encoding="utf-8")
                rewritten.append(p.name)
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
            return {"fixed": 0}
        src = main_py.read_text(encoding="utf-8", errors="ignore")
        if _FAKE_PARTS_MARKER not in src or "_framework_jwt_sub(" in src:
            return {"fixed": 0}  # not the fake-token shape / already repaired
        new_src, n = _FAKE_SPLIT_RE.subn(
            r'parts = ["user", str(_framework_jwt_sub(\1))]', src)
        if n == 0:
            return {"fixed": 0}
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
        main_py.write_text(new_src, encoding="utf-8")
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
import jwt as _fw_jwt
from fastapi.responses import JSONResponse as _FWJSONResponse
try:
    from jwt_manager import JWTManager as _FWJM, ALGORITHM as _FWALG
    _fw_pp = _FWJM().public_pem
    _FW_PEM = _fw_pp() if callable(_fw_pp) else _fw_pp
except Exception:
    _FW_PEM, _FWALG = None, "RS256"


@app.middleware("http")
async def _framework_auth_guard(request, call_next):
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
        or p in ("/api/auth/login", "/api/auth/register")
    )
    if p.startswith("/api/") and not public and request.method != "OPTIONS":
        ok = False
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer ") and _FW_PEM:
            try:
                _fw_jwt.decode(auth.split(" ", 1)[1].strip(), _FW_PEM,
                               algorithms=[_FWALG], options={"verify_aud": False})
                ok = True
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
        main_py.write_text(new_src, encoding="utf-8")
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
        else:
            status, detail = 400, "integrity constraint violated"
        return _FWIntegrityJSON(status_code=status, content={"detail": detail})
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
        main_py.write_text(new_src, encoding="utf-8")
        return {"injected": True}
    except Exception as exc:
        return {"injected": False, "error": f"{type(exc).__name__}: {exc}"}


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
        pp.write_text(src.rstrip() + "\n" + addition, encoding="utf-8")
        return {"repaired": True, "pyproject": str(pp)}
    except Exception as exc:
        return {"repaired": False, "error": f"{type(exc).__name__}: {exc}"}


__all__ = ["repair_backend_auth_dependency", "repair_auth_import_paths",
           "repair_backend_packaging"]
