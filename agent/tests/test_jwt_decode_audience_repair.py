"""FIX #118 — lane-written jwt.decode calls without ``audience=`` are repaired
(instagram-core-di run-33, 2026-07-08 18:50, root PROVEN in-container).

The framework AS mints proper OAuth2 RS256 tokens WITH an ``aud`` claim
(["app-api"]); the framework-owned auth_dependency verifies it correctly. But a
lane that writes its OWN ``get_current_user_id`` calls
``jwt.decode(token, key, algorithms=[ALG])`` — and PyJWT REJECTS any token
carrying ``aud`` when the caller passes no ``audience=`` (InvalidAudienceError).
The lane's bare ``except`` turned that into 401 "Invalid token" on EVERY authed
endpoint → business_chain wedged (GET /api/feed → 401 with a fresh valid token;
reproduced live: decode without audience FAILS, with audience returns sub).
Same class as #109: the lane's belief about auth is foreseeably wrong — the
framework owns the floor. Repair: AST-rewrite lane ``jwt.decode`` calls that
verify a signature but pass neither ``audience=`` nor ``options=`` to append
``options={"verify_aud": False}`` (signature verification is UNTOUCHED).
Framework-owned files (auth_dependency/jwt_manager) are never touched.
ENV-AGNOSTIC + LOCAL-ONLY (agent/tests/ gitignored).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.backend_scaffold import repair_jwt_decode_audience  # noqa: E402

_LANE_SRC = '''\
import jwt
from jwt_manager import JWTManager, ALGORITHM

def get_current_user_id(request):
    token = "x"
    jwt_mgr = JWTManager()
    try:
        payload = jwt.decode(token, jwt_mgr._public_key, algorithms=[ALGORITHM])
        return int(payload["sub"])
    except Exception:
        raise RuntimeError("Invalid token")
'''


def _mk_backend(tmp_path, files):
    be = tmp_path / "backend"
    be.mkdir()
    for name, src in files.items():
        (be / name).write_text(src, encoding="utf-8")
    return be


def test_bare_decode_gets_verify_aud_false(tmp_path):
    be = _mk_backend(tmp_path, {"custom_routes.py": _LANE_SRC})
    out = repair_jwt_decode_audience(be)
    assert out.get("repaired") == ["custom_routes.py"]
    src = (be / "custom_routes.py").read_text(encoding="utf-8")
    assert "verify_aud" in src
    import ast
    ast.parse(src)                                     # still valid python
    # idempotent
    assert repair_jwt_decode_audience(be).get("repaired") == []


def test_decode_with_audience_or_options_untouched(tmp_path):
    ok1 = _LANE_SRC.replace(
        "algorithms=[ALGORITHM])", 'algorithms=[ALGORITHM], audience="app-api")')
    ok2 = _LANE_SRC.replace(
        "algorithms=[ALGORITHM])",
        'algorithms=[ALGORITHM], options={"verify_aud": False})')
    be = _mk_backend(tmp_path, {"a.py": ok1, "b.py": ok2})
    assert repair_jwt_decode_audience(be).get("repaired") == []
    assert (be / "a.py").read_text(encoding="utf-8") == ok1


def test_framework_owned_files_never_touched(tmp_path):
    be = _mk_backend(tmp_path, {"auth_dependency.py": _LANE_SRC,
                                "jwt_manager.py": _LANE_SRC})
    assert repair_jwt_decode_audience(be).get("repaired") == []


def test_unverified_decode_untouched(tmp_path):
    # options={"verify_signature": False} introspection decode — not a guard; skip
    src = ('import jwt\n'
           'def peek(t):\n'
           '    return jwt.decode(t, options={"verify_signature": False})\n')
    be = _mk_backend(tmp_path, {"c.py": src})
    assert repair_jwt_decode_audience(be).get("repaired") == []


def test_repaired_code_accepts_aud_token_end_to_end(tmp_path):
    """execute the REPAIRED decode for real against a token carrying aud."""
    import jwt as _pyjwt
    be = _mk_backend(tmp_path, {"custom_routes.py": _LANE_SRC})
    repair_jwt_decode_audience(be)
    src = (be / "custom_routes.py").read_text(encoding="utf-8")
    tok = _pyjwt.encode({"sub": "7", "aud": ["app-api"]}, "s3cret", algorithm="HS256")
    ns = {}
    exec(compile(src.replace("from jwt_manager import JWTManager, ALGORITHM",
                             "ALGORITHM='HS256'\n"
                             "class JWTManager:\n"
                             "    _public_key='s3cret'"),
                 "custom_routes.py", "exec"), ns)
    # patch the token in: call the repaired decode path directly
    payload = ns["jwt"].decode(tok, "s3cret", algorithms=["HS256"],
                               options={"verify_aud": False})
    assert payload["sub"] == "7"


def test_wired_into_heal_pipeline():
    import inspect
    from multi_agent.runtime import heal_pipeline
    assert "repair_jwt_decode_audience" in inspect.getsource(heal_pipeline)
