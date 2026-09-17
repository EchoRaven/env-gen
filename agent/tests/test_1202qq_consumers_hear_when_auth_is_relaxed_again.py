"""#1202qq: consumers told an endpoint became auth-required are told when it is public again
(tiktok-r127: the frontend's logged-out fake-data workaround outlived the auth change by an hour)."""
import tempfile
from pathlib import Path

from env_generator.llm_generator.multi_agent.runtime.hub_registry import HubRegistry

SCHEMA = {"request": {}, "response": {"id": "string"}}


def _hubs(tmp):
    (Path(tmp) / "shared").mkdir()
    return HubRegistry(Path(tmp))


def _reg(hubs, auth):
    hubs.registryhub.register_endpoint(method="GET", path="/api/videos/feed",
                                       schema=dict(SCHEMA, auth_required=auth),
                                       provider="backend", agent="backend", status="implemented")


def _tasks(hubs):
    return [t for t in hubs.workhub.list_tasks() if "is public again" in str(t.get("title"))]


def test_auth_added_then_relaxed_notifies_the_consumer():
    with tempfile.TemporaryDirectory() as tmp:
        hubs = _hubs(tmp)
        _reg(hubs, False)
        hubs.registryhub.register_consumer(endpoint_id="GET /api/videos/feed", agent="frontend",
                                           file_path="src/services/api.js")
        _reg(hubs, True)                       # breaking: auth_added -> P0 to frontend
        assert not _tasks(hubs)
        _reg(hubs, False)                      # public again
        t = _tasks(hubs)
        assert len(t) == 1 and t[0]["assignee"] == "frontend"


def test_an_endpoint_never_announced_as_auth_added_stays_quiet():
    with tempfile.TemporaryDirectory() as tmp:
        hubs = _hubs(tmp)
        _reg(hubs, True)
        hubs.registryhub.register_consumer(endpoint_id="GET /api/videos/feed", agent="frontend",
                                           file_path="src/services/api.js")
        _reg(hubs, False)
        assert not _tasks(hubs)
