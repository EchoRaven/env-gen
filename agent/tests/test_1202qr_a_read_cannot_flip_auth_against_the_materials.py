"""#1202qr: the registry refuses a GET auth flip that contradicts the materials' visibility
(tiktok-r127 flipped the PUBLIC feed to auth_required -> auth_added P0 -> logged-out fake feed;
6-28 flips per run in r120-r127)."""
import json
import tempfile
from pathlib import Path

from env_generator.llm_generator.multi_agent.runtime.hub_registry import HubRegistry
from env_generator.llm_generator.multi_agent.runtime.registryhub import _resolved_auth_1202gr

SPEC = {"entities": [{"name": "videos", "visibility": "public"},
                     {"name": "video_saves", "visibility": "owner"},
                     {"name": "sounds"}]}


def _hubs(tmp):
    root = Path(tmp)
    (root / "shared").mkdir()
    (root / "design").mkdir()
    (root / "design" / "reference_spec.json").write_text(json.dumps(SPEC))
    return HubRegistry(root)


def _reg(hubs, path, auth):
    return hubs.registryhub.register_endpoint(
        method="GET", path=path, schema={"response": {"id": "string"}, "auth_required": auth},
        provider="backend", agent="backend", status="implemented")


def _stored(hubs, path):
    return _resolved_auth_1202gr(hubs.registryhub.get_endpoints()["GET " + path])


def test_a_public_feed_cannot_be_flipped_to_auth():
    with tempfile.TemporaryDirectory() as tmp:
        hubs = _hubs(tmp)
        _reg(hubs, "/api/videos/feed", False)
        r = _reg(hubs, "/api/videos/feed", True)
        assert _stored(hubs, "/api/videos/feed") is False
        assert "materials declare `videos` public" in r.get("_auth_flip_refused", "")
        assert not [t for t in hubs.workhub.list_tasks()
                    if "Fix breaking change in GET /api/videos/feed" == t.get("title")]


def test_an_owner_table_cannot_be_flipped_public():
    with tempfile.TemporaryDirectory() as tmp:
        hubs = _hubs(tmp)
        _reg(hubs, "/api/video_saves", True)
        _reg(hubs, "/api/video_saves", False)
        assert _stored(hubs, "/api/video_saves") is True


def test_first_registration_silent_tables_and_me_paths_are_untouched():
    with tempfile.TemporaryDirectory() as tmp:
        hubs = _hubs(tmp)
        r = _reg(hubs, "/api/videos", True)                  # first registration: accepted
        assert _stored(hubs, "/api/videos") is True and "_auth_flip_refused" not in r
        _reg(hubs, "/api/sounds", False)
        _reg(hubs, "/api/sounds", True)                      # materials silent: flip allowed
        assert _stored(hubs, "/api/sounds") is True
        _reg(hubs, "/api/me/videos", False)
        _reg(hubs, "/api/me/videos", True)                   # a /me read: not judged
        assert _stored(hubs, "/api/me/videos") is True
