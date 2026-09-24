"""#317 — the frontend auth-token localStorage key must be CANONICAL by
construction, so a lane can't mismatch what api.js writes vs what a page/AuthProvider
reads.

r85 + r86 both wedged deliverability_ui_flow the same way: the framework prompt says
"localStorage keys are FIXED: access_token" but the framework scaffold DUAL-WRITES
access_token+token (a hedge that signals the key isn't really fixed), and the lane's
api.js diverged to a brand key (`tt_token`) while its SignupPage/LoginPage wrote
`token`/`access_token`. After login the token landed in access_token/token but
api.js.authHeaders() read tt_token → null → every authed call unauthenticated → the
app looked logged-out → the signup/feed ui_flow failed, and the lane thrash-rewrote
the pages without ever converging. A strong model shouldn't have to keep 3+ files
agreeing on a bare string by hand — the FRAMEWORK must enforce one key.

normalize_frontend_token_key rewrites every auth-token localStorage key across src/*
to the canonical ``access_token`` (leaving refresh_token / user / tenant keys alone),
idempotently — mirroring normalize_frontend_api_base.
"""
import sys
import tempfile
from pathlib import Path

THIS = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS.parent / "env_generator" / "llm_generator"))
from multi_agent.runtime.frontend_scaffold import normalize_frontend_token_key  # noqa: E402


def _fe(files: dict) -> Path:
    root = Path(tempfile.mkdtemp(prefix="fe317_"))
    src = root / "src"
    (src / "services").mkdir(parents=True)
    (src / "pages").mkdir(parents=True)
    for rel, body in files.items():
        p = src / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    return root


def test_r86_mismatch_is_unified():
    # api.js reads tt_token; the page writes token + access_token → after normalize all
    # three collapse to access_token, so api.js reads exactly what the page wrote.
    fe = _fe({
        "services/api.js": "const t = localStorage.getItem('tt_token'); localStorage.setItem('tt_token', tok);",
        "pages/SignupPage.jsx": "localStorage.setItem('token', d.access_token); localStorage.setItem('access_token', d.access_token);",
    })
    out = normalize_frontend_token_key(fe)
    api = (fe / "src/services/api.js").read_text()
    page = (fe / "src/pages/SignupPage.jsx").read_text()
    assert "tt_token" not in api and "getItem('access_token')" in api and "setItem('access_token'" in api
    assert "'token'" not in page and page.count("access_token") >= 2   # both writes now access_token
    assert out.get("normalized")   # reports the files it touched


def test_camelcase_and_jwt_aliases_unified():
    fe = _fe({
        "services/api.js": "localStorage.getItem('accessToken'); localStorage.getItem('jwt'); localStorage.getItem('authToken');",
    })
    normalize_frontend_token_key(fe)
    api = (fe / "src/services/api.js").read_text()
    assert "accessToken" not in api and "'jwt'" not in api and "authToken" not in api
    assert api.count("access_token") == 3


def test_non_token_keys_are_left_alone():
    # refresh_token, user, tenant keys must NOT be rewritten to access_token
    body = ("localStorage.getItem('refresh_token'); localStorage.getItem('tt_user'); "
            "localStorage.getItem('X_TENANT_ID');")
    fe = _fe({"services/api.js": body})
    normalize_frontend_token_key(fe)
    api = (fe / "src/services/api.js").read_text()
    assert "refresh_token" in api and "tt_user" in api and "X_TENANT_ID" in api
    assert "access_token" not in api


def test_idempotent():
    fe = _fe({"services/api.js": "localStorage.setItem('tt_token', t);"})
    normalize_frontend_token_key(fe)
    first = (fe / "src/services/api.js").read_text()
    out2 = normalize_frontend_token_key(fe)
    second = (fe / "src/services/api.js").read_text()
    assert first == second and not out2.get("normalized")   # second pass is a no-op
