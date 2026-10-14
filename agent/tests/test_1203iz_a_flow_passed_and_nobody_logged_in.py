r"""#1203iz: a ui_flow can pass on navigation alone, and one did in the corpus's best run.

`ok` is `bool(token) or moved`. #1126b left that `or` deliberately untouched — "this only
withdraws a claim of success that the landing contradicts" — so a flow that merely navigated
somewhere plausible passes. tiktok-web-r177, the run with the best delivery in the corpus
(4 of 4 milestones, every closing gate green, open P0 = 0), has three records of exactly that:

    signup  auth_requests=0  auth_status=[]  token_stored=false  url=http://localhost:8053/
    login   auth_requests=0  auth_status=[]  token_stored=false  url=http://localhost:8053/

Zero auth requests, no token, and the destination is the site root — which shows no login
affordance, so #1126b's landing check sees nothing wrong and the zero-request fact is never
consulted. #1203gp counted four `auth_requests == 0` cases but only inside the branch where
the landing check had ALREADY withdrawn `ok`.

Over the 522 ui_flow records: 252 passed, 26 with no token, and 22 of those 26 show no auth
request either — but 19 of the 26 predate #1203a6 and carry no `auth_requests` field, so what
is PROVEN today is three records in one run.

RECORDED, NOT ACTED ON. An app that logs in through a path outside the watched surface and
sets an httpOnly cookie looks identical from here, and withdrawing `ok` would turn its success
into a false failure. The flag makes the class countable in the next runs instead of
invisible — what #1203ix did for the rounds, for the verdict's other direction.
"""
import ast
import inspect

import pytest

from env_generator.llm_generator.multi_agent.runtime import test_user_validation as tuv

SRC = inspect.getsource(tuv)


def _flow():
    for n in ast.walk(ast.parse(SRC)):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "_ui_auth_flow":
            return n
    raise AssertionError("_ui_auth_flow is gone")


def _flag_expr():
    """The flag's expression, as written in the record."""
    for node in ast.walk(_flow()):
        if not isinstance(node, ast.Dict):
            continue
        for k, v in zip(node.keys, node.values):
            if isinstance(k, ast.Constant) and k.value == "passed_without_auth_1203iz":
                return ast.unparse(v)
    raise AssertionError("the flag is not in any record")


# --- it means what it says ------------------------------------------------------------------

def test_the_flag_is_recorded():
    assert _flag_expr()


@pytest.mark.parametrize("name", ["ok", "token", "_auth_resps", "_auth_reqs", "_auth_failed"])
def test_the_flag_reads_every_signal_it_needs(name):
    """Dropping any one of these would flag a flow that did log somebody in."""
    assert name in _flag_expr(), (name, _flag_expr())


def _eval(**env):
    base = {"ok": True, "token": None, "_auth_resps": [], "_auth_reqs": [], "_auth_failed": []}
    base.update(env)
    return bool(eval(_flag_expr(), {"bool": bool}, base))


def test_r177s_shape_is_flagged():
    """Passed, no token, nothing on the auth surface — the record this ticket is about."""
    assert _eval() is True


def test_a_cookie_login_is_not_flagged():
    """★ THE SAFETY PROPERTY. An httpOnly-cookie login stores no token and still issues the
    request; flagging it would be the false failure this ticket refuses to create."""
    assert _eval(_auth_resps=[200]) is False
    assert _eval(_auth_reqs=["http://x/auth/login"]) is False


def test_a_request_that_never_answered_is_not_flagged():
    """#1203a6's case: the stack was unreachable, which says nothing about the form."""
    assert _eval(_auth_failed=["http://x/auth/login (ERR_CONNECTION_REFUSED)"]) is False


def test_a_token_login_is_not_flagged():
    assert _eval(token="abc") is False


def test_a_failing_flow_is_not_flagged():
    """The flag is about PASSES. A failure already has a note explaining itself."""
    assert _eval(ok=False) is False


# --- and it changes nothing -------------------------------------------------------------------

def test_the_verdict_is_untouched():
    """#1126b's `or` is deliberate; this ticket does not re-open it.

    Asserted over the AST. The first version matched the text `"ok = bool(token) or moved"`
    in the module source and a mutation to `and` SURVIVED it — because #1203gp's comment and
    this ticket's own comment both quote that line, so the words were still there while the
    code said something else. Third time this session that an assertion read its author's
    prose; the shape that does not is to ask the tree.
    """
    found = []
    for node in ast.walk(_flow()):
        if (isinstance(node, ast.Assign)
                and any(getattr(t, "id", "") == "ok" for t in node.targets)
                and isinstance(node.value, ast.BoolOp)):
            found.append(node.value)
    assert found, "no boolean assignment to `ok` — the verdict moved"
    assert any(isinstance(b.op, ast.Or) for b in found), \
        [ast.unparse(b) for b in found]
    joined = " ".join(ast.unparse(b) for b in found)
    assert "token" in joined and "moved" in joined, joined


def test_nothing_assigns_ok_from_the_flag():
    for node in ast.walk(_flow()):
        if (isinstance(node, ast.Assign)
                and any(getattr(t, "id", "") == "ok" for t in node.targets)):
            assert "1203iz" not in ast.unparse(node.value), ast.unparse(node.value)


def test_the_note_does_not_read_the_flag():
    for node in ast.walk(_flow()):
        if (isinstance(node, ast.Assign)
                and any(getattr(t, "id", "") == "_note" for t in node.targets)):
            assert "1203iz" not in ast.unparse(node.value), ast.unparse(node.value)


# --- provenance ---------------------------------------------------------------------------------

def test_the_run_it_was_found_in_is_named():
    flat = " ".join(SRC.replace("#", " ").split())
    assert "tiktok-web-r177" in flat


def test_the_census_and_its_caveat_are_recorded():
    """19 of the 26 predate the field — the honest denominator is 3, not 22."""
    flat = " ".join(SRC.replace("#", " ").split())
    assert "252 passed" in flat
    assert "19 of" in flat and "predate" in flat


def test_why_it_is_not_acted_on_is_recorded():
    flat = " ".join(SRC.replace("#", " ").split())
    assert "RECORDED, NOT ACTED ON" in flat
    assert "httpOnly cookie" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
