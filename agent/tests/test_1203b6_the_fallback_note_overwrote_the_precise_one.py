r"""#1203b6: the fallback note overwrote the precise one and contradicted the record.

`#1126b` withdraws a login success the landing contradicts — it sets `ok = False` and writes the
one note that names the repair ("landed on '/', which still shows a way to sign in — redirect to
a route that requires auth"). The `if ok: / elif ...` chain below then runs BECAUSE `ok` is now
False, falls through to its final `else`, and replaces that text with "/auth returned [...] but
no token was stored and no navigation".

r144's walk report, verbatim:

    {"flow": "signup", "ok": false, "token_stored": true, "navigated": true,
     "auth_status": [201], "auth_requests": 1, "auth_failed": [],
     "note": "/auth returned [201] but no token was stored and no navigation — response
              shape or post-login handling issue"}

`token_stored` and `navigated` are both TRUE in the record whose note says neither happened. The
verdict is right; the sentence is impossible, and it sends the lane after "response shape /
post-login handling" instead of the redirect.

`browser_ui_unusable` (`auth_ok=False`) held r144's last FOUR green gate windows — attempts 1, 2
and 3 of the bounded escape — so this sentence stood between a fully-green gate and a release.

★ The chain and #1126b both predate #1203a6, but #1203a6 added a branch to this very chain and
did not notice the overwrite — #1202wx's shape ("two formatters, the lane gets the worse one") in
code I had just edited.
"""
import ast
import inspect
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

import multi_agent.runtime.test_user_validation as TUV  # noqa: E402


def _chain():
    """The `if ok: / elif ... / else:` note chain, as an AST node.

    Located by the branch #1203a6 added rather than by line number (#943): that branch's test
    is unique in this module.
    """
    src = inspect.getsource(TUV)
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        # the chain's head is `if ok:` whose body is a single `_note = ""`
        if not (isinstance(node.test, ast.Name) and node.test.id == "ok"):
            continue
        if not (len(node.body) == 1 and isinstance(node.body[0], ast.Assign)
                and getattr(node.body[0].targets[0], "id", "") == "_note"):
            continue
        dumped = ast.dump(node)
        if "_auth_resps" in dumped and "_auth_reqs" in dumped:
            return node
    raise AssertionError("the note chain is gone or no longer recognisable")


def _branch_tests(node):
    """Every branch condition of the chain, in evaluation order (None for the final else)."""
    out = []
    cur = node
    while True:
        out.append(cur.test)
        if len(cur.orelse) == 1 and isinstance(cur.orelse[0], ast.If):
            cur = cur.orelse[0]
            continue
        out.append(None)              # the final `else`
        return out


def _first_true(env):
    """Index of the first branch whose condition holds under `env` — the branch that runs."""
    tests = _branch_tests(_chain())
    for i, t in enumerate(tests):
        if t is None:
            return i
        if eval(compile(ast.Expression(t), "<t>", "eval"), {}, dict(env)):
            return i
    raise AssertionError("unreachable")


_R144 = {
    # the signup flow exactly as r144 recorded it, plus #1126b's note already set
    "ok": False,
    "_note": ("login SUCCEEDED (token=True) but landed on '/', which still shows a way to "
              "sign in — the user is back on the signed-out page. (#1126b)"),
    "_auth_resps": [201],
    "_auth_reqs": ["http://localhost:8021/auth/register"],
    "_auth_failed": [],
}


def test_the_precise_note_wins_on_r144s_own_record():
    """★ The whole ticket, decided by evaluating the real conditions rather than reading
    positions: with #1126b's note set, branch 1 (`elif _note`) runs, not the final `else`."""
    i = _first_true(_R144)
    assert i == 1, "branch %d runs, so the fallback still overwrites #1126b" % i


def test_the_guard_branch_does_nothing():
    """It must KEEP the note, not write a new one — a branch that assigned would be the same
    defect with different words."""
    node = _chain()
    guard = node.orelse[0]
    assert isinstance(guard, ast.If)
    assert all(isinstance(st, (ast.Pass, ast.Expr)) for st in guard.body), \
        "the guard branch assigns something: %s" % ast.dump(guard)[:160]
    assert not any(isinstance(st, ast.Assign) for st in guard.body)


def test_a_verdict_with_no_explanation_still_gets_the_fallback():
    """★ The chain keeps its job. Same record, but nothing above explained it — the 201/else
    branch must still fire, or #1203b6 would have silenced a real diagnosis."""
    env = dict(_R144, _note="")
    i = _first_true(env)
    tests = _branch_tests(_chain())
    assert i == len(tests) - 1, "branch %d runs, expected the final else" % i


def test_the_unreachable_backend_branch_is_unaffected():
    """#1203a6's own case: requests issued, no response, and no note from above."""
    env = {"ok": False, "_note": "", "_auth_resps": [],
           "_auth_reqs": ["x"], "_auth_failed": ["x (ERR_CONNECTION_REFUSED)"]}
    assert _first_true(env) == 2, "the #1203a6 branch moved"


def test_the_unwired_branch_is_unaffected():
    env = {"ok": False, "_note": "", "_auth_resps": [], "_auth_reqs": [], "_auth_failed": []}
    assert _first_true(env) == 3


def test_a_passing_flow_still_clears_the_note():
    """`ok` wins over everything, including a note left by #1126b's probe."""
    assert _first_true(dict(_R144, ok=True)) == 0


def test_the_note_is_initialised_once_per_flow():
    """★ WITHOUT THIS THE GUARD IS A BUG: `_note` is only assigned by #1126b before the chain,
    so on the NEXT flow in the loop it would still hold the previous flow's text and `elif
    _note` would attach `login`'s explanation to `signup`. Pinned structurally: the init sits
    in the same block as the verdict it explains, and before the #1126b probe."""
    src = inspect.getsource(TUV)
    tree = ast.parse(src)
    verdicts = [n for n in ast.walk(tree) if isinstance(n, ast.Assign)
                and getattr(n.targets[0], "id", "") == "ok"
                and isinstance(n.value, ast.BoolOp)]
    assert verdicts, "`ok = bool(token) or moved` is gone"
    v = verdicts[0]
    inits = [n for n in ast.walk(tree) if isinstance(n, ast.Assign)
             and getattr(n.targets[0], "id", "") == "_note"
             and isinstance(n.value, ast.Constant) and n.value.value == ""
             and v.lineno < n.lineno < v.lineno + 8]
    assert inits, "no `_note = \"\"` within 8 lines after the verdict — a stale note can leak"


def test_the_1126b_note_is_still_written_before_the_chain():
    """The guard is worthless if the thing it protects stopped being produced."""
    src = inspect.getsource(TUV)
    assert "#1126b" in src
    tree = ast.parse(src)
    chain_line = _chain().lineno
    writes = [n for n in ast.walk(tree) if isinstance(n, ast.Assign)
              and getattr(n.targets[0], "id", "") == "_note"
              and n.lineno < chain_line
              and isinstance(n.value, (ast.JoinedStr, ast.BinOp, ast.Call, ast.Constant))]
    assert any(n.lineno < chain_line and not (isinstance(n.value, ast.Constant)
               and n.value.value == "") for n in writes), \
        "nothing writes a note before the chain any more"
