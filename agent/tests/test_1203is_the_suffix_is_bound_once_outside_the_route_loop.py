r"""#1203is: the ui_flow probe's credential suffix is bound ONCE, before the route loop.

`_ui_auth_flow` drives `/signup` and then `/login` through one `_fill_visible_inputs`, and
`sfx = str(int(time.time()))[-6:]` is what makes the two flows agree: the signup creates
`uiflow<sfx>` and the login types the same string back. Moving that line inside the loop is
the obvious tidy-up — nothing before the loop uses it — and it would hand the two routes
suffixes seconds apart, so every login would fail as "login user not registered". That is a
verdict this corpus really contains (19 of its 270 failed ui_flows), so the failure mode is
not hypothetical; only its cause would be.

The same invariant is what makes an UNDER-SPECIFIC field classification harmless. The
placeholder chain reads `placeholder` and `type` and NOT `name`, while the sibling
`test_user_runner._fill_visible_inputs` reads name too. Projected over the 1967 inputs on
auth pages in this corpus, 267 (13.6%) are classified GENERIC where their `name` says
otherwise — 154 full-name, 50 email, 32 password, 31 username — and every one of the 267 is
GENERIC -> a specific role, never one role -> another. An under-specific value still logs in,
because BOTH flows produce it. Two causal hypotheses for the commonest ui_flow failure were
tested and both failed (see the note at the assignment), so nothing was changed; this file
pins the accident of placement that the safety rests on.
"""
import ast
import inspect

import pytest

from env_generator.llm_generator.multi_agent.runtime import test_user_validation as tuv

SRC = inspect.getsource(tuv)


def _fn():
    """The probe function, by name — no byte windows (#943)."""
    tree = ast.parse(SRC)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "_ui_auth_flow":
            return node
    raise AssertionError("_ui_auth_flow is gone — this ticket's subject moved")


def _sfx_assignments(scope):
    out = []
    for node in ast.walk(scope):
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == "sfx":
                    out.append(node)
    return out


def _route_loops(scope):
    """The loop that walks ('/signup', …), ('/login', …)."""
    out = []
    for node in ast.walk(scope):
        if isinstance(node, (ast.For, ast.AsyncFor)):
            consts = {c.value for c in ast.walk(node.iter)
                      if isinstance(c, ast.Constant) and isinstance(c.value, str)}
            if "/signup" in consts and "/login" in consts:
                out.append(node)
    return out


def test_the_probe_still_drives_both_routes_in_one_loop():
    """The positive control: the rest of this file means nothing if the loop is gone."""
    loops = _route_loops(_fn())
    assert len(loops) == 1, "expected exactly one signup+login loop, got %d" % len(loops)


def test_the_suffix_is_assigned_exactly_once():
    """Two assignments would mean two suffixes, whatever their positions."""
    assert len(_sfx_assignments(_fn())) == 1


def test_the_suffix_is_not_assigned_inside_the_route_loop():
    """The whole invariant: one suffix shared by signup and login."""
    loop = _route_loops(_fn())[0]
    inside = {id(n) for n in _sfx_assignments(loop)}
    assert not inside, "sfx is bound inside the route loop — signup and login would disagree"


def test_the_suffix_is_bound_before_the_loop_runs():
    fn = _fn()
    assert _sfx_assignments(fn)[0].lineno < _route_loops(fn)[0].lineno


def test_both_routes_share_one_filler():
    """Two fillers could drift the same way two suffixes would."""
    fn = _fn()
    fillers = [n for n in ast.walk(fn)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
               and n.name == "_fill_visible_inputs"]
    assert len(fillers) == 1


def _filler():
    return [n for n in ast.walk(_fn())
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            and n.name == "_fill_visible_inputs"][0]


def test_the_suffix_is_what_the_filler_types():
    """If the filler stopped using `sfx`, pinning the assignment would guard nothing."""
    names = {n.id for n in ast.walk(_filler()) if isinstance(n, ast.Name)}
    assert "sfx" in names, sorted(names)[:12]


def test_the_identity_the_account_is_created_under_carries_the_suffix():
    """The EMAIL branch specifically — that string IS the account.

    A first version of this file asserted only that `sfx` appeared SOMEWHERE in the filler,
    and a mutation that hardcoded this one call site survived it: the other two fills still
    named `sfx`. Hardcoding it means every run registers the same address, so the second run
    onward collides with the account the first one made.
    """
    email_fills = []
    for node in ast.walk(_filler()):
        if not isinstance(node, ast.If):
            continue
        if "email" not in ast.dump(node.test):
            continue
        for call in ast.walk(ast.Module(body=node.body, type_ignores=[])):
            if (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                    and call.func.attr == "fill" and call.args):
                email_fills.append(call.args[0])
    assert email_fills, "no fill() found under a branch testing for an email field"
    for arg in email_fills:
        assert isinstance(arg, ast.JoinedStr), ast.dump(arg)
        assert "sfx" in {n.id for n in ast.walk(arg) if isinstance(n, ast.Name)}, ast.dump(arg)


# --- provenance -------------------------------------------------------------------------------

def test_the_consequence_of_moving_it_is_recorded():
    flat = " ".join(SRC.replace("#", " ").split())
    assert "login user not registered" in flat
    assert "19 of its 270" in flat


def test_the_projection_and_the_two_failed_hypotheses_are_recorded():
    """A reader must see that the under-specific reading was MEASURED and left alone."""
    flat = " ".join(SRC.replace("#", " ").split())
    assert "267 (13.6%)" in flat
    assert "BOTH FAILED" in flat
    assert "EMPTY (n=0)" in flat


def test_the_direction_of_the_misreading_is_recorded():
    """GENERIC -> a role, never role -> role: that is why it is under-specific, not wrong."""
    flat = " ".join(SRC.replace("#", " ").split())
    assert "never one role -> another" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
