"""FIX #289 — cross-user denial probe on a PUBLIC idempotent social action can never pass (r74 live).

#275 widened idempotent control-surface denial probes to accept 2xx, but only for logout. #266
leaves CROSS-USER probes alone for PRIVATE resources. A like/save/follow/share is PUBLIC (#288)
and idempotent — a cross-user "isolation" probe on it is a category error. r74 died on
`tenant_isolation_like`: POST /api/videos/{vid}/like (auth=tokenA) expect=[404]; app returned 201
(correct, post-#288) → business_chain_failing → api_smoke unrecorded → NO-CONVERGENCE ABORT with
the whole frontend already green. Verified: normalize_steps leaves that expect at [404].

Fix: widen a denial probe (expect has 403/404, no 2xx) whose path ends in a WHITELISTED public
social verb to also accept 2xx. Whitelist — not any action suffix — so /transfer /promote
/delete keep cross-user isolation. ENV-AGNOSTIC + LOCAL-ONLY.
"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
from multi_agent.runtime.chain_executor import normalize_steps  # noqa: E402

_REG = {"method": "POST", "path": "/auth/register",
        "body": {"email": "a@e.com", "password": "x"}, "save": {"tokenA": "access_token"}}

def _expect_after(step):
    out, _ = normalize_steps([_REG, step])
    e = out[-1].get("expect")
    return set(e if isinstance(e, (list, tuple, set)) else ([e] if e is not None else []))

def test_cross_user_like_denial_widened_to_accept_2xx():
    st = {"method": "POST", "path": "/api/videos/${vid}/like", "auth": "tokenA", "expect": [404]}
    assert _expect_after(st) & {200, 201, 204}

def test_all_public_social_verbs_widened():
    for verb in ("like", "unlike", "save", "unsave", "follow", "unfollow",
                 "share", "repost", "bookmark", "subscribe", "favorite"):
        st = {"method": "POST", "path": "/api/videos/${vid}/" + verb, "auth": "tokenA", "expect": [403, 404]}
        assert _expect_after(st) & {200, 201, 204}, verb + " not widened"

def test_sensitive_actions_keep_cross_user_isolation():
    for verb in ("transfer", "promote", "approve", "delete", "ban", "deactivate"):
        st = {"method": "POST", "path": "/api/accounts/${otherId}/" + verb, "auth": "tokenA", "expect": [403, 404]}
        assert not (_expect_after(st) & {200, 201, 204}), verb + " wrongly widened"

def test_positive_like_step_unchanged():
    st = {"method": "POST", "path": "/api/videos/${vid}/like", "auth": "token", "expect": [200, 201]}
    ex = _expect_after(st)
    assert 200 in ex and 201 in ex

def test_social_verb_must_be_the_path_tail():
    st = {"method": "POST", "path": "/api/liked_items/${otherId}/transfer", "auth": "tokenA", "expect": [403, 404]}
    assert not (_expect_after(st) & {200, 201, 204})
