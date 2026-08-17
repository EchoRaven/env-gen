r"""#574 (netflix r138, live): `_seed_demo_login` read the EMAIL from the seed row but
HARDCODED the password to the framework default:

    return {"email": str(users[0]["email"]), "password": "password", ...}

The seed LOADER does not work that way. `seed_data.py` honours a row's own plaintext:

    pw = row.pop('password', None) or 'password'
    row['password_hash'] = sha256(pw + _PASSWORD_SALT)

r138's `seed_data.json` first user is `demo@netflix.test` with `password: 'Demo!2345'`, so the
DB held sha256('Demo!2345'+salt) while every QA login sent 'password'. Verified against the
live container: POST /auth/login {"email":"avachen@example.com","password":"password"} → 401
"invalid credentials", with both salts identical (`app_sandbox_salt_2024`) and both schemes
sha256 — the scheme was never the problem, the plaintext was.

Blast radius, all on an app whose auth was fine:
  * the browser form drive failed        → auth_ok=False
  * #504's direct-API corroboration failed → api_login_ok=False, so the escape never armed
  * → hollow_frontend + 10 pages "bouncing to auth" → delivery hard-deferred 11 times / 54 min
  * and the walk browsed as a NON-populated user, so data pages looked blank — precisely the
    failure `_seed_demo_login`'s own docstring says it exists to prevent.

Fix: mirror the loader's rule exactly — the row's own plaintext when present, the framework
default only when absent.
"""
import json

import pytest

from env_generator.llm_generator.multi_agent.runtime.visual_fidelity import _seed_demo_login


def _project(tmp_path, users, *, as_json=True):
    backend = tmp_path / "app" / "backend"
    backend.mkdir(parents=True)
    if as_json:
        (backend / "seed_data.json").write_text(json.dumps({"users": users}), encoding="utf-8")
    return tmp_path


def test_r138_a_row_with_its_own_password_is_honoured(tmp_path):
    p = _project(tmp_path, [{"email": "demo@netflix.test", "name": "Demo Watcher",
                             "password": "Demo!2345", "password_hash": None}])
    creds = _seed_demo_login(p)
    assert creds == {"email": "demo@netflix.test", "password": "Demo!2345",
                     "name": "Demo Watcher"}, creds


def test_the_framework_default_still_applies_when_the_row_has_none(tmp_path):
    """The loader's `or 'password'` branch — unchanged behaviour for seeds without one."""
    for row in ({"email": "a@b.c", "name": "A"},
                {"email": "a@b.c", "name": "A", "password": None},
                {"email": "a@b.c", "name": "A", "password": ""}):
        creds = _seed_demo_login(_project(tmp_path / str(id(row)), [row]))
        assert creds["password"] == "password", row


def test_it_matches_the_loader_rule_for_every_shape(tmp_path):
    """The rule under test IS `row.pop('password', None) or 'password'`."""
    for row, expected in (({"email": "x@y.z", "password": "Secret!1"}, "Secret!1"),
                          ({"email": "x@y.z", "password": "0"}, "0"),
                          ({"email": "x@y.z"}, "password")):
        loader = row.get("password") or "password"
        creds = _seed_demo_login(_project(tmp_path / str(abs(hash(str(row)))), [row]))
        assert creds["password"] == loader == expected, (row, creds)


def test_a_hash_only_row_does_not_invent_a_plaintext(tmp_path):
    """A row carrying only a hash has no usable plaintext — fall back, never guess."""
    p = _project(tmp_path, [{"email": "h@a.sh", "password_hash": "deadbeef"}])
    assert _seed_demo_login(p)["password"] == "password"


def test_no_users_no_creds(tmp_path):
    assert _seed_demo_login(_project(tmp_path, [])) is None


def test_the_password_is_no_longer_hardcoded():
    """Guard: the literal that caused this must not come back."""
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import visual_fidelity
    src = inspect.getsource(visual_fidelity._seed_demo_login)
    assert '"password": "password"' not in src, "the hardcoded password is back"
    assert 'users[0].get("password")' in src


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
