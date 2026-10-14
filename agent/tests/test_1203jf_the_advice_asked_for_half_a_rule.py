r"""#1203jf: the session-restore advice asked for half a rule, and the other half blocks.

`test_user_runner`'s `hollow_frontend` advice said "restore auth on load via the canonical
/api/auth/me" with no condition. A frontend that follows it literally probes a protected
endpoint on every page load; the API answers 401 — correctly, `backend_scaffold`
deliberately keeps `/api/auth/me` guarded — and the verifier then records the page as a
failed ui_flow for the resulting console/network error.

★ THAT IS THE TOP FINAL-GATE BLOCKER'S COMMONEST NAMEABLE CAUSE.
`validation_ui_evidence_failed` holds the final gate in 13 of the 63 modern runs with a
ledger, ahead of `business_chain_failing` (11) and `deliverability_guard_tampering` (7).
15 of its failure records across 7 runs say only this, r135/r136/r150/r170/r181 in the
current era. tiktok-web-r170's TERMINAL blocker was
`ui_evidence_failed_pages=['login_page','signup_page']` and both records say nothing else:

    login_page   "flow failed: /api/auth/me produced a 401 console/network error during
                  the flow."
    signup_page  "/api/auth/me returned 401 during logged-out signup flow."

r181 failed four pages the same way, one named `fyp_feed_logged_out`, where an anonymous
401 is the only possible answer. Every record says the page RENDERED.

★★ BOTH HALVES MATTER, because the framework punishes both reflexes. #1202qn flags the
opposite one — tiktok-r127's `if(!getToken())return fallbackVideos` before
`request('/api/videos/feed')`, where "a logged-out visitor never reached the API, so no
request failed and no console error was ever logged; only the invented feed showed". A lane
told only "don't call it anonymously" lands there instead. So the advice has to name the
ENDPOINT's auth requirement, which is what neither half said.

This module asserts the advice's CONTENT through the AST's literal values, never by
reading the file's text: a prose assertion that greps the source passes on the comment
that explains it, which is how three assertions in this repo came to prove nothing.
"""
import ast
import inspect
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

import multi_agent.runtime.test_user_runner as TUR  # noqa: E402


def _advice():
    """The string the `hollow_frontend` branch appends, as a VALUE.

    Located by the condition it hangs off, so the test follows the advice if it moves, and
    reddens if it detaches from `hollow_frontend` — the advice is only correct for that
    diagnosis.
    """
    tree = ast.parse(inspect.getsource(TUR))
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        if "hollow_frontend" not in ast.dump(node.test):
            continue
        out = []
        for sub in ast.walk(node):
            if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                out.append(sub.value)
        if out:
            return " ".join(out)
    raise AssertionError("the hollow_frontend advice is gone or no longer in its own branch")


def test_the_probe_is_conditional_on_a_token():
    """★ THE TICKET. The advice may not ask for an unconditional session probe."""
    a = _advice().lower()
    assert "/api/auth/me" in a, "the canonical session endpoint is no longer named: %r" % a[:200]
    assert "only when a token" in a, (
        "the advice still asks for an unconditional probe, which answers 401 on every "
        "public page: %r" % a[:400])


def test_it_also_forbids_gating_a_public_endpoint():
    """WITHOUT THIS THE FIX TRADES ONE DEFECT FOR THE OTHER: #1202qn's case is a lane that
    gated its PUBLIC feed on a token, so a logged-out visitor saw invented data."""
    a = _advice().lower()
    assert "public endpoint" in a and "token" in a, (
        "the converse is not stated, so a lane can satisfy this advice by gating "
        "everything: %r" % a[:400])
    assert "1202qn" in a, "the converse is stated without pointing at the ticket that owns it"


def test_the_rule_is_stated_as_the_endpoints_auth():
    """Both halves follow from one rule, and saying the rule is what makes the advice
    actionable rather than two prohibitions to balance."""
    a = _advice().lower()
    assert "endpoint" in a and "auth" in a, a[:300]
    assert "not whether a token happens to exist" in a, (
        "the advice lists two prohibitions but never names the rule behind them: %r"
        % a[:400])


def test_the_original_advice_survives():
    """The sentence exists for `hollow_frontend` — an app that logged in but renders the
    login form on protected pages. Its original diagnosis (an absolute/wrong origin
    bypassing the proxy) must not be lost to the addition."""
    a = _advice().lower()
    # ★ "relative" alone is NOT a pin: the same branch separately says "a same-origin
    # RELATIVE path", so deleting the IMPERATIVE ("use relative '/api', '/auth' URLs")
    # left this test green until the mutation exposed it. Each fragment here has to be
    # unique to the instruction it stands for.
    for frag in ("hollow frontend", "use relative", "'/auth'",
                 "canonical /api/auth/me", "blocks delivery"):
        assert frag in a, "the original advice lost %r: %r" % (frag, a[:400])


def test_the_advice_is_reachable_from_the_report_formatter():
    """A fact that reaches no recipient is this project's commonest defect, so the branch
    must still be inside the function that builds what the lane reads."""
    tree = ast.parse(inspect.getsource(TUR))
    owners = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for sub in ast.walk(fn):
            if isinstance(sub, ast.If) and "hollow_frontend" in ast.dump(sub.test):
                owners.append(fn.name)
                break
    assert owners, "the advice is no longer inside any function"
    # it must be a formatter the lane reads, i.e. it appends to a lines/report list
    fn = [f for f in ast.walk(tree)
          if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)) and f.name == owners[0]][0]
    appends = [n for n in ast.walk(fn) if isinstance(n, ast.Call)
               and getattr(n.func, "attr", "") == "append"]
    assert appends, "%s no longer appends anything — the advice reaches nobody" % owners[0]
