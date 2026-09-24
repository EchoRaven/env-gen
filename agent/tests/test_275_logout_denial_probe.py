"""#275 — an anonymous logout is legitimately a no-op; a denial probe on it must accept 2xx.

r60 (opus-4.7, v4 prompts), live: the unauth_guard chain asserted, alongside the real
protected endpoints, ``POST /api/auth/logout`` anon expect=[401, 403]. The app answered 200,
and the chain failed. But an anonymous logout returning 200 is CORRECT — logout is an
idempotent auth-control-surface action ("end whatever session you have"), and real apps
answer it 200 / 204 (a no-op) just as often as 401. The framework's own
resolve_endpoint_auth (#271) already classifies /auth/logout as anonymous-accessible, so the
app and the framework agree; only the verifier's probe is too strict, and no lane can make a
correct logout start rejecting anonymous callers.

Same family as #266 (a denial probe that cannot be satisfied on a correct app), and just as
env-agnostic — every app's logout hits it. The fix widens the probe rather than dropping it:
for an idempotent auth-control endpoint (logout / signout / sign-out), a denial expectation
is relaxed to ALSO accept success codes, so the step passes whether the app 401s OR treats
anonymous logout as a no-op. Coverage is kept; the false failure is removed. Real protected
endpoints (feed, me, like) are untouched — they are not the control surface.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from env_generator.llm_generator.multi_agent.runtime.chain_executor import (  # noqa: E402
    normalize_steps,
)


def _expect_of(steps, path):
    for s in steps:
        if str(s.get("path")) == path:
            e = s.get("expect")
            return set(int(x) for x in (e if isinstance(e, (list, tuple, set)) else [e])
                       if str(x).isdigit())
    return None


def _chain(path, expect):
    return [{"method": "POST", "path": "/auth/register", "save": {"token": "access_token"},
             "expect": [200, 201]},
            {"method": "POST", "path": path, "expect": expect}]


def test_r60_regression_logout_denial_probe_accepts_2xx():
    out, _ = normalize_steps(_chain("/api/auth/logout", [401, 403]))
    exp = _expect_of(out, "/api/auth/logout")
    assert exp & {200, 201, 204}, f"anon logout may be a 200 no-op; got {exp}"
    assert 401 in exp or 403 in exp, "must still accept the reject answer too"


def test_signout_and_sign_out_variants():
    for path in ("/api/auth/signout", "/api/auth/sign-out", "/auth/logout"):
        out, _ = normalize_steps(_chain(path, [401, 403]))
        assert _expect_of(out, path) & {200, 201, 204}, path


def test_a_real_protected_endpoint_probe_is_untouched():
    """A denial probe on a genuine protected endpoint must still require rejection only."""
    out, _ = normalize_steps(_chain("/api/feed/for-you", [401, 403]))
    exp = _expect_of(out, "/api/feed/for-you")
    assert not (exp & {200, 201, 204}), f"feed anon must be rejected, not widened; got {exp}"


def test_login_is_not_widened():
    """login already legitimately 200s and is not a denial probe — leave it alone.
    (The framework normalizes /api/auth/login -> /auth/login, so look it up by either.)"""
    out, _ = normalize_steps(_chain("/api/auth/login", [200]))
    exp = _expect_of(out, "/api/auth/login") or _expect_of(out, "/auth/login")
    assert exp == {200}, exp


def test_logout_with_a_success_expectation_is_left_as_is():
    """A chain that already expects logout to succeed needs no widening."""
    out, _ = normalize_steps(_chain("/api/auth/logout", [200, 204]))
    exp = _expect_of(out, "/api/auth/logout")
    assert 200 in exp and 401 not in exp


def test_delete_method_logout_also_handled():
    steps = [{"method": "POST", "path": "/auth/register", "save": {"token": "access_token"},
              "expect": [200, 201]},
             {"method": "DELETE", "path": "/api/auth/logout", "expect": [401, 403]}]
    out, _ = normalize_steps(steps)
    assert _expect_of(out, "/api/auth/logout") & {200, 201, 204}
