"""#1101: the AS could verify a token under four names and mint one under only a name no lane uses.

``JWTManager`` carries three aliases for verify-and-decode, added because "lanes
routinely hand-write a custom-route auth helper that calls
``jwt_manager.verify_access_token`` / ``verify_token`` — methods that did NOT exist
on this manager, so EVERY such custom endpoint 401'd". The mint side had exactly one
name, ``sign_access_token``, keyword-only and requiring issuer/audience/scope.

The name a lane actually reaches for is the one in FastAPI's own security docs:

    jwt_mgr.create_access_token(data={"sub": str(1)})

instagram-run67 wrote that in ``GET /api/v1/get_token`` and shipped it in a DELIVERED
milestone. Booted against a real Postgres the route answers **500** — AttributeError,
every request. The corpus has one such call in 84 runs; the verify-side aliases exist
for the same reason and this is the same remedy on the other side.

★ The alias only pays off if the token it mints is one the app's OWN auth accepts —
otherwise it trades a 500 for a 401, which is worse because it looks like it worked.
So it delegates to ``sign_access_token`` rather than encoding a payload itself, and
the round-trip is asserted below. Verified live on run67's delivered backend: the
route went 500 → 200, and ``GET /auth/me`` with the minted token returned the right
user.
"""
import sys
from datetime import timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.oauth_scaffold import render_oauth_module  # noqa: E402


@pytest.fixture(scope="module")
def mod():
    """The rendered AS module, exec'd as a real module."""
    import types
    src = render_oauth_module("jwt_manager.py")
    m = types.ModuleType("jwt_manager_1101")
    m.__dict__["__file__"] = "jwt_manager.py"
    exec(compile(src, "jwt_manager.py", "exec"), m.__dict__)
    return m


@pytest.fixture()
def mgr(mod, tmp_path):
    # a 1024-bit key keeps the suite fast; the alias does no crypto of its own
    return mod.JWTManager(data_dir=str(tmp_path), key_size=1024)


def _claims(mgr, token):
    return mgr.verify_access_token(token)


def test_the_tutorial_signature_works(mgr):
    """`create_access_token(data={"sub": ...})` — what run67 called."""
    tok = mgr.create_access_token(data={"sub": "7"})
    assert _claims(mgr, tok)["sub"] == "7"


def test_the_minted_token_verifies_with_this_same_manager(mgr):
    """★ The whole point: an alias that minted an unverifiable token would turn a
    500 into a 401 and look like it had worked."""
    tok = mgr.create_access_token(data={"sub": "7"})
    c = _claims(mgr, tok)
    assert c["token_type"] == "access_token"
    assert c["iss"] and c["aud"] and c["scope"]


def test_it_produces_the_same_claim_set_as_the_canonical_minter(mgr):
    """It must delegate, not re-implement — same keys, same shapes."""
    a = _claims(mgr, mgr.create_access_token(data={"sub": "7"}))
    b = _claims(mgr, mgr.sign_access_token(subject="7", issuer="app-oauth",
                                           audience="app-api", scope="app.read app.write"))
    assert set(a) == set(b)
    assert isinstance(a["aud"], list)          # RFC 7519 array form, as the AS emits


def test_the_explicit_subject_kwarg_also_works(mgr):
    assert _claims(mgr, mgr.create_access_token(subject=42))["sub"] == "42"


@pytest.mark.parametrize("key", ["sub", "subject", "user_id", "id"])
def test_the_keys_a_lane_puts_the_subject_under(mgr, key):
    assert _claims(mgr, mgr.create_access_token(data={key: "9"}))["sub"] == "9"


def test_the_subject_key_is_not_also_emitted_as_a_claim(mgr):
    c = _claims(mgr, mgr.create_access_token(data={"user_id": "9", "email": "a@b.io"}))
    assert c["sub"] == "9"
    assert "user_id" not in c
    assert c["email"] == "a@b.io"               # the rest of `data` survives


def test_extra_data_becomes_claims(mgr):
    c = _claims(mgr, mgr.create_access_token(
        data={"sub": "1", "email": "a@b.io", "tenant_id": "t1"}))
    assert c["email"] == "a@b.io" and c["tenant_id"] == "t1"


def test_a_timedelta_expiry_is_honoured(mgr):
    c = _claims(mgr, mgr.create_access_token(data={"sub": "1"},
                                             expires_delta=timedelta(minutes=5)))
    assert c["exp"] - c["iat"] == 300


def test_plain_seconds_are_honoured_too(mgr):
    c = _claims(mgr, mgr.create_access_token(data={"sub": "1"}, expires_delta=120))
    assert c["exp"] - c["iat"] == 120


def test_the_default_ttl_matches_the_canonical_minter(mgr):
    c = _claims(mgr, mgr.create_access_token(data={"sub": "1"}))
    assert c["exp"] - c["iat"] == 3600


def test_no_subject_fails_loudly_and_says_what_to_pass(mgr):
    """A token with no `sub` identifies nobody; silently minting one would surface
    later as an unexplainable 401."""
    with pytest.raises(ValueError) as e:
        mgr.create_access_token(data={"email": "a@b.io"})
    assert "sub" in str(e.value)


def test_the_verify_side_aliases_still_work(mgr):
    """Non-regression on the three this fix is modelled after."""
    tok = mgr.create_access_token(data={"sub": "3"})
    for name in ("verify_access_token", "verify_token", "decode_token",
                 "decode_access_token"):
        assert getattr(mgr, name)(tok)["sub"] == "3"


def test_the_canonical_minter_is_unchanged(mgr):
    """`sign_access_token` stays keyword-only with its required arguments."""
    with pytest.raises(TypeError):
        mgr.sign_access_token("7", "iss", "aud", "scope")


def test_the_defaults_agree_with_the_routes_module():
    """The alias has no request to derive an issuer from, so it uses defaults — they
    must be the ones oauth_routes.py already emits, not a second set."""
    routes = render_oauth_module("oauth_routes.py")
    jm = render_oauth_module("jwt_manager.py")
    assert 'DEFAULT_SCOPE = "app.read app.write"' in routes
    assert 'DEFAULT_SCOPE = "app.read app.write"' in jm
    assert 'os.getenv("OAUTH_DEFAULT_AUDIENCE", "app-api")' in routes
    assert 'os.getenv("OAUTH_DEFAULT_AUDIENCE", "app-api")' in jm


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
