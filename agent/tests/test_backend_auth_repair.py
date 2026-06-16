"""Backend auth-dependency repair — normalises a get_current_user that does NOT
validate the bearer JWT to the framework one.

Root fix (instagram MM run #11, 2026-06-09): the lane wrote a ``get_current_user`` that
read identity from an ``X-User-Id`` header instead of the bearer token → every authed
endpoint 401'd 'missing user context' with a valid token. The delivered app passed
api_smoke (401 < 500) but was unusable; the test-user phase caught it. The repair must
catch this shape (no token param, no JWT validation) AND preserve a real JWT dependency.
"""

import ast
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.backend_scaffold import (  # noqa: E402
    _is_placeholder_auth,
    _module_get_current_user,
    repair_auth_enforcement_middleware,
    repair_backend_auth_dependency,
    repair_inline_token_auth,
)


def _func(src):
    return _module_get_current_user(ast.parse(src))


_XUSERID = '''def get_current_user(
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    db: Session = Depends(get_db),
):
    if not x_user_id:
        raise HTTPException(status_code=401, detail="missing user context")
    return db.get(User, int(x_user_id))
'''

_PLACEHOLDER = '''def get_current_user(db: Session = Depends(get_db)):
    return db.query(User).first()
'''

_REAL_JWT = '''def get_current_user(authorization: str = Header(None), db: Session = Depends(get_db)):
    token = authorization.split(" ", 1)[1]
    claims = jwt.decode(token, KEY, algorithms=["RS256"])
    return db.query(User).filter(User.id == int(claims["sub"])).first()
'''

# run #13: reads the Authorization header but uses the RAW token as a SQL lookup value
# (WHERE id = :token) — never decodes the JWT → 401 on every authed endpoint.
_SQL_LOOKUP = '''def get_current_user(authorization: str = Header(default=None), db: Session = Depends(get_db)):
    token = authorization[7:].strip()
    user = db.execute(text("SELECT * FROM users WHERE id::text = :token OR email = :token"), {"token": token}).first()
    if not user:
        raise HTTPException(status_code=401, detail="invalid token")
    return dict(user)
'''


def test_xuserid_header_dependency_is_broken():
    assert _is_placeholder_auth(_func(_XUSERID)) is True


def test_classic_placeholder_is_broken():
    assert _is_placeholder_auth(_func(_PLACEHOLDER)) is True


def test_sql_lookup_token_without_decode_is_broken():
    # the run #13 variant: has an `authorization` param but never decodes the JWT
    assert _is_placeholder_auth(_func(_SQL_LOOKUP)) is True


def test_real_jwt_dependency_preserved():
    assert _is_placeholder_auth(_func(_REAL_JWT)) is False


def _backend(tmp_path, main_src):
    (tmp_path / "models.py").write_text(
        'from sqlalchemy import Column, Integer\nfrom database import Base\n'
        'class User(Base):\n    __tablename__="users"\n    id=Column(Integer, primary_key=True)\n',
        encoding="utf-8")
    (tmp_path / "database.py").write_text("Base=object\ndef get_db():\n    ...\n", encoding="utf-8")
    (tmp_path / "main.py").write_text(
        "from fastapi import Depends, Header, HTTPException\n"
        "from sqlalchemy.orm import Session\n"
        "from database import get_db\n"
        "from models import User\n\n" + main_src, encoding="utf-8")
    return tmp_path


def test_repair_rewrites_xuserid_to_framework_auth(tmp_path):
    be = _backend(tmp_path, _XUSERID)
    res = repair_backend_auth_dependency(be)
    assert res.get("repaired") is True
    out = (be / "main.py").read_text(encoding="utf-8")
    assert "from auth_dependency import get_current_user" in out
    assert "missing user context" not in out  # the broken body is gone
    ast.parse(out)
    # the framework auth_dependency.py was written and decodes the JWT
    assert (be / "auth_dependency.py").exists()
    assert "jwt" in (be / "auth_dependency.py").read_text(encoding="utf-8").lower()


def test_repair_leaves_real_jwt_dependency_untouched(tmp_path):
    be = _backend(tmp_path, _REAL_JWT)
    repair_backend_auth_dependency(be)
    out = (be / "main.py").read_text(encoding="utf-8")
    # real auth is preserved (not replaced by the import)
    assert "jwt.decode" in out
    assert "from auth_dependency import get_current_user" not in out


# --- inline fake-token auth (run #12: parts = raw_token.split(":") → user:<id>) ---
_INLINE_FAKE = '''from fastapi import Header, HTTPException


def get_me(authorization: str | None = Header(default=None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="missing bearer token")
    raw_token = authorization[7:] if authorization.startswith("Bearer ") else authorization
    parts = raw_token.split(":", 1)
    if len(parts) != 2 or parts[0] != "user":
        raise HTTPException(status_code=401, detail="invalid token")
    user_id = int(parts[1])
    return {"id": user_id}
'''


def test_inline_fake_token_repaired_to_real_assignment(tmp_path):
    """The repair must REPLACE the fake split with a proper ``parts = [...]`` ASSIGNMENT
    that decodes the JWT — not a bare expression (which would NameError at runtime)."""
    (tmp_path / "main.py").write_text(_INLINE_FAKE, encoding="utf-8")
    res = repair_inline_token_auth(tmp_path)
    assert res["fixed"] == 1
    out = (tmp_path / "main.py").read_text(encoding="utf-8")
    ast.parse(out)
    assert 'parts = ["user", str(_framework_jwt_sub(raw_token))]' in out  # assignment kept
    assert ".split(\":\"" not in out                                       # fake split gone
    assert "def _framework_jwt_sub(" in out                                # helper injected
    # the rewritten line really defines `parts` (no NameError) — assert via AST
    tree = ast.parse(out)
    assigns = [n for n in ast.walk(tree)
               if isinstance(n, ast.Assign)
               and any(getattr(t, "id", None) == "parts" for t in n.targets)]
    assert assigns, "parts must be assigned, not left a bare expression"


def test_inline_repair_idempotent(tmp_path):
    (tmp_path / "main.py").write_text(_INLINE_FAKE, encoding="utf-8")
    assert repair_inline_token_auth(tmp_path)["fixed"] == 1
    assert repair_inline_token_auth(tmp_path)["fixed"] == 0


def test_inline_repair_skips_non_fake_auth(tmp_path):
    (tmp_path / "main.py").write_text(
        "def h(authorization=None):\n    return jwt.decode(authorization)\n", encoding="utf-8")
    assert repair_inline_token_auth(tmp_path)["fixed"] == 0


# --- run #16: a no-auth app (handlers fetch the first DB user) → enforce via middleware ---
_NOAUTH_MAIN = '''from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"])


@app.get("/api/users/me")
def get_my_profile(db=Depends(get_db)):
    return db.query(User).order_by(User.id.asc()).first()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app)
'''


def test_auth_enforcement_middleware_injected(tmp_path):
    (tmp_path / "main.py").write_text(_NOAUTH_MAIN, encoding="utf-8")
    (tmp_path / "jwt_manager.py").write_text("ALGORITHM='RS256'\nclass JWTManager:\n    public_pem=b''\n", encoding="utf-8")
    res = repair_auth_enforcement_middleware(tmp_path)
    assert res["injected"] is True
    out = (tmp_path / "main.py").read_text(encoding="utf-8")
    ast.parse(out)
    assert "_framework_auth_guard" in out
    assert '@app.middleware("http")' in out
    # the middleware is defined BEFORE the first route so it registers
    assert out.index("_framework_auth_guard") < out.index('@app.get("/api/users/me")')
    # /auth/ and /api/v1/ stay public
    assert 'p.startswith("/auth/")' in out and 'p.startswith("/api/v1/")' in out


def test_auth_middleware_idempotent(tmp_path):
    (tmp_path / "main.py").write_text(_NOAUTH_MAIN, encoding="utf-8")
    (tmp_path / "jwt_manager.py").write_text("class JWTManager:\n    public_pem=b''\n", encoding="utf-8")
    assert repair_auth_enforcement_middleware(tmp_path)["injected"] is True
    assert repair_auth_enforcement_middleware(tmp_path)["injected"] is False


def test_auth_middleware_skipped_without_AS(tmp_path):
    (tmp_path / "main.py").write_text(_NOAUTH_MAIN, encoding="utf-8")  # no jwt_manager.py
    assert repair_auth_enforcement_middleware(tmp_path)["injected"] is False
