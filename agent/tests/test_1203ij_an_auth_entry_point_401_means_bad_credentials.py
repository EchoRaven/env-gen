"""#1203ij — the framework told the agent to hunt enforcement on an endpoint that enforces nothing.

`test_api`'s hint branch keys on "401/403 with no Authorization header" and cannot tell apart
the two things a 401 can mean:

  (a) this endpoint is protected and you sent no token;
  (b) this endpoint VERIFIES credentials and the ones you sent are wrong.

For an auth ENTRY point the answer is always (b) — it needs no token, so it can never reject
one for being absent. Proven on the framework's own generated stack rather than inferred:

  * the enforcement middleware only guards paths starting `/api/` and explicitly exempts the
    `/api/auth/<login|register|signup|signin|token|refresh|logout>` terminals, so a bare
    `POST /auth/login` never reaches it;
  * the handler is `async def auth_login(request: Request)` — no auth dependency;
  * its only 401 is `if not user: {"detail": "invalid credentials"}`.

So the old message sent the agent to "Find why auth is enforced: a stale image (re-run
validation to rebuild)" about an endpoint where nothing is enforced — an expensive rebuild for
a problem that does not exist — while the real next step (register the user first, then log in
with those credentials) went unsaid. 102 times across four runs: r182 57, r183 23, r184 6,
r185 16.

#1202qp's own case stays intact: tiktok-r127's `GET /api/videos/feed` registered public and
answering 401 is case (a), and a feed is not an auth entry point.
"""
import os
import pathlib
import sys

import pytest

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _AGENT)

from env_generator.llm_generator.tools.runtime_tools import (  # noqa: E402
    _AUTH_ENTRY_TERMINALS_1203ij as TERMINALS,
    _is_auth_entry_endpoint_1203ij as is_entry,
)


@pytest.mark.parametrize("url,expected", [
    # the call this exists for — no `/api/` prefix at all
    ("http://localhost:8058/auth/login", "/auth/login"),
    ("http://localhost:8058/api/auth/login", "/api/auth/login"),
    # r25's synonym: #235 records that a literal whitelist walled it for 108 minutes
    ("http://localhost:8058/api/auth/signup", "/api/auth/signup"),
    ("http://localhost:8058/oauth/token", "/oauth/token"),
    ("http://localhost:8058/auth/refresh", "/auth/refresh"),
    ("http://localhost:8058/auth/login/", "/auth/login"),      # trailing slash
    ("http://localhost:8058/auth/LOGIN", "/auth/LOGIN"),       # case-insensitive match
])
def test_an_auth_entry_point_is_recognised(url, expected):
    assert is_entry(url) == expected


@pytest.mark.parametrize("url", [
    # ★ #1202qp's real case must stay case (a): a feed is not an auth entry point
    "http://localhost:8058/api/videos/feed",
    "http://localhost:8058/api/auth/me",        # the middleware guards this one too
    "http://localhost:8058/api/videos",
    "http://localhost:8058/api/users/1/logins",  # plural, not the entry segment
    "",
    None,
])
def test_everything_else_is_not(url):
    assert is_entry(url) == ""


def test_the_terminal_list_matches_the_middleware_the_framework_generates():
    """★ #1032: this list is restated from a TEMPLATE STRING in backend_scaffold (#235), which
    cannot be imported. A duplicated literal with no guard fails silently on the day someone
    edits one copy — so pin that the two agree."""
    bs = pathlib.Path(
        _AGENT, "env_generator/llm_generator/multi_agent/runtime/backend_scaffold.py"
    ).read_text(encoding="utf-8")
    assert '"login", "register", "signup", "signin", "token", "refresh",' in bs, (
        "the generated middleware's auth-entry list moved or changed shape; "
        "_AUTH_ENTRY_TERMINALS_1203ij must be re-checked against it")
    for seg in ("login", "register", "signup", "signin", "token", "refresh", "logout"):
        assert seg in TERMINALS, seg


def test_the_hint_branches_on_it_and_spares_1202qp():
    """Pinned over the AST: the auth-entry message must be reachable, must suppress the
    contract-disagreement message for an entry point, and must leave #1202qp's wording for
    everything else. The old code called `_contract_says_public_1202qp` unconditionally."""
    import ast
    src = pathlib.Path(
        _AGENT, "env_generator/llm_generator/tools/runtime_tools.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(src)
    ifs = [n for n in ast.walk(tree) if isinstance(n, ast.If)
           and (ast.get_source_segment(src, n.test) or "").strip() == "_authentry_1203ij"]
    assert ifs, "nothing branches on _authentry_1203ij — the predicate is computed and ignored"
    node = ifs[0]

    def _text(nodes):
        return " ".join(c.value for n in nodes for c in ast.walk(n)
                        if isinstance(c, ast.Constant) and isinstance(c.value, str))

    body, orelse = _text(node.body), _text(node.orelse)
    assert "AUTH ENTRY POINT" in body
    assert "THE CREDENTIALS WERE REJECTED" in body
    assert "Do NOT re-run validation" in body, (
        "the message must say not to chase the rebuild this used to point at")
    # #1202qp's wording survives for the non-entry case
    assert "disagrees with the contract" in orelse, (
        "#1202qp's contract-disagreement message was lost; r127's feed case needs it")
    assert "disagrees with the contract" not in body, (
        "an auth entry point is still being told the app disagrees with the contract")


def test_the_contract_lookup_is_skipped_for_an_auth_entry_point():
    """Not merely a different message: asking `_contract_says_public_1202qp` about an auth
    entry point is the question that produced the wrong answer, so it must not be asked."""
    import ast
    src = pathlib.Path(
        _AGENT, "env_generator/llm_generator/tools/runtime_tools.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(src)
    asn = [n for n in ast.walk(tree) if isinstance(n, ast.Assign)
           and any(isinstance(t, ast.Name) and t.id == "_public_1202qp" for t in n.targets)]
    assert asn, "_public_1202qp is no longer assigned"
    seg = ast.get_source_segment(src, asn[0].value) or ""
    assert "_authentry_1203ij" in seg, (
        "the contract lookup is unconditional again, so an auth entry point can still be "
        "told the served app disagrees with the contract")
