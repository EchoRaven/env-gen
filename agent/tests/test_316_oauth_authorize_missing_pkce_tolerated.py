"""#316 — a /oauth/authorize business_chain step that omits the PKCE
``code_challenge`` correctly 400/422s on a PKCE-enforced AS and can NEVER pass,
so its 4xx must be tolerated — whether the step is fully BARE (#301) or
PARAMS-BEARING-but-no-challenge (#316).

r86 M-final NO-CONVERGENCE ABORT (75min, business_chain_failing): a framework-
synthesized default chain hit
  GET /oauth/authorize?response_type=code&client_id=mcp_...&redirect_uri=...&state=xyz
which correctly 400s ``{"detail":"code_challenge with S256 is required"}``. #301's
``_is_bare_oauth_authorize`` treated it as NOT-bare (it carries client_id/
response_type) → not tolerated → business_chain never went green → the whole run
aborted even though every real (code_challenge-bearing) PKCE flow passed. Same
"framework-synthesized probe wedges the gate" family as #281/#289/#299/#301.

The correct discriminator is the PRESENCE OF ``code_challenge``: a step WITHOUT it
can't complete PKCE (tolerate its 4xx); a step WITH it is the real flow and MUST
pass (a 4xx there is a genuine bug — never tolerated).
"""
import sys
from pathlib import Path

THIS = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS.parent / "env_generator" / "llm_generator"))
from multi_agent.runtime.chain_executor import _oauth_authorize_lacks_pkce  # noqa: E402


def test_r86_params_bearing_authorize_without_challenge_is_tolerated():
    # the exact r86 step: has response_type/client_id/redirect_uri/state, NO code_challenge
    path = ("/oauth/authorize?response_type=code&client_id=mcp_VnAYyJuKiemL9oVwqIcd6A"
            "&redirect_uri=http://localhost:9999/callback&state=xyz")
    assert _oauth_authorize_lacks_pkce(path, None) is True


def test_fully_bare_authorize_still_tolerated():
    # #301 case must still hold
    assert _oauth_authorize_lacks_pkce("/oauth/authorize", None) is True
    assert _oauth_authorize_lacks_pkce("/oauth/authorize?foo=1", None) is True


def test_authorize_with_code_challenge_is_the_real_flow_not_tolerated():
    # a step carrying code_challenge is the real PKCE flow; it must PASS, so a 4xx
    # there is a genuine bug and must NOT be swallowed.
    assert _oauth_authorize_lacks_pkce(
        "/oauth/authorize?response_type=code&client_id=x&code_challenge=abc123&code_challenge_method=S256",
        None) is False
    # code_challenge in the body counts too
    assert _oauth_authorize_lacks_pkce(
        "/oauth/authorize", {"client_id": "x", "response_type": "code", "code_challenge": "abc"}) is False


def test_non_authorize_paths_never_tolerated():
    assert _oauth_authorize_lacks_pkce("/api/videos", None) is False
    assert _oauth_authorize_lacks_pkce("/oauth/token", {"grant_type": "authorization_code"}) is False
