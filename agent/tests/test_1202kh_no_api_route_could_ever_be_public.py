"""#1202kh: three layers agreed the route was public, and the guard denied it anyway.

tiktok-r114, live, against the running container:

    $ curl -s -o /dev/null -w '%{http_code}' localhost:8008/api/videos/feed
    401   {"detail":"missing or invalid token"}

while the contract registered that endpoint `auth_required: false`, and the app's own
`/openapi.json` named the serving handler `_projected_get_api_videos_feed_0` — rendered as
`def _projected_get_api_videos_feed_0(db=Depends(get_db))`, with no user dependency at all.
The logged-out landing page sat on "Loading...".

The denial came from `_framework_auth_guard`, FIX #47's blanket middleware: "enforces a valid
RS256 bearer token on every /api/ business route". #47 was written for a real defect (lanes
shipping unguarded handlers), but it predates the per-endpoint `auth_required` the rest of the
framework now runs on, and the layers had drifted apart:

  * the projector builds a contract-public handler with NO guard;
  * #1202ih stopped the validator demanding a 401 from one;
  * this middleware denied it anyway, and it is framework-projected, so no lane could fix it.

Measured: 77 of the 153 corpus runs declare at least one public /api/ endpoint — 451 of them
(412 GET, 38 POST, 1 PATCH) — and every one was denied. That is the mechanism behind the top
ui_flow failure signature (401, 21 of 54 recent failures), and #320's "logged-out surface" has
been unreachable by construction for as long as both mechanisms have coexisted.

WHAT IS VERIFIED: the emitted set comes from the SAME `auth` value `_generate_handler` is
given, so guard and handler cannot disagree; a protected route is still denied; a main.py this
skeleton did not render keeps #47's blanket rule exactly; and the path matcher is exact
(no prefix, no method bleed, `{param}` bounded to one segment).

WHAT IS NOT: that any lane's declaration is now trusted more than before. `resolve_endpoint_auth`
+ #1202ht + #633 decide `auth`, unchanged — this only stops a second, blind rule from
overriding the decision they already made.
"""
import sys
import pathlib

_AGENT = pathlib.Path(__file__).resolve().parents[1]
# House style, and NOT a detail: insert `llm_generator`, never `multi_agent` itself.
# `multi_agent/` contains its own `tests/` package, so putting it on sys.path ahead of `agent/`
# shadows `agent/tests` — and `test_kickoff_run_kickoff_finalize_hardening.py`, which does
# `from tests.test_kickoff_run_kickoff import ...`, then fails to COLLECT and takes the whole
# suite down with it. Passed alone; only the full run showed it.
_LLM = _AGENT / "env_generator" / "llm_generator"
for _p in (str(_LLM), str(_AGENT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import ast                                                             # noqa: E402
import re                                                              # noqa: E402

from multi_agent.runtime.backend_scaffold import _AUTH_MIDDLEWARE                  # noqa: E402
from multi_agent.runtime.backend_skeleton import render_skeleton_main              # noqa: E402


_TABLES = {"videos": {"name": "videos", "schema": {"columns": [
    {"name": "id", "type": "int"}, {"name": "caption", "type": "text"}]}}}


def _ep(method, path, auth, rk="items"):
    return {"method": method, "path": path, "auth_required": auth, "response_key": rk,
            "schema": {"auth_required": auth, "response": {"tables": ["videos"]}}}


def _render(eps):
    return render_skeleton_main(eps, _TABLES)


def _emitted(src):
    """The literal the skeleton wrote, read back with `ast` — not a regex over source
    (#923: no span locator that ends on a bare delimiter)."""
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "_FW_PUBLIC_API_1202KH"
                for t in node.targets):
            return [tuple(v) for v in ast.literal_eval(node.value)]
    raise AssertionError("_FW_PUBLIC_API_1202KH was not emitted")


def _matcher(public):
    """Execute the middleware's OWN matcher, so the test cannot pass against a
    reimplementation of it."""
    head = _AUTH_MIDDLEWARE.split("@app.middleware")[0]
    head = head[head.index("try:\n    _FW_PUBLIC_API_1202KH"):]
    g = {"_fw_re": re, "_FW_PUBLIC_API_1202KH": list(public)}
    exec(compile(head, "<middleware>", "exec"), g)      # noqa: S102 — the shipped source
    return g["_fw_contract_public_1202kh"]


# --- what gets emitted ----------------------------------------------------------------------

def test_a_contract_public_read_is_emitted():
    """★ r114's endpoint."""
    src = _render([_ep("GET", "/api/videos/feed", False)])
    assert ("GET", "/api/videos/feed") in _emitted(src)


def test_a_protected_route_is_not_emitted():
    """★ The floor. Without it the fix could be emitting everything."""
    src = _render([_ep("GET", "/api/videos/feed", False), _ep("POST", "/api/videos", True)])
    got = _emitted(src)
    assert ("GET", "/api/videos/feed") in got
    assert ("POST", "/api/videos") not in got


def test_a_contract_public_WRITE_is_not_emitted():
    """★ READS ONLY, and the asymmetry is deliberate — it is not the contract half-followed.

    Of the 451 contract-public /api/ endpoints in the corpus, 412 are GET. Of the 39 writes,
    20 are auth entry points this middleware already exempts BY NAME and 16 are a share
    counter. The remaining two — a `POST /api/videos` and a `PATCH /api/notifications/{id}`
    marked public — are contract ERRORS, and honouring them would hand an unauthenticated
    caller a projected create with no actor: the null-owner row #317 and #1202jd exist to
    prevent. A denied public write costs a share button; an opened public create costs the
    seeded data the visual gate compares against.

    Nothing pinned this when the narrowing was made — all 16 tests here passed before and
    after — so it is pinned now."""
    src = _render([_ep("POST", "/api/videos", False, rk="item"),
                   _ep("GET", "/api/videos/feed", False)])
    got = _emitted(src)
    assert ("GET", "/api/videos/feed") in got
    assert ("POST", "/api/videos") not in got, (
        "a contract-public WRITE must keep #47's blanket rule")


def test_the_projector_applies_the_same_read_only_filter():
    """★ Two emitters, one rule. If they disagreed, whether a write was open would depend on
    which code path last wrote main.py — the drift #1202kh exists to end."""
    import inspect
    import textwrap
    from multi_agent.runtime import backend_skeleton as BK
    from multi_agent.runtime import route_projector as RP

    def _guard_of_the_append(fn):
        """The `if` that guards the append, found in the parse tree — not by a source span
        between two landmarks, which silently matched the DECLARATION line instead (#923)."""
        tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
        for node in ast.walk(tree):
            if not isinstance(node, ast.If):
                continue
            # DIRECT children only. `ast.walk` yields the outermost `if` first, and an
            # enclosing `if block_info:` also *contains* the append somewhere below it —
            # which is how the first version of this test read `block_info` as the guard.
            for stmt in node.body:
                call = stmt.value if isinstance(stmt, ast.Expr) else None
                if (isinstance(call, ast.Call)
                        and isinstance(call.func, ast.Attribute)
                        and call.func.attr == "append"
                        and isinstance(call.func.value, ast.Name)
                        and call.func.value.id.endswith("_1202kh")):
                    return ast.dump(node.test)
        raise AssertionError(f"{fn.__name__} does not collect a #1202kh public set")

    for fn in (BK.render_skeleton_main, RP.project_missing_routes):
        guard = _guard_of_the_append(fn)
        assert "'GET'" in guard and "'HEAD'" in guard, (
            f"{fn.__name__} must filter to safe methods before collecting the public set: "
            f"{guard[:200]}")


def test_the_control_plane_is_not_re_emitted():
    """/api/v1/* is already public in the middleware's own list; listing it twice is the
    duplicated-fixed-surface shape #853 was."""
    src = _render([_ep("GET", "/api/v1/tenants", False)])
    assert _emitted(src) == []


def test_the_emitted_set_matches_the_handlers_that_were_built_without_an_actor():
    """★ The whole point: ONE derivation. Every emitted route must be a route whose rendered
    handler has no `user=Depends(...)`, and every no-actor /api/ handler must be emitted."""
    src = _render([_ep("GET", "/api/videos/feed", False),
                   _ep("GET", "/api/videos/{id}", False),
                   _ep("POST", "/api/videos", True)])
    emitted = {p for _m, p in _emitted(src)}
    tree = ast.parse(src)
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef) or not node.name.startswith("_projected_"):
            continue
        route = None
        for dec in node.decorator_list:
            if isinstance(dec, ast.Call) and dec.args and isinstance(dec.args[0], ast.Constant):
                route = dec.args[0].value
        if not isinstance(route, str) or not route.startswith("/api/"):
            continue
        has_actor = any(a.arg == "user" for a in node.args.args)
        assert (route in emitted) is (not has_actor), (
            f"{route}: emitted={route in emitted} but handler has_actor={has_actor}")


# --- the matcher the middleware actually runs -----------------------------------------------

def test_the_middleware_lets_the_emitted_route_through():
    """★ Reachability, not presence: the list is worthless unless the guard reads it."""
    src = _render([_ep("GET", "/api/videos/feed", False)])
    assert _matcher(_emitted(src))("GET", "/api/videos/feed") is True


def test_the_method_must_match_too():
    m = _matcher([("GET", "/api/videos/feed")])
    assert m("GET", "/api/videos/feed") is True
    assert m("POST", "/api/videos/feed") is False


def test_a_param_matches_exactly_one_segment():
    """`/api/places/{id}` must not swallow `/api/places/42/secrets`."""
    m = _matcher([("GET", "/api/places/{id}")])
    assert m("GET", "/api/places/42") is True
    assert m("GET", "/api/places/42/secrets") is False


def test_a_longer_path_that_merely_starts_the_same_is_denied():
    """A prefix rule here would publish siblings the contract never declared."""
    m = _matcher([("GET", "/api/videos/feed")])
    assert m("GET", "/api/videos/feedback") is False
    assert m("GET", "/api/videos/feed/secret") is False


def test_a_trailing_slash_is_the_same_route():
    assert _matcher([("GET", "/api/videos/feed")])("GET", "/api/videos/feed/") is True


def test_an_empty_set_denies_everything():
    """★ Fail closed. This is also the `repair_auth_enforcement_middleware` heal path, where
    the skeleton never ran and #47's blanket rule must stand unchanged."""
    m = _matcher([])
    for p in ("/api/videos/feed", "/api/anything", "/api/"):
        assert m("GET", p) is False


def test_the_middleware_survives_a_main_py_without_the_literal():
    """The heal path injects this string into a main.py the skeleton did not render, so the
    NameError guard is what keeps that app booting at all."""
    assert "except NameError:" in _AUTH_MIDDLEWARE
    assert "_FW_PUBLIC_API_1202KH = []" in _AUTH_MIDDLEWARE


def test_the_guard_consults_the_contract_before_denying():
    """The call has to sit BEFORE the `/api/` denial, or it can never take effect."""
    body = _AUTH_MIDDLEWARE
    assert body.index("_fw_contract_public_1202kh(request.method, p)") < body.index(
        'if p.startswith("/api/") and not public')


# --- staleness: the projector adds handlers to a main.py the skeleton wrote once -------------

def test_a_route_projected_later_is_added_to_the_public_set():
    """★ #1202kh's list is emitted by `render_skeleton_main`, which runs ONCE, while
    `project_missing_routes` inserts handlers into that same file every cycle. Without the
    refresh, an endpoint a lane registers mid-run gets a no-actor handler and stays denied —
    the #1202ju / #1202ic staleness shape one artefact over."""
    from multi_agent.runtime.route_projector import refresh_public_api_1202kh as refresh
    src = _render([_ep("GET", "/api/videos/feed", False)])
    out = refresh(src, [("GET", "/api/sounds")])
    assert _emitted(out) == [("GET", "/api/videos/feed"), ("GET", "/api/sounds")]
    ast.parse(out)


def test_the_refresh_unions_and_never_replaces():
    """★ The projector sees only the endpoints it is projecting THIS cycle. Replacing would
    drop the skeleton's own entries and silently re-deny them.

    Two skeleton entries and ONE incoming entry, deliberately: a replace then changes the
    LENGTH, so the `len(merged) == len(have)` short-circuit cannot make this pass vacuously —
    which it did when the fixture had one of each."""
    from multi_agent.runtime.route_projector import refresh_public_api_1202kh as refresh
    src = _render([_ep("GET", "/api/videos/feed", False),
                   _ep("GET", "/api/videos/{id}", False, rk="item")])
    have = _emitted(src)
    assert len(have) == 2, have
    out = refresh(src, [("GET", "/api/sounds")])
    got = _emitted(out)
    assert got == have + [("GET", "/api/sounds")], got


def test_the_refresh_is_idempotent():
    """A no-op cycle must not rewrite the file — a churned mtime is what #934 and #1202jn
    were both about."""
    from multi_agent.runtime.route_projector import refresh_public_api_1202kh as refresh
    src = _render([_ep("GET", "/api/videos/feed", False)])
    assert refresh(src, [("GET", "/api/videos/feed")]) is src


def test_a_main_py_without_the_literal_is_left_alone():
    """The heal path's main.py has the middleware but no list; rewriting it blindly would
    corrupt a file the skeleton does not own."""
    from multi_agent.runtime.route_projector import refresh_public_api_1202kh as refresh
    assert refresh("x = 1\n", [("GET", "/api/x")]) == "x = 1\n"
