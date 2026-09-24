"""#301 (widened by #316) — a /oauth/authorize chain step that lacks the PKCE
``code_challenge`` 4xx's on a working AS and must be tolerated, else business_chain
wedges (r82 M2 STUCK 75min; r86 final NO-CONVERGENCE ABORT 75min).

The verifier/framework authors both a bare GET /oauth/authorize probe AND a correct
params-bearing PKCE flow. Any authorize request WITHOUT ``code_challenge`` correctly
422/400s on a PKCE-enforced AS and can never pass. #316 corrected the discriminator
from "no flow params at all" (which let a params-bearing-but-no-challenge step slip
through as not-tolerated → r86 wedge) to "no code_challenge". Same family as #281
(oauth Form) / #289 (denial probe) / #299 (self-follow). See also test_316.
"""
import sys
from pathlib import Path
THIS = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS.parent / "env_generator" / "llm_generator"))
from multi_agent.runtime.chain_executor import _oauth_authorize_lacks_pkce  # noqa: E402


def test_bare_get_authorize_lacks_pkce():
    assert _oauth_authorize_lacks_pkce("/oauth/authorize", None) is True


def test_authorize_with_code_challenge_is_real_flow():
    # carries code_challenge → the real PKCE flow → must pass, NOT tolerated
    assert _oauth_authorize_lacks_pkce(
        "/oauth/authorize?response_type=code&client_id=x&code_challenge=abc", None) is False


def test_params_bearing_without_code_challenge_is_tolerated():
    # #316: client_id/response_type present but NO code_challenge → still cannot PKCE
    # → tolerated (this exact shape wedged r86 under #301's old "any flow param" rule).
    assert _oauth_authorize_lacks_pkce(
        "/oauth/authorize", {"client_id": "x", "response_type": "code"}) is True


def test_non_authorize_path_not_tolerated():
    assert _oauth_authorize_lacks_pkce("/api/videos", None) is False
    assert _oauth_authorize_lacks_pkce("/oauth/token", {"grant_type": "authorization_code"}) is False


def test_trailing_slash_and_query_only_other_params():
    # a query that lacks code_challenge is still tolerated
    assert _oauth_authorize_lacks_pkce("/oauth/authorize?foo=1", None) is True
