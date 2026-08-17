"""#477 — the r51/r48 delivery-convergence blocker: contract-completeness synthesized a
SPURIOUS `POST /api/titles` for the READ-ONLY titles catalog. ROOT (database_scaffold.
synthesize_missing_create_endpoints): a resource was marked 'writable' (⇒ warrants a plain
CREATE) if it had PATCH/PUT/DELETE OR a POST SUB-ACTION (/<res>/{id}/<verb>). Netflix's
`POST /api/titles/{id}/rating` is a rate ACTION, not evidence titles are user-creatable —
so `titles` got a spurious `POST /api/titles`, the business_chain tested it → 400 (titles
need many required fields) → business_chain_failing → churn (r51: 0 release; r48 same).

FIX: only a DIRECT item mutation (PATCH/PUT/DELETE /<res>/{id}) proves user-mutability ⇒
warrants a create ('you can create X if you can edit/delete X'). A POST sub-action no longer
implies it. Preserves the outlook messages case (it has PATCH/DELETE /messages/{id}).
Generalizable: any seeded read-only catalog (titles/genres) never gets a spurious create."""
from env_generator.llm_generator.multi_agent.runtime.database_scaffold import (
    synthesize_missing_create_endpoints)


def _ep(m, p):
    return {"method": m, "path": p}


def _tbl(*cols):
    return {"columns": [{"name": "id", "primary_key": True}]
            + [{"name": c, "type": "string"} for c in cols]}


def test_readonly_catalog_with_subaction_gets_no_spurious_create():
    # Netflix titles: GET catalog (+by-id/trending) + a rating SUB-ACTION, NO direct mutation
    eps = [_ep("GET", "/api/titles"), _ep("GET", "/api/titles/{id}"),
           _ep("GET", "/api/titles/trending"), _ep("POST", "/api/titles/{id}/rating")]
    _out, added = synthesize_missing_create_endpoints(eps, {"titles": _tbl("name")})
    assert "/api/titles" not in added, \
        "#477: a read-only catalog with only a POST sub-action must NOT get a spurious CREATE"


def test_item_mutable_resource_still_gets_create():
    # outlook messages: GET + PATCH/DELETE on /{id} (direct mutation) → CREATE preserved
    eps = [_ep("GET", "/api/messages"), _ep("PATCH", "/api/messages/{id}"),
           _ep("DELETE", "/api/messages/{id}"), _ep("POST", "/api/messages/{id}/reply")]
    _out, added = synthesize_missing_create_endpoints(eps, {"messages": _tbl("body")})
    assert "/api/messages" in added, \
        "#477: a PATCH/DELETE-mutable resource still gets its synthesized create (outlook case)"


def test_existing_post_not_duplicated():
    eps = [_ep("GET", "/api/my_list"), _ep("POST", "/api/my_list"),
           _ep("DELETE", "/api/my_list/{id}")]
    _out, added = synthesize_missing_create_endpoints(eps, {"my_list": _tbl("title_id")})
    assert "/api/my_list" not in added, "already has POST → no duplicate synthesis"


def test_pure_readonly_catalog_no_create():
    eps = [_ep("GET", "/api/genres"), _ep("GET", "/api/genres/{id}/titles")]
    _out, added = synthesize_missing_create_endpoints(eps, {"genres": _tbl("name")})
    assert added == [], "#477: a pure read-only catalog gets no create"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
