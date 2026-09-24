"""Guard: business_chain auth-token variable always resolves.

Surfaced by the youtube run: the verifier authored an /auth/register step that
saved the token under a CUSTOM var ({"commenter_token": "access_token"}), while
other steps referenced auth="token" — which was never saved → empty bearer →
GET /api/videos/{id}/comments → 401 → business_chain failed forever (run stalled
in a 36x validation churn). normalize_steps must (a) always also save the
canonical "token", and (b) repoint any /api/ step whose auth var is never saved.
Domain-agnostic.
"""
from env_generator.llm_generator.multi_agent.runtime.chain_executor import normalize_steps


def _saved(steps):
    return {v for s in steps for v in (s.get("save") or {})}


def test_auth_step_always_saves_canonical_token_even_with_custom_save():
    steps, _ = normalize_steps([
        {"method": "POST", "path": "/auth/register",
         "save": {"commenter_token": "access_token"}, "expect": [200, 201]},
        {"method": "POST", "path": "/api/videos", "auth": "commenter_token", "expect": [200, 201]},
        {"method": "GET", "path": "/api/videos/1/comments", "auth": "token", "expect": [200]},
    ])
    saved = _saved(steps)
    assert "token" in saved, "canonical token must be saved"
    assert "commenter_token" in saved, "custom save must be preserved"
    # every auth reference resolves to a saved var (no empty bearer → no 401)
    for s in steps:
        if s.get("auth"):
            assert s["auth"] in saved, f"unresolved auth {s['auth']!r} on {s['path']}"


def test_api_step_with_unsaved_auth_var_is_repointed_to_token():
    steps, _ = normalize_steps([
        {"method": "POST", "path": "/auth/login", "expect": [200, 201]},
        {"method": "GET", "path": "/api/videos/1", "auth": "ghost_var", "expect": [200]},
    ])
    saved = _saved(steps)
    assert "token" in saved
    get_step = [s for s in steps if s["method"] == "GET"][0]
    assert get_step["auth"] == "token", "unsaved auth var must be repointed to canonical token"


def test_unset_api_auth_defaults_to_token_and_resolves():
    steps, _ = normalize_steps([
        {"method": "POST", "path": "/auth/register", "expect": [200, 201]},
        {"method": "GET", "path": "/api/videos/1", "expect": [200]},  # no auth → default
    ])
    saved = _saved(steps)
    get_step = [s for s in steps if s["method"] == "GET"][0]
    assert get_step["auth"] == "token" and "token" in saved
