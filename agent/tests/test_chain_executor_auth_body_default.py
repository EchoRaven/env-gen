"""chain_executor: a body-less /auth/register|login step must not 422 forever.

Observed live on the Gemini instagram run (2026-06-13): the verifier registered a
verification chain whose ``/auth/register`` step carried NO body (authored from a
bare endpoint id → ``body=None``). At execution the empty request hit the
framework AS, which returned ``422 {"detail":"email and password are required"}``
→ the business_chain delivery check failed on every retry → the milestone could
never deliver (it was stuck at validation attempt 6/6).

normalize_steps already defaults ``save`` for auth steps; it now also defaults a
framework-authored ``body`` (the auth round-trip is a platform invariant: every
app mints its token from /auth/* with {email,password}). A verifier slip can no
longer permanently 422-block the chain.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from multi_agent.runtime.chain_executor import normalize_steps, _subst, _dig  # noqa: E402


def _reg(step):
    out, errs = normalize_steps([step])
    assert errs == [], errs
    return out[0]


def test_bodyless_register_gets_default_body():
    s = _reg({"endpoint": "POST /auth/register", "method": "POST",
              "path": "/auth/register", "save": {"token": "access_token"}})
    body = s.get("body")
    assert isinstance(body, dict)
    assert body.get("email") and body.get("password")   # the two fields the AS requires
    assert body.get("name")                              # register also accepts a name


def test_bodyless_login_gets_default_body_no_name():
    s = _reg({"method": "POST", "path": "/auth/login"})
    body = s.get("body")
    assert isinstance(body, dict)
    assert body.get("email") and body.get("password")
    assert "name" not in body


def test_existing_body_is_preserved():
    good = {"email": "real@x.io", "password": "secret", "name": "Real"}
    s = _reg({"method": "POST", "path": "/auth/register", "body": dict(good)})
    assert s["body"] == good  # framework must NOT clobber an authored body


def test_empty_dict_body_is_filled():
    # an explicitly-empty body is as broken as a missing one → fill it
    s = _reg({"method": "POST", "path": "/auth/register", "body": {}})
    assert s["body"].get("email") and s["body"].get("password")


def test_default_body_rand_substitutes_to_unique_email():
    s = _reg({"method": "POST", "path": "/auth/register"})
    subbed = _subst(s["body"], {"rand": "1234567"})
    assert subbed["email"] == "chain_1234567@example.com"
    assert "${rand}" not in subbed["email"]


def test_non_auth_step_body_untouched():
    s = _reg({"method": "POST", "path": "/api/posts", "body": {"caption": "hi"}})
    assert s["body"] == {"caption": "hi"}
    s2 = _reg({"method": "GET", "path": "/api/feed"})
    assert not s2.get("body")  # no spurious body injected on non-auth steps


# ── _dig envelope tolerance (2026-06-13) ──────────────────────────────────────

def test_dig_descends_canonical_item_envelope():
    # POST create returns {"item": {...}}; a chain saving "id" must resolve to item.id
    assert _dig({"item": {"id": 42, "caption": "x"}}, "id") == 42
    assert _dig({"item": {"id": 42}}, "caption") is None  # caption not present → None


def test_dig_descends_canonical_items_envelope():
    # list returns {"items": [...]}; "id" resolves to items[0].id
    assert _dig({"items": [{"id": 7}, {"id": 8}], "total": 2}, "id") == 7


def test_dig_flat_response_still_works():
    # a bare/flat response (no envelope) resolves top-level keys unchanged
    assert _dig({"id": 99, "access_token": "tok"}, "id") == 99
    assert _dig({"access_token": "tok"}, "access_token") == "tok"


def test_dig_top_level_wins_over_envelope():
    # if the key IS at the top level, use it (don't spuriously descend)
    assert _dig({"id": 1, "item": {"id": 2}}, "id") == 1


def test_dig_explicit_dotted_path_unaffected():
    assert _dig({"item": {"id": 5}}, "item.id") == 5
    assert _dig({"a": {"b": {"c": 3}}}, "a.b.c") == 3


def test_dig_missing_everywhere_returns_none():
    assert _dig({"item": {"id": 5}}, "nonexistent") is None
    assert _dig({}, "id") is None
    assert _dig(None, "id") is None
