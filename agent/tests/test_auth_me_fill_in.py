"""The scaffold fills in a canonical current-user endpoint when nothing registered one
(outlook run-27 + run-29, 2026-07-01).

The frontend's session restore (ProtectedRoute) calls the auth-prefixed "current user"
endpoint, but NOTHING guaranteed it exists: the projector excludes the /auth|/oauth control
surface, the coverage gate excludes it too, and the lane only sometimes writes it. run-29
live: /api/auth/me 404 → every protected page bounced to /login → login_wall + hollow=True
browser verdict → delivery deferral churn. The _CUSTOM_ROUTES_INCLUDE block now registers
/api/auth/me + /auth/me AFTER the custom include, each ONLY if absent — a lane-authored /me
always wins. ENV-AGNOSTIC + LOCAL-ONLY (agent/tests/ gitignored).
"""

import datetime
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.backend_skeleton import _CUSTOM_ROUTES_INCLUDE  # noqa: E402


class _Route:
    def __init__(self, path):
        self.path = path
        self.methods = ["GET"]


class _App:
    def __init__(self, paths=()):
        self.routes = [_Route(p) for p in paths]
        self.registered = {}

    def get(self, path):
        def deco(fn):
            self.registered[path] = fn
            self.routes.append(_Route(path))
            return fn
        return deco

    def include_router(self, r):
        pass


def _substituted():
    """Every placeholder render_skeleton_main fills, filled the same way.

    The template gained __DEGENERATE_RESOURCES__ after this test was written and
    nothing here knew: exec'ing it raised `NameError: name
    '__DEGENERATE_RESOURCES__' is not defined` at line 32 and took all 7 tests
    with it. The assertion below is the part that matters — the next placeholder
    added to the template fails HERE, naming itself, instead of as a NameError
    from inside an exec.
    """
    tmpl = (_CUSTOM_ROUTES_INCLUDE
            .replace("__NESTED_CHILD_RESOURCES__", "[]")
            .replace("__OWNER_SCOPED_RESOURCES__", "[]")
            .replace("__DEGENERATE_RESOURCES__", "[]"))
    left = sorted(set(re.findall(r"__[A-Z][A-Z0-9_]*__", tmpl)))
    assert not left, f"unsubstituted template placeholders: {left}"
    return tmpl


def _run_template(existing_paths=()):
    tmpl = _substituted()
    app = _App(existing_paths)
    ns = {"app": app, "Depends": lambda f: None, "get_current_user": lambda: None,
          "get_db": lambda: None}
    exec(compile(tmpl, "custom_include.py", "exec"), ns)
    return app


def test_fills_both_me_paths_when_absent():
    app = _run_template()
    assert "/api/auth/me" in app.registered and "/auth/me" in app.registered


def test_lane_authored_me_wins():
    app = _run_template(existing_paths=("/api/auth/me",))
    assert "/api/auth/me" not in app.registered      # lane's kept, no shadow
    assert "/auth/me" in app.registered              # the missing alias is still filled


def test_nothing_registered_when_both_present():
    app = _run_template(existing_paths=("/api/auth/me", "/auth/me"))
    # both /me paths present -> no ME registration; the tenants fill-in is separate
    assert "/api/auth/me" not in app.registered and "/auth/me" not in app.registered



def test_handler_serializes_user_object():
    app = _run_template()
    fn = app.registered["/api/auth/me"]

    class U:
        id = 11
        email = "a@b.c"
        name = "A"
        password_hash = "SECRET"
        created_at = datetime.datetime(2026, 7, 1, 12, 0, 0)
    out = fn(user=U())
    item = out["item"]
    assert item["id"] == 11 and item["email"] == "a@b.c"
    assert item["created_at"] == "2026-07-01T12:00:00"
    assert "password_hash" not in item               # only the allow-listed fields


def test_handler_tolerates_dict_and_bare_id():
    app = _run_template()
    fn = app.registered["/api/auth/me"]
    assert fn(user={"id": "u-1", "email": "x@y.z"})["item"] == {"id": "u-1", "email": "x@y.z"}
    assert fn(user=7)["item"] == {"id": 7}           # dependency returned a bare id


def test_template_is_valid_python():
    compile(_substituted(), "custom_include.py", "exec")


def test_tenants_list_filled_when_absent():
    app = _run_template()
    assert "/api/v1/tenants" in app.registered
    out = app.registered["/api/v1/tenants"](db=None)
    assert out["items"] == [{"id": "default", "name": "default"}]   # no models module → fallback
    assert out["tenants"] == out["items"]


def test_lane_authored_tenants_wins():
    app = _run_template(existing_paths=("/api/v1/tenants",))
    assert "/api/v1/tenants" not in app.registered


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
