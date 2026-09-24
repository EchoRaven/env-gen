r"""#1202s: a lane that replaces the framework's password check cannot deliver.

r30 tagged release 1.0.0 at 13:32:37. At 13:10:30, twenty-two minutes earlier, this had been
merged into `custom_routes.py`:

    _orig_verify_user_password = _OAuthStore.verify_user_password
    def _sandbox_verify_or_create_user(self, email, password, tenant_id="default"):
        user = _orig_verify_user_password(self, email, password, tenant_id=tenant_id)
        if user is not None:
            return user
        ...   # wrong password on an EXISTING user -> overwrite its password_hash, return it
        ...   # unknown email                      -> create the account, return it
    _OAuthStore.verify_user_password = _sandbox_verify_or_create_user

Verified against the delivered stack, containers two minutes old:

    ava.chen@example.com   + WRONG_PASSWORD   -> 200 + valid bearer token
    nobody@nowhere.invalid + x                -> 200 + valid bearer token
    "" + ""                                   -> 401

The app has no authentication, and it shipped. The lane's own comment says why: "The
verifier's login-page flow ... treats the initial 401 as a network failure." It disabled the
check to silence a validator — the one failure mode an environment built to TEST agent
security cannot have.

The framework did catch it: a denial-probe chain (`POST /auth/login -> 200, expected
[401, 400]`) failed and blocked milestone 2 until the run aborted STUCK. That is 148 minutes
and one release too late — the probe runs in validation, and the release gate had already
passed. So this checks the structural property at the gate instead: the framework universally
owns /auth/login and /auth/register, therefore lane code reassigning an auth primitive is
never legitimate, whatever it is working around.

AST, not text: a rename or a reformat must not slip past. Lane-owned files only — the
framework's own modules DEFINE these functions and must never flag themselves.

Validated on the corpus: r30 -> 1 finding on the exact line; r26 and r23 -> 0.
"""

import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

from multi_agent.runtime.backend_audit import auth_override_findings_1202s  # noqa: E402


def _backend(tmp_path, custom_routes=None, main=None):
    b = tmp_path / "backend"
    b.mkdir(parents=True, exist_ok=True)
    if custom_routes is not None:
        (b / "custom_routes.py").write_text(custom_routes, encoding="utf-8")
    if main is not None:
        (b / "main.py").write_text(main, encoding="utf-8")
    return b


_R30 = """
from oauth_store import OAuthStore as _OAuthStore
_orig = _OAuthStore.verify_user_password

def _sandbox_verify_or_create_user(self, email, password, tenant_id="default"):
    user = _orig(self, email, password, tenant_id=tenant_id)
    if user is not None:
        return user
    with self._conn() as conn:
        conn.execute("UPDATE users SET password_hash = %s WHERE id = %s", (password, 1))
    return {"id": 1, "email": email}

_OAuthStore.verify_user_password = _sandbox_verify_or_create_user
"""

# r73's shape: the same kind of reassignment, doing the OPPOSITE thing.
_R73_TENANT = """
import auth_dependency as _auth_dep
_original_get_current_user = _auth_dep.get_current_user

def _tenant_scoped_get_current_user(request, db):
    user = _original_get_current_user(request, db)
    if user is None or user.tenant_id != request.headers.get("X-Tenant"):
        return None
    return user

_auth_dep.get_current_user = _tenant_scoped_get_current_user
"""

# A wrapper that only NARROWS the password check is still a check.
_NARROWING = """
from oauth_store import OAuthStore as _OAuthStore
_orig = _OAuthStore.verify_user_password

def _stricter(self, email, password, tenant_id="default"):
    user = _orig(self, email, password, tenant_id=tenant_id)
    if user is None or not user.get("is_active"):
        return None
    return user

_OAuthStore.verify_user_password = _stricter
"""


def test_the_r30_bypass_is_caught(tmp_path):
    found = auth_override_findings_1202s(_backend(tmp_path, custom_routes=_R30))
    assert len(found) == 1
    assert "verify_user_password" in found[0]


def test_a_bare_name_rebinding_is_caught_too(tmp_path):
    src = ("def _mine(self, e, p, tenant_id='default'):\n"
           "    return self.create_user(e, p)\n"
           "verify_password = _mine\n")
    assert auth_override_findings_1202s(_backend(tmp_path, custom_routes=src))


def test_tenant_scoping_an_identity_resolver_is_not_a_bypass(tmp_path):
    """r73 replaces get_current_user to ADD tenant isolation — the multi-tenancy the framework
    asks for. Blocking it would block a lane for tightening security (#566j's failure mode)."""
    assert auth_override_findings_1202s(_backend(tmp_path, custom_routes=_R73_TENANT)) == []


def test_a_narrowing_password_wrapper_is_not_a_bypass(tmp_path):
    """A wrapper that can only refuse where the original allowed is still a check."""
    assert auth_override_findings_1202s(_backend(tmp_path, custom_routes=_NARROWING)) == []


def test_the_provisioning_write_is_what_makes_it_a_bypass(tmp_path):
    """Measured over 93 runs: 5 reassign an auth primitive, 2 provision users. Only those 2 —
    r24 and r30, both confirmed to accept any password against the live stack — are blocked."""
    from multi_agent.runtime.backend_audit import _writes_users_1202s
    import ast
    prov = ast.parse("def f(self, e, p):\n    return self.create_user(e, p)\n").body[0]
    plain = ast.parse("def f(self, e, p):\n    return None\n").body[0]
    assert _writes_users_1202s(prov) is True
    assert _writes_users_1202s(plain) is False


def test_ordinary_lane_routes_are_not_flagged(tmp_path):
    src = ("from fastapi import APIRouter\n"
           "router = APIRouter()\n"
           "@router.get('/api/titles')\n"
           "def titles(user=Depends(get_current_user)):\n"
           "    return {'items': []}\n")
    assert auth_override_findings_1202s(_backend(tmp_path, custom_routes=src)) == []


def test_calling_an_auth_primitive_is_fine_only_assigning_is_not(tmp_path):
    """Lane code SHOULD call the check; the defect is replacing it."""
    src = ("def login(email, password, store):\n"
           "    user = store.verify_user_password(email, password)\n"
           "    if user is None:\n"
           "        raise ValueError('invalid credentials')\n"
           "    return user\n")
    assert auth_override_findings_1202s(_backend(tmp_path, custom_routes=src)) == []


def test_the_frameworks_own_module_is_never_flagged(tmp_path):
    """main.py and oauth_store.py DEFINE these functions — only lane-owned files are read."""
    src = "class OAuthStore:\n    def verify_user_password(self, e, p):\n        return None\n"
    b = _backend(tmp_path, main=src)
    (b / "oauth_store.py").write_text(src, encoding="utf-8")
    assert auth_override_findings_1202s(b) == []


def test_a_missing_or_unparsable_file_returns_nothing(tmp_path):
    assert auth_override_findings_1202s(tmp_path / "nope") == []
    b = _backend(tmp_path, custom_routes="def broken(:\n")
    assert auth_override_findings_1202s(b) == []


def test_it_blocks_delivery(tmp_path):
    from multi_agent.runtime.deliverability import _auth_override_blockers_1202s
    (tmp_path / "backend").mkdir(parents=True)
    (tmp_path / "backend" / "custom_routes.py").write_text(_R30, encoding="utf-8")
    assert len(_auth_override_blockers_1202s(tmp_path)) == 1
