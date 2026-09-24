"""#235 (tiktok r25 no-convergence abort, live): the contract declared its auth
entry point as POST /api/auth/signup — a SYNONYM the framework's literal
whitelists didn't know. Three layers each failed:

  a) the skeleton's auth guard walled /api/auth/signup (only login/register were
     public) → 401 on every unauthenticated call, and the lane's fix was
     overwritten every tick by the framework-owned skeleton → 108-min livelock;
  b) nothing ever SERVED /api/auth/signup (the AS router only has register/login);
  c) the verifier-authored chain step used the synonym path so it bypassed every
     chain auth invariant, and carried a self-dependent auth="token" on the very
     step that mints the token.
"""
import re

import pytest

from env_generator.llm_generator.multi_agent.runtime import backend_scaffold
from env_generator.llm_generator.multi_agent.runtime import backend_skeleton
from env_generator.llm_generator.multi_agent.runtime.chain_executor import normalize_steps


# ---------- a) guard whitelist ----------

def _public_predicate():
    """Extract the `public = (...)` expression from the rendered middleware and
    compile it into a callable p -> bool (the expression references only `p`)."""
    src = backend_scaffold._AUTH_MIDDLEWARE
    m = re.search(r"public = \((.*?)\n    \)", src, re.S)
    assert m, "public predicate not found in _AUTH_MIDDLEWARE"
    expr = "(" + m.group(1) + ")"
    return lambda p: bool(eval(expr, {"p": p}))  # noqa: S307 — test-only, own template


@pytest.mark.parametrize("path", [
    "/api/auth/login", "/api/auth/register",           # pre-#235 literals
    "/api/auth/signup", "/api/auth/signin",            # r25's synonym class
    "/api/auth/token", "/api/auth/refresh", "/api/auth/logout",
])
def test_guard_marks_bootstrap_synonyms_public(path):
    assert _public_predicate()(path), f"{path} must be public (auth entry point)"


@pytest.mark.parametrize("path", [
    "/api/auth/me",              # current-user stays guarded (its Depends re-checks)
    "/api/videos", "/api/feed",  # business routes stay guarded
    "/api/auth/signup/extra",    # only the terminal segment is a bootstrap
])
def test_guard_keeps_everything_else_guarded(path):
    assert not _public_predicate()(path), f"{path} must stay guarded"


# ---------- b) skeleton alias fill-in ----------

class _FakeRoute:
    def __init__(self, path, endpoint=None, methods=("POST",)):
        self.path, self.endpoint, self.methods = path, endpoint, set(methods)


class _FakeApp:
    def __init__(self, routes):
        self.routes = list(routes)
        self.added = []
        self.added_kwargs = []

    def add_api_route(self, path, fn, methods=None, **kwargs):
        # **kwargs: the real FastAPI signature takes many more. #1103 added
        # response_model=None here and this stub rejected it — a fixture that
        # pins an argument LIST fails on any addition to the call, which is not
        # what these tests are about. `added_kwargs` keeps them assertable.
        self.added.append((path, fn, tuple(methods or ())))
        self.added_kwargs.append(kwargs)
        self.routes.append(_FakeRoute(path, fn, methods or ("POST",)))


def _alias_block_source():
    src = backend_skeleton.__dict__.get("__file__") and open(
        backend_skeleton.__file__, encoding="utf-8").read()
    # Anchored on the block's own landmarks, not on the last line of the
    # add_api_route CALL: #1103 wrapped that call across two lines and the old
    # pattern stopped matching, failing these tests for a formatting change
    # (#943's lesson — a slice must not be pinned to text that legitimately grows).
    m = re.search(
        r"(    _fw_alias_of = \{\"signup\".*?)\n *# TENANTS-LIST FILL-IN",
        src, re.S)
    assert m, "#235 alias fill-in block not found in backend_skeleton template"
    import textwrap
    return textwrap.dedent(m.group(1))


def test_alias_fillin_serves_signup_and_signin_from_canonical_handlers():
    def register_fn():  # canonical AS handlers
        return "register"

    def login_fn():
        return "login"

    app = _FakeApp([
        _FakeRoute("/auth/register", register_fn), _FakeRoute("/auth/login", login_fn),
        _FakeRoute("/api/auth/register", register_fn), _FakeRoute("/api/auth/login", login_fn),
    ])
    exec(_alias_block_source(), {"app": app})
    added = {p: fn for p, fn, _ in app.added}
    # #1103: every alias must pin response_model=None. The AS handlers are
    # `-> JSONResponse` under future-annotations, and letting FastAPI infer a model
    # from that string put ForwardRef('JSONResponse') on four routes in tiktok-r92
    # and 500'd its /openapi.json.
    assert app.added_kwargs and all(k.get("response_model", "MISSING") is None
                                    for k in app.added_kwargs), app.added_kwargs
    assert added["/api/auth/signup"] is register_fn
    assert added["/auth/signup"] is register_fn
    assert added["/api/auth/signin"] is login_fn
    assert added["/auth/signin"] is login_fn


def test_alias_fillin_lane_authored_route_wins():
    def lane_signup():
        return "lane"

    def register_fn():
        return "register"

    app = _FakeApp([
        _FakeRoute("/auth/register", register_fn),
        _FakeRoute("/api/auth/register", register_fn),
        _FakeRoute("/api/auth/signup", lane_signup),   # lane already wrote it
    ])
    exec(_alias_block_source(), {"app": app})
    assert "/api/auth/signup" not in {p for p, _, _ in app.added}
    assert "/auth/signup" in {p for p, _, _ in app.added}  # absent one still filled


# ---------- c) chain normalization ----------

def test_chain_signup_synonym_collapses_and_sheds_self_dependent_auth():
    steps, errors = normalize_steps([
        {"method": "POST", "path": "/api/auth/signup", "auth": "token",
         "expect": [200, 201], "save": {"token": "access_token"}},
        {"method": "GET", "path": "/api/feed", "auth": "token", "expect": [200]},
    ])
    assert not errors
    boot = steps[0]
    # r25's exact authored shape: synonym path + self-dependent auth
    assert boot["path"] == "/auth/register"
    assert "auth" not in boot, "token-minting step must never send a bearer"
    assert boot["save"].get("token") == "access_token"
    assert {200, 201, 409} <= set(boot["expect"])
    assert isinstance(boot.get("body"), dict) and boot["body"].get("email")


def test_chain_signin_synonym_maps_to_login():
    steps, _ = normalize_steps([
        {"method": "POST", "path": "/auth/register", "expect": [201],
         "body": {"email": "a@b.c", "password": "x"}},
        {"method": "POST", "path": "/auth/signin", "auth": "token",
         "body": {"email": "a@b.c", "password": "x"}, "expect": [200]},
    ])
    by_path = [s["path"] for s in steps]
    # signin collapsed into the canonical login family (a lone login may further
    # normalize to register via the ensure-user invariant — both are bootstrap)
    assert "/auth/signin" not in by_path
    signin_step = steps[1]
    assert signin_step["path"] in ("/auth/login", "/auth/register")
    assert "auth" not in signin_step


def test_chain_bootstrap_strip_leaves_other_steps_alone():
    steps, _ = normalize_steps([
        {"method": "POST", "path": "/auth/register", "expect": [201],
         "body": {"email": "a@b.c", "password": "x"}},
        {"method": "GET", "path": "/api/videos", "expect": [200]},
    ])
    assert steps[1].get("auth") == "token"  # auto-auth on /api steps unchanged
