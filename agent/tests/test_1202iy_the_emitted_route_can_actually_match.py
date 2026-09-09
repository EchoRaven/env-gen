"""#1202iy: emit a `<Route path>` React Router can match, everywhere a route is emitted.

#1202ix established the fact from react-router 6.30.3's own source: compilePath takes a param
only via `.replace(/\\/:([\\w-]+)(\\?)?/g,...)`, so the `:` must directly follow a `/`. In
`/@:username` it follows `@`, no param is extracted, and the path compiles to the literal
`^/@:username` -- matching that exact URL and nothing else.

This is the repair. The literal moves INTO the param, so the URL is unchanged: `/@bob` still
routes and the param carries `@bob`. Nothing that matched before stops matching -- these paths
only ever matched their own spelling, which nobody navigates to.

Why the framework may decide this without asking the route contract: the page was never the
problem. r110's ProfileScreen reads `window.location.pathname` directly and guards
`!pathUsername.startsWith(':')` -- the lane had already seen the literal URL and routed around
the router. Nothing ever mounted the component.

37 such routes across 36 runs, all dead, essentially every tiktok `profile_own`. It matters
because the visual gate passes only once EVERY blocking screen clears the bar at least once
(#129), so one permanently-blank screen defers every delivery attempt: r110 called
deliver_project five times and every one was deferred by the visual gate.
"""
import sys
import pathlib
import re

_AGENT = pathlib.Path(__file__).resolve().parents[1]
if str(_AGENT) not in sys.path:
    sys.path.insert(0, str(_AGENT))

from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (  # noqa: E402
    _router_matchable_route_1202iy as _fix, _render_routed_app)
from env_generator.llm_generator.multi_agent.runtime import remediation_dispatcher as RD  # noqa: E402

_RR_PARAM = re.compile(r"/:([\w-]+)(\?)?")


def _react_router_params(path: str):
    """What react-router would actually extract, by its own regex."""
    return [m.group(1) for m in _RR_PARAM.finditer(path)]


def test_the_repaired_path_is_one_react_router_can_parse():
    """Decided by react-router's rule, not by restating the helper's."""
    for dead in ("/@:username", "/@:handle", "/user-:id/posts"):
        assert _react_router_params(dead) == [], dead
        assert _react_router_params(_fix(dead)), (dead, _fix(dead))


def test_the_param_name_survives():
    """The page may read `useParams().username`; renaming it would break a page that works."""
    assert _fix("/@:username") == "/:username"
    assert _fix("/user-:id/posts") == "/:id/posts"


def test_the_url_still_routes():
    """The whole safety argument: `/@bob` matched nothing before and matches now. Compiled
    with react-router's own transformation so this is not a claim about the helper."""
    compiled = "^" + re.sub(r"/:([\w-]+)", r"/([^/]+)", _fix("/@:username")) + "$"
    assert re.match(compiled, "/@bob"), compiled
    # and the old spelling matched only itself
    assert not re.match("^/@:username$", "/@bob")


def test_a_healthy_route_is_untouched():
    for ok in ("/videos/:id", "/explore", "/", "", "/a/:b/c/:d"):
        assert _fix(ok) == ok, ok


def test_every_route_emitter_applies_it():
    """One fact, four emitters. The projector writes App.jsx and the dispatcher writes the
    advice a lane follows by hand; a route repaired in one and not the other drifts."""
    app = _render_routed_app([("ProfileOwnPage", "/@:username"),
                              ("VideosPage", "/videos/:id")])
    assert '<Route path="/:username"' in app, app
    assert '<Route path="/@:username"' not in app, app
    assert '<Route path="/videos/:id"' in app, app

    src = (_AGENT / "env_generator" / "llm_generator" / "multi_agent" / "runtime"
           / "remediation_dispatcher.py").read_text(encoding="utf-8")
    assert src.count('route = _matchable_route_1202iy(') == 3, src.count(
        'route = pg.get("route")')
    assert 'route = pg.get("route") or pg.get("path") or "?"' not in src


def test_the_dispatchers_wrapper_is_audible_when_it_cannot_normalise(monkeypatch):
    """A silent fallback would leave the advice quietly wrong — #1201's shape."""
    seen = {}

    import env_generator.llm_generator.multi_agent.runtime.message_format as MF
    monkeypatch.setattr(MF, "warn_once_1201",
                        lambda key, what, exc: seen.update(key=key))
    monkeypatch.setattr(
        RD, "_matchable_route_1202iy", RD._matchable_route_1202iy)  # keep the real one
    import env_generator.llm_generator.multi_agent.runtime.frontend_scaffold as FS
    monkeypatch.delattr(FS, "_router_matchable_route_1202iy")

    assert RD._matchable_route_1202iy("/@:username") == "/@:username"
    assert seen.get("key") == "remediation_dispatcher.matchable_route_1202iy", seen
