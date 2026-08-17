"""Gen-1: a resource-less GET /api/search resolves to the content table (no empty stub).

`_primary_content_model` requires a timestamp column; a catalog (netflix `titles`) has
none, so a bare /api/search fell to `{"items":[],"total":0}` → deliverability_
placeholder_stub_handler hard-blocks delivery. `_search_target_model` picks the richest
non-spine table so the real search handler fires.
"""
from env_generator.llm_generator.multi_agent.runtime.route_projector import _search_target_model

def _m(cols): return {"cols": cols}

def test_picks_richest_non_spine():
    models = {
        "tenants": _m(["id", "name"]), "users": _m(["id", "email", "password_hash"]),
        "genres": _m(["id", "name"]),
        "titles": _m(["id","name","kind","year","genre","synopsis","poster","backdrop","video_url","duration"]),
        "profiles": _m(["id","user_id","name","avatar"]),
    }
    r = _search_target_model(models)
    assert r is not None and r[0] == "titles"

def test_excludes_spine_only():
    assert _search_target_model({"users": _m(["id"]), "tenants": _m(["id"])}) is None

def test_deterministic_tiebreak_alpha():
    r = _search_target_model({"beta": _m(["id","a","b"]), "alpha": _m(["id","a","b"])})
    assert r[0] == "alpha"  # equal cols -> alphabetical

if __name__ == "__main__":
    import pytest; raise SystemExit(pytest.main([__file__, "-q"]))
