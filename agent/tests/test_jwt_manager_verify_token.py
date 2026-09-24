"""JWTManager must expose verify_access_token (+ verify_token/decode_token aliases).

Lanes routinely hand-write a custom-route auth helper that calls
``jwt_manager.verify_access_token(token)`` (or ``verify_token``) — methods that did NOT
exist, so every such custom (non-CRUD action) endpoint 401'd "Invalid authentication
token" and dead-ended the milestone's business_chain (outlook M2 reply/rsvp/search,
2026-06-29). The methods now decode against the AS's own public key, so a lane's invented
auth verifies a token the AS actually signed.
"""

import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]
_TMPL = (AGENT_DIR / "env_generator" / "llm_generator" / "multi_agent" / "runtime"
         / "oauth_as_templates" / "jwt_manager.py.tmpl")


def _load_jwt_manager(tmp_dir):
    """exec the seeded jwt_manager template as a module (it's plain Python)."""
    ns: dict = {"__name__": "jwt_manager_under_test"}
    exec(compile(_TMPL.read_text(encoding="utf-8"), str(_TMPL), "exec"), ns)  # noqa: S102
    return ns["JWTManager"](data_dir=str(tmp_dir))


def _sign(mgr, sub="42"):
    return mgr.sign_access_token(
        subject=sub, issuer="http://localhost:3001",
        audience="app", scope="openid", extra_claims={"email": "u@x.io"})


def test_verify_access_token_roundtrips(tmp_path):
    mgr = _load_jwt_manager(tmp_path)
    claims = mgr.verify_access_token(_sign(mgr, sub="42"))
    assert claims["sub"] == "42"
    assert claims["email"] == "u@x.io"


def test_alias_methods_present_and_work(tmp_path):
    mgr = _load_jwt_manager(tmp_path)
    tok = _sign(mgr, sub="7")
    for name in ("verify_token", "decode_token", "decode_access_token"):
        assert hasattr(mgr, name), f"JWTManager missing alias {name!r}"
        assert getattr(mgr, name)(tok)["sub"] == "7"


def test_invalid_token_raises(tmp_path):
    mgr = _load_jwt_manager(tmp_path)
    import pytest
    with pytest.raises(Exception):
        mgr.verify_access_token("not.a.jwt")


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
