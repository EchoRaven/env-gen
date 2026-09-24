"""#266 — an anonymous-rejection probe must not be sent WITH a valid token.

r57 (opus-4.7) got 11 of 12 chains green — up from 8 of 28 in r55/r56 — and aborted on the
last one, ``auth_required_endpoints_reject_anon``:

    POST /api/videos/videos-d1-4/like     -> 201  (expected [401, 403])
    POST /api/videos/videos-d1-4/save     -> 201  (expected [401, 403])
    POST /api/videos/videos-d1-4/comments -> 201  (expected [401, 403])

The app was RIGHT: get_current_user raises 401 without a bearer token, and those handlers
all declare it. The requests simply were not anonymous. ``normalize_steps`` auto-attaches
``auth="token"`` to every ``/api/`` step, and #91 only strips it back off when the
expectation is EXACTLY ``{401}`` — this chain wrote ``[401, 403]``, the natural way to say
"must be rejected" when an app may answer either. So the probe went out authenticated,
succeeded, and could never pass no matter what any lane did.

Widened to: 401 present, no success code, and the auth var is the chain's own canonical
``token``. A cross-user isolation probe carries a DIFFERENT actor's token (``tokenB``) and
keeps it — stripping that would still satisfy the assertion via 401 but would stop proving
isolation, which is the one thing that probe exists for.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from env_generator.llm_generator.multi_agent.runtime.chain_executor import (  # noqa: E402
    normalize_steps,
)


def _auth_of(steps, path):
    for s in steps:
        if str(s.get("path")) == path:
            return s.get("auth")
    return "<missing>"


def _chain(expect, auth=None, path="/api/videos/${vid}/like"):
    step = {"method": "POST", "path": path, "expect": expect}
    if auth:
        step["auth"] = auth
    return [{"method": "POST", "path": "/auth/register",
             "save": {"token": "access_token"}, "expect": [200, 201]},
            {"method": "GET", "path": "/api/feed/for-you",
             "save": {"vid": "items.0.id"}, "expect": [200]},
            step]


def test_r57_regression_401_403_probe_goes_out_tokenless():
    out, _ = normalize_steps(_chain([401, 403]))
    assert _auth_of(out, "/api/videos/${vid}/like") in (None, "<missing>")


def test_the_existing_401_only_case_still_works():
    out, _ = normalize_steps(_chain([401]))
    assert _auth_of(out, "/api/videos/${vid}/like") in (None, "<missing>")


def test_401_404_probe_also_goes_tokenless():
    out, _ = normalize_steps(_chain([401, 404]))
    assert _auth_of(out, "/api/videos/${vid}/like") in (None, "<missing>")


def test_cross_user_probe_with_an_intruder_token_keeps_it():
    """403-with-someone-else's-token is the isolation probe — it must stay authenticated.
    A real isolation chain registers the second actor, so tokenB is genuinely saved (an
    auth var no step saves is repointed at the canonical token, by long-standing design)."""
    steps = _chain([401, 403], auth="tokenB")
    steps.insert(1, {"method": "POST", "path": "/auth/register",
                     "save": {"tokenB": "access_token"}, "expect": [200, 201]})
    out, _ = normalize_steps(steps)
    assert _auth_of(out, "/api/videos/${vid}/like") == "tokenB"


def test_pure_403_cross_user_probe_is_untouched():
    out, _ = normalize_steps(_chain([403]))
    assert _auth_of(out, "/api/videos/${vid}/like") == "token"


def test_a_success_expectation_keeps_its_token():
    """Any 2xx in the set means it is not a rejection probe at all."""
    for expect in ([200], [200, 401], [201, 403]):
        out, _ = normalize_steps(_chain(expect))
        assert _auth_of(out, "/api/videos/${vid}/like") == "token", expect


def test_normal_api_steps_still_get_the_auto_bearer():
    out, _ = normalize_steps(_chain([200]))
    assert _auth_of(out, "/api/feed/for-you") == "token"


def test_no_expectation_at_all_keeps_the_token():
    steps = _chain([200])
    steps[-1].pop("expect")
    out, _ = normalize_steps(steps)
    assert _auth_of(out, "/api/videos/${vid}/like") == "token"
