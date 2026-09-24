"""#321 — /auth/register + /auth/login are FRAMEWORK-OWNED with a fixed schema
{email, password}. A verifier-authored business_chain step that omits email/password
422s "email and password are required" → business_chain wedges forever (r90 M-final:
FAILED 6/6 on POST /auth/register). normalize_steps must guarantee the body carries
both (setdefault only the MISSING keys — never clobbering authored creds).
"""
import sys
from pathlib import Path

THIS = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS.parent / "env_generator" / "llm_generator"))
from multi_agent.runtime.chain_executor import normalize_steps  # noqa: E402


def _body(steps, path):
    norm, _err = normalize_steps(steps)
    for s in norm:
        if str(s.get("path", "")).rstrip("/") == path:
            return s.get("body")
    return None


def test_register_missing_email_password_is_injected():
    b = _body([{"method": "POST", "path": "/auth/register", "body": {}}], "/auth/register")
    assert isinstance(b, dict) and b.get("email") and b.get("password")


def test_register_with_only_username_gets_email_password_added():
    # modelled a username signup → email/password still guaranteed (username kept alongside)
    b = _body([{"method": "POST", "path": "/auth/register",
                "body": {"username": "alice"}}], "/auth/register")
    assert b.get("email") and b.get("password") and b.get("username") == "alice"


def test_authored_credentials_are_not_clobbered():
    b = _body([{"method": "POST", "path": "/auth/register",
                "body": {"email": "real@x.io", "password": "S3cret!!"}}], "/auth/register")
    assert b["email"] == "real@x.io" and b["password"] == "S3cret!!"


def test_login_missing_creds_injected():
    b = _body([{"method": "POST", "path": "/auth/login", "body": {}}], "/auth/login")
    assert b.get("email") and b.get("password")


def test_register_and_login_share_one_identity():
    # a register→login round-trip in one chain must use the SAME injected identity
    norm, _ = normalize_steps([
        {"method": "POST", "path": "/auth/register", "body": {}},
        {"method": "POST", "path": "/auth/login", "body": {}},
    ])
    reg = next(s for s in norm if s["path"].rstrip("/") == "/auth/register")
    log = next(s for s in norm if s["path"].rstrip("/") == "/auth/login")
    assert reg["body"]["email"] == log["body"]["email"]
    assert reg["body"]["password"] == log["body"]["password"]


def test_non_auth_step_body_untouched():
    b = _body([{"method": "POST", "path": "/api/videos", "body": {"caption": "hi"}}], "/api/videos")
    assert b == {"caption": "hi"}   # no email/password injected into business writes
