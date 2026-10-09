"""#1203gj: a lane route the framework DECIDED to keep must actually serve.

``_custom_route_overrides_projected`` returning True is the framework saying "the LANE owns
this path". But which handler serves is settled by REGISTRATION ORDER, and
``backend_skeleton`` emits its projected ``@app.get(...)`` handlers ABOVE the
``app.include_router(_custom_router)`` line, so the projection registered first and won.
MEASURED over the corpus: 18 endpoints across 15 runs where this predicate handed the path
to the lane and the lane lost; 13 of them the feed, plus tiktok-web-r167's
``/api/creators/suggested`` whose shadower is a hardcoded ``{"items": [], "total": 0}``.

Every test here execs the code the SKELETON actually emits, sliced out of
``backend_skeleton.py`` — the same technique #528's harness uses. A hand-copied hook would
prove something about the copy.
"""
import ast
import re
import textwrap
import types
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi import APIRouter, FastAPI            # noqa: E402
from fastapi.testclient import TestClient         # noqa: E402

SKEL = (Path(__file__).resolve().parents[1]
        / "env_generator/llm_generator/multi_agent/runtime/backend_skeleton.py")


def _slice_def(src: str, header: str) -> str:
    """The whole ``def``/``async def`` block starting at *header*, dedented."""
    i = src.find(header)
    assert i >= 0, "not found in backend_skeleton.py: %s" % header
    lines = src[i:].split("\n")
    base = len(lines[0]) - len(lines[0].lstrip())
    out = [lines[0]]
    for ln in lines[1:]:
        if ln.strip() and (len(ln) - len(ln.lstrip())) <= base:
            break
        out.append(ln)
    return textwrap.dedent("\n".join(out))


SKEL_SRC = SKEL.read_text(encoding="utf-8")
PRED_SRC = _slice_def(SKEL_SRC, "def _custom_route_overrides_projected(method, path):")
HOOK_SRC = _slice_def(SKEL_SRC, "async def _fw_unshadow_lane_overrides_1203gj():")


# The three sets the predicate closes over, as tiktok-web-r167 actually rendered them
# (`_DEGENERATE_RESOURCES` was empty there). Only membership matters to the branches below;
# `videos` is present so a bare collection GET reaches the #528 projected-wins branch, and
# the premise assertions in the tests fail loudly if that stops being true.
_R167_SETS = {
    "_OWNER_SCOPED_RESOURCES": {"comment", "comments", "commentss", "saved_video",
                                "saved_videos", "message", "messages", "video", "videos"},
    "_NESTED_CHILD_RESOURCES": {"comment", "comments", "commentss", "conversation",
                                "video", "videos"},
    "_DEGENERATE_RESOURCES": set(),
}


def _predicate():
    ns: dict = dict(_R167_SETS)
    exec(compile(PRED_SRC, "<pred>", "exec"), ns)
    return ns["_custom_route_overrides_projected"]


def _lane_module(routes):
    """A real module named ``custom_routes`` — the hook identifies lane handlers by
    ``endpoint.__module__``, so the function must genuinely be defined in that module."""
    mod = types.ModuleType("custom_routes")
    mod.__dict__["router"] = APIRouter()
    src = "\n".join(routes)
    exec(compile(src, "custom_routes", "exec"), mod.__dict__)
    return mod


def _build(projected, lane_routes, fixed_paths=()):
    """The r167 shape: projected handlers at module top, lane router included afterwards."""
    app = FastAPI()
    for method, path, body in projected:
        ns = {"app": app}
        exec(compile(
            '@app.%s("%s")\ndef _projected_%s():\n    return %s\n'
            % (method.lower(), path, re.sub(r"\W", "_", path).strip("_"), body),
            "<projected>", "exec"), ns)
    lane = _lane_module(lane_routes)
    app.include_router(lane.router)
    fixed = [r for r in app.router.routes
             if str(getattr(r, "path", "")) in set(fixed_paths)
             and getattr(getattr(r, "endpoint", None), "__module__", "") != "custom_routes"]
    ns = {"app": app,
          "_custom_route_overrides_projected": _predicate(),
          "_FW_FIXED_ROUTES_1202KI": fixed}
    exec(compile(HOOK_SRC.replace("async def ", "def ", 1), "<hook>", "exec"), ns)
    return app, ns["_fw_unshadow_lane_overrides_1203gj"]


R167_LANE = [
    '@router.get("/api/creators/suggested")',
    'def get_suggested_creators():',
    '    return {"items": [{"id": 1, "username": "real"}], "total": 1}',
]


def test_the_projected_stub_wins_before_the_hook_runs():
    """The premise. Without this hook FastAPI serves the framework's empty stub —
    tiktok-web-r167 shipped exactly this pair."""
    app, _hook = _build(
        [("get", "/api/creators/suggested", '{"items": [], "total": 0}')], R167_LANE)
    assert TestClient(app).get("/api/creators/suggested").json() == {
        "items": [], "total": 0}


def test_the_lane_handler_serves_after_the_hook_runs():
    app, hook = _build(
        [("get", "/api/creators/suggested", '{"items": [], "total": 0}')], R167_LANE)
    hook()
    body = TestClient(app).get("/api/creators/suggested").json()
    assert body == {"items": [{"id": 1, "username": "real"}], "total": 1}, body


def test_the_feed_is_unshadowed_too():
    """13 of the 18 measured endpoints are the feed under one of four spellings."""
    for path in ("/api/videos/feed", "/api/feed/for-you",
                 "/api/videos/foryou", "/api/feed/videos"):
        lane = ['@router.get("%s")' % path,
                'def lane_feed():',
                '    return {"items": ["lane"]}']
        app, hook = _build([("get", path, '{"items": []}')], lane)
        hook()
        got = TestClient(app).get(path).json()
        assert got == {"items": ["lane"]}, (path, got)


def test_a_path_the_predicate_gives_to_the_projection_is_left_alone():
    """The reverse half. #528/#77: a bare collection GET keeps the schema-safe projected
    read so a buggy lane handler cannot 500-shadow it. The predicate must still decide
    that, and this hook must not override it."""
    pred = _predicate()
    assert pred("GET", "/api/videos") is False, (
        "premise gone: the predicate no longer gives a bare collection to the projection")
    lane = ['@router.get("/api/videos")',
            'def lane_videos():',
            '    return {"items": ["lane"]}']
    app, hook = _build([("get", "/api/videos", '{"items": ["projected"]}')], lane)
    hook()
    assert TestClient(app).get("/api/videos").json() == {"items": ["projected"]}


def test_a_shadower_on_the_framework_fixed_surface_is_kept_and_reported(caplog):
    """#1202ki owns the auth/oauth surface; a lane handler cannot replace it, and the hook
    must say so rather than skip in silence."""
    pred = _predicate()
    assert pred("GET", "/auth/me") is True, (
        "premise gone: the predicate no longer hands /auth/me to the lane, so this case "
        "can no longer arise and the guard below is untested")
    lane = ['@router.get("/auth/me")',
            'def lane_me():',
            '    return {"who": "lane"}']
    app, hook = _build([("get", "/auth/me", '{"who": "framework"}')], lane,
                       fixed_paths=("/auth/me",))
    with caplog.at_level("WARNING"):
        hook()
    assert TestClient(app).get("/auth/me").json() == {"who": "framework"}
    assert "framework fixed surface" in caplog.text, caplog.text


def test_the_hook_removes_the_shadower_not_the_lane_route():
    app, hook = _build(
        [("get", "/api/creators/suggested", '{"items": [], "total": 0}')], R167_LANE)
    before = len([r for r in app.router.routes
                  if str(getattr(r, "path", "")) == "/api/creators/suggested"])
    assert before == 2
    hook()
    left = [r for r in app.router.routes
            if str(getattr(r, "path", "")) == "/api/creators/suggested"]
    assert len(left) == 1, left
    assert getattr(left[0].endpoint, "__module__", "") == "custom_routes"


def test_the_hook_says_what_it_did(caplog):
    app, hook = _build(
        [("get", "/api/creators/suggested", '{"items": [], "total": 0}')], R167_LANE)
    with caplog.at_level("WARNING"):
        hook()
    assert "unshadowed 1 lane route" in caplog.text, caplog.text
    assert "/api/creators/suggested" in caplog.text


def test_the_hook_is_registered_after_1166_and_1202ki():
    """Order is the whole point: this hook needs the final table, with #1202ki's
    framework routes already re-inserted at the front."""
    order = [m.group(1) for m in re.finditer(
        r"async def (_fw_[A-Za-z0-9_]+)\(\):", SKEL_SRC)]
    for earlier in ("_fw_restore_unserved_dropped_1166",
                    "_fw_restore_fixed_surface_1202ki"):
        assert earlier in order, order
        assert order.index(earlier) < order.index(
            "_fw_unshadow_lane_overrides_1203gj"), order


def test_the_hook_reaches_the_generated_app():
    """The hook must sit inside the template's `try: import custom_routes` block — outside
    it, neither the lane module nor `_custom_router` exists. This region of
    backend_skeleton.py is a TEMPLATE STRING copied verbatim into main.py (the generated
    file carries the same indentation), so it is not reachable by ast.parse of the skeleton
    and the span is checked on the text."""
    start = SKEL_SRC.index("try:\n    import custom_routes as _custom_mod")
    end = SKEL_SRC.index("except ImportError as _custom_imp:", start)
    hook = SKEL_SRC.index("async def _fw_unshadow_lane_overrides_1203gj():")
    assert start < hook < end, (start, hook, end)
    # and it really is a template, not code the skeleton itself runs
    assert not [n for n in ast.walk(ast.parse(SKEL_SRC))
                if isinstance(n, ast.AsyncFunctionDef)
                and n.name == "_fw_unshadow_lane_overrides_1203gj"], (
        "the hook became real skeleton code — it is meant to be emitted into main.py")


def test_a_shadower_serving_a_method_the_lane_did_not_claim_is_kept(caplog):
    """Removing the whole route object would take its other methods with it, so a
    multi-method shadower is left in place and named."""
    lane = ['@router.get("/api/creators/suggested")',
            'def lane_sugg():',
            '    return {"who": "lane"}']
    app = FastAPI()
    def _multi():
        return {"who": "projected"}
    app.router.add_api_route("/api/creators/suggested", _multi,
                             methods=["GET", "POST"])
    mod = _lane_module(lane)
    app.include_router(mod.router)
    ns = {"app": app,
          "_custom_route_overrides_projected": _predicate(),
          "_FW_FIXED_ROUTES_1202KI": []}
    exec(compile(HOOK_SRC.replace("async def ", "def ", 1), "<hook>", "exec"), ns)
    with caplog.at_level("WARNING"):
        ns["_fw_unshadow_lane_overrides_1203gj"]()
    assert TestClient(app).get("/api/creators/suggested").json() == {"who": "projected"}
    assert "which the lane did not claim" in caplog.text, caplog.text
    assert "POST" in caplog.text, caplog.text


def test_a_projection_registered_AFTER_the_lane_route_is_untouched():
    """The majority case, and the one #1156 probed live: `project_missing_routes` APPENDS
    its handlers BELOW `include_router`, so the lane already wins — 2281 such endpoints
    across 171 corpus runs. The hook must not walk past the lane's own route and start
    deleting the projections behind it."""
    app = FastAPI()
    mod = _lane_module(['@router.get("/api/videos/feed")',
                        'def lane_feed():',
                        '    return {"items": ["lane"]}'])
    app.include_router(mod.router)                       # lane FIRST this time
    ns0 = {"app": app}
    exec(compile('@app.get("/api/videos/feed")\n'
                 'def _projected_appended():\n'
                 '    return {"items": ["projected"]}\n', "<appended>", "exec"), ns0)
    assert len([r for r in app.router.routes
                if str(getattr(r, "path", "")) == "/api/videos/feed"]) == 2
    ns = {"app": app,
          "_custom_route_overrides_projected": _predicate(),
          "_FW_FIXED_ROUTES_1202KI": []}
    exec(compile(HOOK_SRC.replace("async def ", "def ", 1), "<hook>", "exec"), ns)
    ns["_fw_unshadow_lane_overrides_1203gj"]()
    assert len([r for r in app.router.routes
                if str(getattr(r, "path", "")) == "/api/videos/feed"]) == 2, (
        "the hook deleted a projection the lane was already winning against")
    assert TestClient(app).get("/api/videos/feed").json() == {"items": ["lane"]}
