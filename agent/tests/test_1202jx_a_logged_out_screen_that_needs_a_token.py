"""#1202jx: a screen declared reachable logged out whose page calls an auth-required endpoint.

Such a screen can never render. The capture arrives without a token, the projected handler
answers 401, and the page shows its error or empty state — so the lane reads "the logged-out
feed is blank" and goes looking at a frontend where nothing is wrong.

Measured over 35 recent runs (googlemaps-r16 excluded, #1202jw): 32 of 98 screens declared
`requires_auth: False` depend on at least one auth-required endpoint. The names say it
outright — tiktok's `fyp_feed_logged_out` at `/` calling `GET /api/videos`, netflix's
`landing` at `/` calling `GET /api/titles`.

Diagnosed on 2026-09-07 and left unimplemented; this is that fix. It reports BOTH repairs and
picks neither: either the endpoint should be public or the screen should not be marked
logged-out, and only the contract's author knows which. Flipping `auth_required` here would
open an endpoint on a guess.

THE SIGNAL IS DECLARED, NOT SNIFFED. `requires_auth` is the design system's own field and the
auth flag arrives through #1202hi's single reader. My first pass guessed instead — I treated
`/browse` as a logged-out surface, which made netflix's login-walled browse page a finding.
"""
import sys
import pathlib

_AGENT = pathlib.Path(__file__).resolve().parents[1]
if str(_AGENT) not in sys.path:
    sys.path.insert(0, str(_AGENT))

import ast                                                             # noqa: E402
import inspect                                                        # noqa: E402

from env_generator.llm_generator.multi_agent.runtime import contract_drift as CD  # noqa: E402

_F = CD.logged_out_screens_needing_auth_1202jx


def _eps(*specs):
    return {f"e{i}": {"method": m, "path": p, "schema": {"auth_required": a}}
            for i, (m, p, a) in enumerate(specs)}


def _pages(*specs):
    return {f"p{i}": {"name": n, "route": r, "apis_used": list(u)}
            for i, (n, r, u) in enumerate(specs)}


def test_the_logged_out_feed_that_needs_a_token(tmp_path):
    """★ tiktok's shape, by name."""
    out = _F([{"name": "fyp_feed_logged_out", "route": "/", "requires_auth": False}],
             _pages(("feed_page", "/", ["GET /api/videos"])),
             _eps(("GET", "/api/videos", True)))
    assert len(out) == 1
    assert out[0]["screen"] == "fyp_feed_logged_out"
    assert out[0]["auth_endpoints"] == ["GET /api/videos"]


def test_a_public_endpoint_is_no_finding():
    out = _F([{"name": "fyp_feed_logged_out", "route": "/", "requires_auth": False}],
             _pages(("feed_page", "/", ["GET /api/videos"])),
             _eps(("GET", "/api/videos", False)))
    assert out == []


def test_an_authenticated_screen_is_no_finding():
    """★ The mistake the first pass made: a login-walled page is SUPPOSED to need a token."""
    out = _F([{"name": "browse_home", "route": "/browse", "requires_auth": True}],
             _pages(("browse_page", "/browse", ["GET /api/titles"])),
             _eps(("GET", "/api/titles", True)))
    assert out == []


def test_a_screen_with_no_declaration_is_no_finding():
    """`requires_auth` absent means nobody declared it — not that it is public (#1039)."""
    out = _F([{"name": "landing", "route": "/"}],
             _pages(("landing_page", "/", ["GET /api/titles"])),
             _eps(("GET", "/api/titles", True)))
    assert out == []


def test_an_endpoint_with_no_stated_auth_is_no_finding():
    out = _F([{"name": "landing", "route": "/", "requires_auth": False}],
             _pages(("landing_page", "/", ["GET /api/titles"])),
             {"e0": {"method": "GET", "path": "/api/titles"}})
    assert out == []


def test_it_reads_auth_through_the_one_reader():
    """One fact, one emitter: a fourth reading of the flag would drift from #1202hi."""
    src = inspect.getsource(CD._stated_auth_1202jx)
    assert "_stated_auth_1202hi" in src
    body = inspect.getsource(_F)
    assert "metadata" not in body and "schema" not in body, (
        "the precedence belongs to #1202hi's reader, not to a copy here")


def test_it_names_both_repairs_and_picks_neither():
    """Reporting a contradiction without a verdict is the point — flipping `auth_required`
    here would open an endpoint on a guess."""
    from env_generator.llm_generator.multi_agent import orchestrator as ORCH
    tree = ast.parse(inspect.getsource(ORCH))
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and getattr(n.func, "id", None) == "logged_out_screens_needing_auth_1202jx"]
    assert len(calls) == 1, f"expected one call site, found {len(calls)}"
    text = " ".join(c.value for c in ast.walk(tree)
                    if isinstance(c, ast.Constant) and isinstance(c.value, str)
                    and "LOGGED-OUT SCREEN NEEDS AUTH" in c.value
                    or (isinstance(c, ast.Constant) and isinstance(c.value, str)
                        and "make those" in c.value))
    assert "make those" in text and "stop declaring" in text, (
        "both repairs must be named; the author picks")
