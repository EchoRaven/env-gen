"""#1202kq: #1202ix diagnosed half the cases, because it was written for one symptom.

`/@:username` cannot carry a param — React Router extracts one only when the `:` directly
follows a `/`, so the whole path compiles to a literal regex. #1202ix says so, and fires from
the `not shot` / blank branch: nothing routed, so nothing rendered.

The identical defect has a second, quieter symptom. The capture navigates to the literal path
(`/@:username` itself), which the literal regex matches trivially, so a component DOES mount —
with the param never extracted. The page has no id to fetch, renders its shell, and waits
forever. Silent console, `empty_state: True`, and a low score that reads as a styling gap.

tiktok-r117, from its persisted verdict:

    profile_own   route=/@:username   empty_state=True   console_errors=[]   similarity=0.10
    deviations[0] = "main content: implementation shows only 'Profile Own' and 'Loading...',
                     while the reference shows the full profile header, tabs, sort control..."

A content complaint for a routing defect. #1202ix logged nothing all run, correctly — the
screen was never blank.

Measured over the persisted verdicts: 13 screens sit on an unmatchable-shaped route, 6 blank
(diagnosed) and 7 NOT blank (undiagnosed). The existing check covers about half.

WHAT IS VERIFIED: the rendered-case sentence fires exactly when the route cannot carry a param
AND the judge reported an empty state; it is appended to the judge's own deviations; it names
the route rather than the page; and a well-formed route produces nothing.

WHAT IS NOT: that an unmatchable route always breaks the page. tiktok-r111 scored 0.74 on one.
This is a HYPOTHESIS handed to the lane in the text it already reads, and it changes no score,
no pass/fail and no blocking set — exactly the bargain #1202ix made.
"""
import sys
import pathlib

_AGENT = pathlib.Path(__file__).resolve().parents[1]
_LLM = _AGENT / "env_generator" / "llm_generator"
for _p in (str(_LLM), str(_AGENT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import ast          # noqa: E402
import inspect      # noqa: E402
import textwrap     # noqa: E402

from multi_agent.runtime.visual_fidelity import (            # noqa: E402
    _unmatchable_route_1202ix,
    _unmatchable_route_rendered_1202kq,
)


def test_r117s_route_is_diagnosed():
    """★ The case."""
    out = _unmatchable_route_rendered_1202kq("/@:username")
    assert out
    assert "/@:username" in out
    assert "literal" in out.lower()


def test_it_blames_the_route_not_the_page():
    """★ The whole point: the judge already said the content is wrong. The new sentence must
    add the CAUSE, or it is noise on top of a complaint the lane cannot act on."""
    out = _unmatchable_route_rendered_1202kq("/@:username").lower()
    assert "fix the route" in out
    assert "symptom" in out


def test_a_well_formed_route_says_nothing():
    """★ The floor."""
    for ok in ("/profile/:username", "/", "/explore", "/videos/:id/comments"):
        assert _unmatchable_route_rendered_1202kq(ok) == "", ok


def test_it_agrees_with_1202ix_about_WHICH_routes_are_broken():
    """One fact, one detector: the rendered variant must never disagree with the blank one
    about whether a path can carry a param — two derivations is how #1202ga happened."""
    for r in ("/@:username", "/user-:id", "/profile/:username", "/x/:y", "/@:a/b", ""):
        assert bool(_unmatchable_route_rendered_1202kq(r)) == bool(_unmatchable_route_1202ix(r)), r


def test_the_blank_wording_is_not_reused_for_a_rendered_page():
    """★ #1202ix says 'Nothing rendered because nothing was routed' — false here, and a false
    sentence sends the lane looking for a component that does exist."""
    rendered = _unmatchable_route_rendered_1202kq("/@:username")
    assert "Nothing rendered" not in rendered
    assert "DID mount" in rendered


def test_it_is_applied_to_the_judged_screen_record():
    """★ Reachability: the helper is inert unless the judged record appends it. Read from the
    parse tree, and require the empty_state guard — a low score alone is not this defect."""
    from multi_agent.runtime import visual_fidelity as VF
    src = textwrap.dedent(inspect.getsource(VF.run_visual_fidelity))
    tree = ast.parse(src)
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id == "_unmatchable_route_rendered_1202kq"]
    assert calls, "the rendered-case diagnosis is never applied"
    # the guard that decides whether to append must mention empty_state
    for node in ast.walk(tree):
        if isinstance(node, ast.IfExp) and "_unmatchable_route_rendered_1202kq" in ast.unparse(node):
            assert "empty_state" in ast.unparse(node.test), ast.unparse(node.test)[:160]
            return
    raise AssertionError("no guarded append found")


def test_it_never_touches_the_score_or_the_verdict():
    """★ Scope, and the reason this is safe to ship on a hypothesis: it writes prose only."""
    from multi_agent.runtime import visual_fidelity as VF
    src = textwrap.dedent(inspect.getsource(VF.run_visual_fidelity))
    # #943: structural, not a byte window. Find the dict literal that carries the call and
    # assert the call appears ONLY under the "deviations" key — so it cannot reach the score.
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.Dict):
            continue
        for k, v in zip(node.keys, node.values):
            if not (isinstance(k, ast.Constant) and isinstance(k.value, str)):
                continue
            if "_unmatchable_route_rendered_1202kq" not in ast.unparse(v):
                continue
            assert k.value == "deviations", (
                f"the diagnosis leaked into the {k.value!r} field — it must only ever "
                "append prose")
            return
    raise AssertionError("the call is not inside a screen-record dict at all")
