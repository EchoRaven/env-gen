"""#566f + #566i + #566n: complete the request schema for CREATE endpoints so the test-user journey /
chain synth / frontend send the target table's required fields — else the create NOT-NULL-violates → 400.

#566f: add non-owner subject FK columns (my_list.title_id) as {fk:"int"}.
#566i: add common REQUIRED non-FK TEXT columns (name/title/label/…) — e.g. profiles.name.
#566n: (a) also heal NESTED collection creates (POST /api/titles/{id}/rating), and (b) add EVERY
       genuinely-REQUIRED column (NOT-NULL, non-PK, non-default — parsed from the ORM) typed from the
       column — e.g. rating.value (a NOT-NULL numeric the subject-FK/text passes miss).
Byte-safe: only ADDs missing fields, never overwrites, excludes the server-derived owner FK.
"""
from env_generator.llm_generator.multi_agent.runtime import heal_pipeline as hp
from env_generator.llm_generator.multi_agent.runtime import route_projector as rp

_MODELS = {
    "my_list": {"cls": "MyList", "cols": ["id", "profile_id", "title_id"],
                "fks": {"profile_id": "profiles", "title_id": "titles"}, "types": {}, "required": []},
    "profiles": {"cls": "Profile", "cols": ["id", "user_id", "name"],
                 "fks": {"user_id": "users"}, "types": {}, "required": []},
    "titles": {"cls": "Title", "cols": ["id", "name", "slug"], "fks": {}, "types": {}, "required": []},
    "tags": {"cls": "Tag", "cols": ["id", "slug"], "fks": {}, "types": {}, "required": []},
    "ratings": {"cls": "Rating", "cols": ["id", "profile_id", "title_id", "value", "note"],
                "fks": {"profile_id": "profiles", "title_id": "titles"},
                "types": {"value": "Integer", "note": "String"},
                "required": ["profile_id", "title_id", "value"]},
}


class _FakeHub:
    def __init__(self, endpoints):
        self._eps = endpoints
        self.calls = []

    def get_endpoints(self):
        return self._eps

    def register_endpoint(self, **kw):
        self.calls.append(kw)
        return {}


def _ep(method, path, request=None):
    schema = {"response_key": "item", "auth_required": True}
    if request is not None:
        schema["request"] = request
    return {"method": method, "path": path, "schema": schema, "provider": "backend",
            "status": "defined", "metadata": {"response_key": "item", "auth_required": True}}


def _run(monkeypatch, endpoints):
    monkeypatch.setattr(rp, "_orm_models", lambda *a, **k: _MODELS)
    hub = _FakeHub({e["path"] + e["method"]: e for e in endpoints})
    hp.heal_create_endpoint_request_schemas(hub, "/tmp/does_not_exist_566n")
    return hub


def _call(hub, path):
    return next((c for c in hub.calls if c.get("path") == path), None)


def test_lane_create_missing_subject_fk_is_healed(monkeypatch):
    req = _call(_run(monkeypatch, [_ep("POST", "/api/my-list")]), "/api/my-list")["schema"]["request"]
    assert req.get("title_id") == "int" and "profile_id" not in req, req


def test_owner_only_table_with_required_name_heals_name(monkeypatch):
    req = _call(_run(monkeypatch, [_ep("POST", "/api/profiles")]), "/api/profiles")["schema"]["request"]
    assert req.get("name") == "str" and "user_id" not in req, req


def test_nested_create_heals_required_typed_column(monkeypatch):
    # #566n: POST /api/titles/{id}/rating — nested create; must add value (NOT-NULL Integer) + the
    # title_id subject FK; must EXCLUDE the owner profile_id.
    hub = _run(monkeypatch, [_ep("POST", "/api/titles/{id}/rating")])
    c = _call(hub, "/api/titles/{id}/rating")
    assert c is not None, "nested collection create must be healed"
    req = c["schema"]["request"]
    assert req.get("value") == "int", req         # the missing required numeric
    assert req.get("title_id") == "int", req
    assert "profile_id" not in req, req            # server-derived owner FK excluded


def test_action_verb_not_healed(monkeypatch):
    # /{id}/toggle resolves to a parent by fallback — must NOT force-add the parent's columns
    hub = _run(monkeypatch, [_ep("POST", "/api/my-list/{id}/toggle")])
    assert hub.calls == []


def test_item_path_not_healed(monkeypatch):
    assert _run(monkeypatch, [_ep("POST", "/api/my-list/{id}")]).calls == []


def test_required_typed_column_on_top_level_create(monkeypatch):
    # a top-level create on ratings adds value + title_id (subject fk), excludes owner
    req = _call(_run(monkeypatch, [_ep("POST", "/api/ratings")]), "/api/ratings")["schema"]["request"]
    assert req.get("value") == "int" and req.get("title_id") == "int" and "profile_id" not in req, req


def test_table_with_nothing_required_not_healed(monkeypatch):
    assert _run(monkeypatch, [_ep("POST", "/api/tags")]).calls == []


def test_already_complete_is_noop(monkeypatch):
    hub = _run(monkeypatch, [_ep("POST", "/api/titles/{id}/rating",
                                 request={"value": "int", "title_id": "int"})])
    assert _call(hub, "/api/titles/{id}/rating") is None


def test_non_post_skipped(monkeypatch):
    assert _run(monkeypatch, [_ep("GET", "/api/profiles")]).calls == []


def test_preserves_existing_request_fields(monkeypatch):
    req = _call(_run(monkeypatch, [_ep("POST", "/api/my-list", request={"note": "str"})]),
                "/api/my-list")["schema"]["request"]
    assert req.get("note") == "str" and req.get("title_id") == "int", req


def test_never_raises_on_garbage(monkeypatch):
    monkeypatch.setattr(rp, "_orm_models", lambda *a, **k: _MODELS)
    assert hp.heal_create_endpoint_request_schemas(None, "/tmp/x") == {"healed": []}


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
