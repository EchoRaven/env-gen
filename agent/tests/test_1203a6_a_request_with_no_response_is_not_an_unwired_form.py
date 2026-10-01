r"""#1203a6: "submit sent NO /auth request" also fired when the request HAD been sent.

The auth-flow probe recorded only RESPONSES (`page.on("response")`). `_auth_resps` is empty in
two situations that mean opposite things:

  * the submit never fired a request  -> the form really is unwired
  * the submit fired one that got no response -> connection refused while the stack was
    restarting, DNS, a refused CORS preflight; the form is wired and the app was down

Both reached `elif not _auth_resps`, so the note accused the form either way: "the form is not
wired to the API (button has no handler / submit does nothing)".

WHAT IT COSTS. r142's `SignupPage.jsx` is 60 lines with a real `<form onSubmit>` whose handler
does `fetch('/auth/register', {method:'POST', ...})` — and the run's test-user report said its
submit "does nothing". A lane told that adds an api call to a page that already has one.

MEASURED over the 656 test_user_reports in the corpus: this note is the dominant verdict by far
— 378 occurrences, against 13 for "wired but 4xx" and 37 for "no token" — and NOT ONE of the
378 can be audited, because the flow record kept `{flow, ok, token_stored, navigated,
auth_status, note}` and neither the URL nor whether a request was attempted. Playwright exposes
both through `page.on("request")` / `page.on("requestfailed")`; nothing was asking.

★ NO MASKING. The failure is still a failure and `ok` is unchanged — what changes is which of
the two causes the note names, and that the record now carries the grounds for it. The
"genuinely unwired" branch still exists and still fires when no request was seen.

★ I HAD TO CORRECT MYSELF TWICE GETTING HERE. First I read r142's two messages — signup "not
wired" beside login "ERR_CONNECTION_REFUSED" — as one unreachable page misdiagnosed. They are
separate loop iterations: /signup's `goto` SUCCEEDED and /login's failed, seconds apart. Then I
assumed the signup page was a stub; it has a real form and a real fetch. The artifacts cannot
say why no response was seen, and that inability IS the defect being fixed here.
"""
import ast
import inspect
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

import multi_agent.runtime.test_user_validation as TUV  # noqa: E402

_SRC = inspect.getsource(TUV)


def _note_branches():
    """The `if/elif` chain that assigns `_note`, as AST — located by the landmark string each
    branch assigns, never by a byte window (#943)."""
    tree = ast.parse(_SRC)
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        dump = ast.dump(node)
        if "not wired to the API" in dump and "no token was stored" in dump:
            return node
    raise AssertionError("the _note branch chain is gone")


def _branch_tests():
    """Every `test` expression in that chain, outermost first, unparsed."""
    out, node = [], _note_branches()
    while isinstance(node, ast.If):
        out.append(ast.unparse(node.test))
        node = node.orelse[0] if (len(node.orelse) == 1
                                  and isinstance(node.orelse[0], ast.If)) else None
    return out


def test_the_unwired_branch_still_exists():
    """★ Non-vacuity: the check this fix narrows must still be able to fire."""
    assert "not wired to the API" in _SRC


def test_a_request_with_no_response_is_judged_before_unwired():
    """★ The ordering IS the fix. If the new branch came after `not _auth_resps`, it would be
    unreachable and the note would be unchanged."""
    tests = _branch_tests()
    idx_new = [i for i, t in enumerate(tests) if "_auth_reqs" in t or "_auth_failed" in t]
    idx_old = [i for i, t in enumerate(tests)
               if "not _auth_resps" in t and "_auth_reqs" not in t and "_auth_failed" not in t]
    assert idx_new and idx_old, tests
    assert min(idx_new) < min(idx_old), (
        "the request-aware branch sits AFTER the unwired branch, so it never runs: %s" % tests)


def _eval_branch(expr, **env):
    """Evaluate one branch condition with controlled locals — BEHAVIOUR, not position."""
    base = {"_auth_resps": [], "_auth_reqs": [], "_auth_failed": [], "ok": False}
    base.update(env)
    return bool(eval(expr, {}, base))


def test_the_request_aware_branch_is_actually_reachable():
    """★ FOUND BY MUTATION. The ordering test below checks POSITION, and prefixing the branch
    with `False and` left it in place, dead, with every test still green. Position is not
    reachability: evaluate the condition and require it to fire on the case it exists for."""
    tests = _branch_tests()
    new = [t for t in tests if "_auth_reqs" in t or "_auth_failed" in t][0]
    assert _eval_branch(new, _auth_reqs=["http://x/auth/register"]) is True, new
    assert _eval_branch(new, _auth_failed=["http://x/auth/register (refused)"]) is True, new


def test_the_unwired_branch_still_fires_when_nothing_was_sent():
    """The other direction, also behavioural: a genuinely dead form must still be named."""
    tests = _branch_tests()
    new = [t for t in tests if "_auth_reqs" in t or "_auth_failed" in t][0]
    old = [t for t in tests
           if "not _auth_resps" in t and "_auth_reqs" not in t and "_auth_failed" not in t][0]
    assert _eval_branch(new) is False, "the request-aware branch swallows the unwired case"
    assert _eval_branch(old) is True, old


def test_the_unwired_branch_still_requires_no_request_seen():
    """The narrowed branch must only claim "unwired" when no request was observed — otherwise
    the new branch is decoration."""
    tests = _branch_tests()
    new = [t for t in tests if "_auth_reqs" in t or "_auth_failed" in t][0]
    assert "not _auth_resps" in new, new
    assert "_auth_reqs" in new and "_auth_failed" in new, new


def test_requests_and_failures_are_actually_recorded():
    """Listeners for both, registered on the page — a branch reading a list nobody fills is
    the shape this project keeps finding."""
    assert 'page.on("request"' in _SRC
    assert 'page.on("requestfailed"' in _SRC
    assert "_auth_reqs.append" in _SRC
    assert "_auth_failed.append" in _SRC


def test_the_listeners_filter_to_auth_urls():
    """Recording every request would make the branch fire on any page with any traffic."""
    tree = ast.parse(_SRC)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in (
                "_on_req_1203a6", "_on_reqfail_1203a6"):
            # ast.unparse normalises quotes, so match the TEXT, not a quoted spelling.
            assert "/auth/" in ast.unparse(node), node.name
    names = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert {"_on_req_1203a6", "_on_reqfail_1203a6"} <= names, sorted(names)


def test_the_flow_record_carries_the_grounds():
    """★ The second half: 378 unauditable verdicts become auditable. The record must name the
    URL and whether a request was attempted."""
    tree = ast.parse(_SRC)
    keys = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            ks = [k.value for k in node.keys
                  if isinstance(k, ast.Constant) and isinstance(k.value, str)]
            if "flow" in ks and "note" in ks:
                keys |= set(ks)
    for needed in ("url", "auth_requests", "auth_failed", "auth_status"):
        assert needed in keys, "%s missing from the flow record: %s" % (needed, sorted(keys))


def test_the_new_note_tells_the_lane_not_to_add_a_call():
    """The measured cost of the old note was a lane adding an api call to a page that had one.
    Saying only "the backend was down" would leave the same wrong next step available."""
    # #943, third time today: a fixed window here matched the COMMENT above the branch
    # instead of the string the lane actually reads. Collect the literal via AST.
    note = ""
    for n in ast.walk(ast.parse(_SRC)):
        if (isinstance(n, ast.Constant) and isinstance(n.value, str)
                and "the form IS wired \u2014 it sent" in n.value):
            note = n.value
            break
    # the note is built by implicit concatenation, so take the whole JoinedStr/BinOp text too
    if "unreachable" not in note:
        for n in ast.walk(ast.parse(_SRC)):
            if isinstance(n, ast.Assign) and any(
                    getattr(t, "id", "") == "_note" for t in n.targets):
                txt = ast.unparse(n)
                if "the form IS wired" in txt:
                    note = txt
                    break
    assert note, "the request-aware note is gone"
    assert "unreachable" in note, note[:300]
    assert "do not add an api call" in note, note[:300]


def test_the_verdict_itself_is_unchanged():
    """No masking: this touches the NOTE, not `ok`. A flow that failed still fails."""
    node = _note_branches()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Assign):
            for t in sub.targets:
                assert getattr(t, "id", "") != "ok", (
                    "the note chain now assigns `ok` — a diagnosis must not flip the verdict")
