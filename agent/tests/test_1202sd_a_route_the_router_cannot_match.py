r"""#1202sd: the unmatchable route, wherever the LANE wrote it.

`#1202iy` established the rule and the rewrite. `@remix-run/router`'s compilePath takes a param
only via `.replace(/\/:([\w-]+)(\?)?/g, ...)`, so the `:` must directly follow a `/`. In
`/@:username` it follows `@`: no param is extracted, the path compiles to the literal
`^/@:username`, and it matches that exact URL and nothing else. React Router warns about a
mid-segment `*` and is silent about this one.

`#1202iy` applied the rewrite where the FRAMEWORK emits routes, and stopped there. The lane
writes App.jsx. Every run from r119 -- the day after that repair -- through r130 ships
`/@:username` anyway: 11 out of 11, and 50 runs across the corpus carry 52 such paths.

What that costs was reported by an unprimed judge asked only to profile the platform's most
prolific creator on a running r122:

  /@zachking, /@charlidamelio and even the sidebar's own "Profile" link all end up at / with
  the feed. The route IS declared in the bundle, but React Router cannot match a dynamic param
  prefixed by a literal inside one path segment, so it falls through to <Route path="*">. This
  is the single biggest blocker: it makes points 1 and 3 of the task nearly unanswerable.

The rewrite moves the literal INTO the param, so no URL changes: `/@bob` still routes and the
param carries `@bob`. Nothing that matched before stops matching -- these paths matched only
their own literal spelling, which nobody navigates to.
"""
import pytest

from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    repair_frontend_unmatchable_routes_1202sd as repair)


def _fe(tmp_path, app_jsx, extra=None):
    src = tmp_path / "src"
    src.mkdir(parents=True, exist_ok=True)
    (src / "App.jsx").write_text(app_jsx)
    for name, text in (extra or {}).items():
        (src / name).write_text(text)
    return tmp_path


def _routes(tmp_path):
    return (tmp_path / "src" / "App.jsx").read_text()


# --- it repairs -----------------------------------------------------------------------

def test_the_r122_route_is_rewritten(tmp_path):
    fe = _fe(tmp_path, '<Route path="/@:username" element={<ProfileOwnPage/>}/>')
    assert repair(fe)["routes"] == 1
    assert 'path="/:username"' in _routes(tmp_path)


@pytest.mark.parametrize("path,fixed", [
    ("/@:username", "/:username"),
    ("/@:handle", "/:handle"),
    ("/@:username/*", "/:username/*"),
])
def test_every_corpus_spelling(tmp_path, path, fixed):
    fe = _fe(tmp_path, '<Route path="%s" element={<P/>}/>' % path)
    repair(fe)
    assert 'path="%s"' % fixed in _routes(tmp_path)


def test_it_repairs_routes_declared_outside_app_jsx(tmp_path):
    """The lane splits its router across files; #1202iy's emitter only ever saw its own."""
    fe = _fe(tmp_path, "<div/>", {"Router.jsx": '<Route path="/@:username" element={<P/>}/>'})
    assert repair(fe)["routes"] == 1
    assert 'path="/:username"' in (tmp_path / "src" / "Router.jsx").read_text()


def test_running_it_twice_changes_nothing(tmp_path):
    fe = _fe(tmp_path, '<Route path="/@:username" element={<P/>}/>')
    repair(fe)
    once = _routes(tmp_path)
    assert repair(fe)["routes"] == 0
    assert _routes(tmp_path) == once


# --- and what it must not touch -------------------------------------------------------

def test_a_route_carrying_a_query_string_is_left_alone(tmp_path):
    """r79 ships `/?comments=1&video=:id`. That is unmatchable for a DIFFERENT reason, and
    #1202iy's rewrite is actively harmful on it: it becomes `/:id`, a top-level dynamic route
    that then shadows /explore, /login and every other static path. Left loudly unfixed.
    """
    fe = _fe(tmp_path, '<Route path="/?comments=1&video=:id" element={<C/>}/>\n'
                       '<Route path="/explore" element={<E/>}/>')
    assert repair(fe)["routes"] == 0
    assert 'path="/?comments=1&video=:id"' in _routes(tmp_path)
    assert 'path="/:id"' not in _routes(tmp_path)


@pytest.mark.parametrize("path", ["/", "/explore", "/video/:id", "/users/:id/posts/:pid", "*"])
def test_a_matchable_route_is_untouched(tmp_path, path):
    fe = _fe(tmp_path, '<Route path="%s" element={<P/>}/>' % path)
    assert repair(fe)["routes"] == 0
    assert 'path="%s"' % path in _routes(tmp_path)


def test_a_file_with_no_routes_is_not_rewritten(tmp_path):
    fe = _fe(tmp_path, "export default function App(){ return <div/> }")
    before = _routes(tmp_path)
    assert repair(fe)["routes"] == 0
    assert _routes(tmp_path) == before


def test_no_frontend_at_all_is_a_no_op(tmp_path):
    assert repair(tmp_path / "nope")["routes"] == 0
    assert isinstance(repair(tmp_path)["repaired"], list)


def test_the_element_and_the_rest_of_the_line_survive(tmp_path):
    fe = _fe(tmp_path,
             '<Route path="/@:username" element={<ProfileOwnPage/>} errorElement={<E/>}/>')
    repair(fe)
    out = _routes(tmp_path)
    assert "element={<ProfileOwnPage/>}" in out and "errorElement={<E/>}" in out


# --- the writing discipline and the wiring --------------------------------------------

def test_it_writes_through_the_framework_choke_point():
    """#1202cw: every framework write goes through _fw_write_1202cw, or the guard that stops
    the framework from erasing the lane's work does not see it."""
    import inspect

    from env_generator.llm_generator.multi_agent.runtime import frontend_scaffold

    src = inspect.getsource(frontend_scaffold.repair_frontend_unmatchable_routes_1202sd)
    assert "_fw_write_1202cw(" in src
    assert ".write_text(" not in src


def test_the_heal_pipeline_calls_it():
    import inspect

    from env_generator.llm_generator.multi_agent.runtime import heal_pipeline

    src = inspect.getsource(heal_pipeline)
    assert "repair_frontend_unmatchable_routes_1202sd(fe)" in src


def test_it_runs_before_the_other_frontend_repairs():
    """It must land before the build that would otherwise ship the dead route."""
    import inspect

    from env_generator.llm_generator.multi_agent.runtime import heal_pipeline

    src = inspect.getsource(heal_pipeline)
    assert (src.index("repair_frontend_unmatchable_routes_1202sd(fe)")
            < src.index("repair_frontend_escaped_backticks(fe)"))
