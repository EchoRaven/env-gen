"""GET /<anything>/me is a CURRENT-USER SINGLETON, never a collection.

outlook run #2: GET /api/auth/me projected a ``{"items":[],"total":0}`` LIST handler
and failed business_endpoints_correct_shape forever ("returns a list but the contract
is a single item"), blocking api_smoke across all 6 attempts. Root cause: the /me
branch was gated on the path's resource segment resolving to a model — and "auth" has
no table, so cls=None → it fell to the generic GET stub which defaults to a list when
response_key != "item". /me is ALWAYS the authenticated caller's own record, so it must
resolve to the users model regardless of the resource segment.

LOCAL-ONLY (agent/tests/ gitignored).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.route_projector import _generate_handler, _me_user_model  # noqa: E402


def _m(cls, cols, fks=None):
    return {"cls": cls, "cols": cols, "fks": fks or {}}


_MODELS = {
    "users": _m("User", ["id", "email", "name", "password_hash"]),
    "messages": _m("Message", ["id", "user_id", "subject", "body"], {"user_id": "users"}),
}


def test_auth_me_is_single_item_not_list_even_without_auth_model():
    # "auth" has no table — the bug was this falling through to the list stub.
    src = _generate_handler("GET", "/api/auth/me", auth=True, models=_MODELS, idx=1, response_key="")
    assert 'return {"item":' in src, src
    assert '"items"' not in src, src                 # NOT a collection envelope
    assert "db.get(User, _fw_owner_val(User, 'id', user))" in src, src       # resolves to the current user
    assert "password_hash" not in src, src           # secrets never serialised


def test_auth_me_single_even_when_response_key_blank_or_items():
    # the contract's response_key must not be able to force a list shape onto /me
    for rk in ("", "items", "item"):
        src = _generate_handler("GET", "/api/auth/me", auth=True, models=_MODELS, idx=2, response_key=rk)
        assert 'return {"item":' in src and '"items"' not in src, (rk, src)


def test_users_me_still_single_item_backcompat():
    # the previously-working cls-resolved case (/api/users/me) stays single
    src = _generate_handler("GET", "/api/users/me", auth=True, models=_MODELS, idx=3, response_key="item")
    assert 'return {"item":' in src and '"items"' not in src, src


def test_put_me_resolves_user_model_dynamically_not_hardcoded_User():
    # An app whose user table is "accounts" (class Account) has NO `User` symbol — a
    # hardcoded db.get(User, ...) NameErrors at request time. PUT/PATCH /me must resolve
    # the user model dynamically, mirroring GET /me.
    models = {"accounts": _m("Account", ["id", "email", "name"])}
    for method in ("PUT", "PATCH"):
        src = _generate_handler(method, "/api/accounts/me", auth=True, models=models, idx=1, response_key="item")
        assert "db.get(Account, _fw_owner_val(Account, 'id', user))" in src, src
        assert "db.get(User," not in src, src


def test_param_get_stub_resolver_reads_real_model_keys():
    # GET /api/business_discovery/{username}: "business_discovery" has no table, but the
    # users model has a `username` column → resolve through it. The resolver previously
    # read non-existent dict keys (columns/class_name) so it was dead and always 404'd.
    models = {"users": _m("User", ["id", "username", "name"])}
    src = _generate_handler("GET", "/api/business_discovery/{username}", auth=False,
                            models=models, idx=2, response_key="item")
    assert "User.username == username" in src, src
    assert 'return {"item":' in src, src


def test_me_user_model_resolves_users_table():
    assert _me_user_model(_MODELS)[0] == "User"
    # user-like fallback (email/username) when no conventionally-named users table
    alt = {"members": _m("Member", ["id", "email", "handle"])}
    assert _me_user_model(alt)[0] == "Member"
    # nothing user-like → None (handler then emits an empty {item}, still single)
    assert _me_user_model({"widgets": _m("Widget", ["id", "color"])}) is None


def test_plain_collection_get_unaffected():
    # a normal non-/me GET stays a list
    src = _generate_handler("GET", "/api/messages", auth=True, models=_MODELS, idx=4, response_key="items")
    assert '"items"' in src, src


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
