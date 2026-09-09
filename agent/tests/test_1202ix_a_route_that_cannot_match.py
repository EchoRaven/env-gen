"""#1202ix: a React Router path whose param does not own a whole segment can never match.

`@remix-run/router`'s compilePath extracts a param with `.replace(/\\/:([\\w-]+)(\\?)?/g, ...)`
-- the `:` must directly follow a `/`. In `/@:username` it follows `@`, so no param is
extracted and the whole path compiles to the literal regex `^/@:username`: it matches that
exact URL and nothing else. Verified against react-router 6.30.3's own source. React Router
warns about a `*` in mid-segment and says NOTHING about this one.

The screen then renders a bare `<div id=root>` with an empty console. #1202da reasons from
that silence that "a component rendered nothing" and sends the lane to find it -- and when no
route matched there is no component to find. That is the one explanation the silence equally
allows and the only one that is decidable from the path alone.

Corpus: 37 such routes across 36 runs, essentially every tiktok run's `/@:username` for
`profile_own`. The visual gate passes only once EVERY blocking screen has cleared the bar at
least once (#129 sticky pass), so one permanently-blank screen makes the gate unpassable for
the whole milestone: r110 scored 7 of 9 over the bar and still could not pass.
"""
import sys
import pathlib
import re

_AGENT = pathlib.Path(__file__).resolve().parents[1]
if str(_AGENT) not in sys.path:
    sys.path.insert(0, str(_AGENT))

from env_generator.llm_generator.multi_agent.runtime.visual_fidelity import (  # noqa: E402
    _unmatchable_route_1202ix)

_VF = (_AGENT / "env_generator" / "llm_generator" / "multi_agent" / "runtime"
       / "visual_fidelity.py")


def test_the_real_corpus_shape_is_caught():
    for dead in ("/@:username", "/@:handle", "/user-:id/posts", "/v1/x:y"):
        assert _unmatchable_route_1202ix(dead), dead


def test_a_normal_route_is_left_alone():
    """A false positive here tells a lane its working route is broken, which is worse than
    the silence being replaced."""
    for ok in ("/videos/:id", "/explore", "/", "", "/a/:b/c/:d", "/users/:id/posts/:pid"):
        assert _unmatchable_route_1202ix(ok) == "", ok


def test_the_explanation_names_the_route_and_a_concrete_replacement():
    out = _unmatchable_route_1202ix("/@:username")
    assert "/@:username" in out
    assert "/@/:username" in out, out           # the param owning a whole segment
    assert "no component to look at" in out, out


def test_it_matches_react_routers_own_rule():
    """The predicate must agree with compilePath, not with a guess about it. Applying
    react-router's actual param regex to the path decides it: a path the regex finds no param
    in, but which contains a `:`, is a literal -- exactly what the helper must flag."""
    rr_param = re.compile(r"/:([\w-]+)(\?)?")
    for path in ("/@:username", "/videos/:id", "/explore", "/user-:id/posts",
                 "/a/:b/c/:d", "/users/:id/posts/:pid"):
        params_found = len(rr_param.findall(path))
        colons = path.count(":")
        rr_says_dead = colons > params_found
        assert bool(_unmatchable_route_1202ix(path)) == rr_says_dead, (
            path, colons, params_found)


def test_the_blank_branch_consults_it_before_blaming_the_page():
    """Reachability, not presence: the helper must be called from the blank-screen branch and
    #1202da's "look for a component" text must be skipped when the route routed nowhere --
    otherwise the lane still gets the advice that sent it hunting in r110."""
    src = _VF.read_text(encoding="utf-8")
    i = src.index("rendered BLANK — navigated + reached ")
    j = src.index("elif screen[\"name\"] in _auth_bounced:", i)
    branch = src[i:j]
    assert "_unmatchable_route_1202ix(screen.get(\"route\"))" in branch, branch[:400]
    assert "elif not _why1202ix:" in branch, branch[:400]
    # and the #1202da advice really is the thing being guarded
    k = branch.index("elif not _why1202ix:")
    assert "Look for a component that returns null/empty" in branch[k:]
