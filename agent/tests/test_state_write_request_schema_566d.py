"""#566d (netflix r115 advisory journey): a projected #556 state-write create (e.g.
POST /api/continue-watching) 400'd with `null value in column "title_id"` because the
endpoint was registered with a schema carrying only {response_key, auth_required} — no
`request` sub-schema — so the TEST-USER journey's _probe_body (which synthesizes the body
from schema.request) never sent the required subject FK (title_id). The app handler was
correct (title_id IS required); the fix makes the contract-derived probe send it.

Fix: heal_state_write_endpoints emits schema.request = {subject_fk: "int", ...} from the
subject FKs it already knows. Then _probe_body sends title_id (non-null) → 201 (or a
tolerated 404 for a nonexistent FK) instead of the NOT-NULL 400. Generalizable to every
state-write; no product literals.
"""
from env_generator.llm_generator.multi_agent.runtime import heal_pipeline as hp
from env_generator.llm_generator.multi_agent.runtime import route_projector as rp
from env_generator.llm_generator.multi_agent.runtime.validation_runner import _probe_body


class _FakeHub:
    def __init__(self):
        self.calls = []

    def register_endpoint(self, **kw):
        self.calls.append(kw)
        return {}

    def list_tables(self):
        return {}

    def get_endpoints(self):
        return {}


def _run(monkeypatch, endpoints):
    hub = _FakeHub()
    monkeypatch.setattr(rp, "project_state_write_endpoints",
                        lambda *a, **k: {"projected": [], "endpoints": endpoints})
    hp.heal_state_write_endpoints("/tmp/does_not_exist_backend_566d", hub)
    return hub


def test_state_write_registers_request_schema_from_subject_fks(monkeypatch):
    ep = {"method": "POST", "path": "/api/continue-watching",
          "response_key": "item", "auth_required": True,
          "subject_fks": ["title_id", "episode_id"],
          "state_columns": ["progress_seconds"],
          "natural_keys": ["profile_id", "title_id"], "owner_fk": "profile_id"}
    hub = _run(monkeypatch, [ep])
    assert hub.calls, "register_endpoint was not called"
    schema = hub.calls[0]["schema"]
    assert schema.get("request") == {"title_id": "int", "episode_id": "int"}, schema
    # end-to-end: _probe_body now emits the subject FKs (non-null) → no NOT-NULL 400
    body = _probe_body({"schema": schema})
    assert body.get("title_id") == 1 and body.get("episode_id") == 1, body


def test_subject_fks_still_passed_through_as_metadata(monkeypatch):
    ep = {"method": "POST", "path": "/api/continue-watching",
          "response_key": "item", "auth_required": True,
          "subject_fks": ["title_id"], "state_columns": [], "natural_keys": [],
          "owner_fk": "profile_id"}
    hub = _run(monkeypatch, [ep])
    # the #556-pt2 metadata (frontend consumer) is preserved alongside the new request schema
    assert hub.calls[0].get("subject_fks") == ["title_id"]
    assert hub.calls[0]["schema"]["request"] == {"title_id": "int"}


def test_no_subject_fks_omits_request_schema(monkeypatch):
    ep = {"method": "POST", "path": "/api/foo", "response_key": "item",
          "auth_required": True, "subject_fks": [], "state_columns": ["count"],
          "natural_keys": [], "owner_fk": "user_id"}
    hub = _run(monkeypatch, [ep])
    # byte-identical for a state-write with no subject FK: no spurious request key
    assert "request" not in hub.calls[0]["schema"], hub.calls[0]["schema"]


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
