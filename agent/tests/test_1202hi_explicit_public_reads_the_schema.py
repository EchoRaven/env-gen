"""#1202hi — `_explicit_public` must read the copy the LANE writes.

#1202ga established, from tiktok-r97 end to end, that a lane declares a read public by
setting `schema.auth_required = False` (that is what `register_endpoint(schema=...)` stores);
`metadata.auth_required` is a MIRROR taken at registration and keeps its original value
forever. `resolve_endpoint_auth` was taught the precedence -- top level, then schema, then
metadata -- and the 401 loop it caused was fixed.

`#320`'s public-feed exemption was NOT. Both emitters compute their own "did the lane
declare this public?" and they disagree:

    route_projector.project_missing_routes:
        (ep["auth_required"] is False) or (ep["metadata"]["auth_required"] is False)
        -> never looks at the schema, i.e. never sees the lane's declaration
    backend_skeleton.render_skeleton_main:
        checks ep, schema AND metadata

Measured over the 142 runs on this machine: 3636 endpoints state auth somewhere, 1518 carry
both copies, and **220 of them are `schema=False, metadata=True`** -- the lane declared a
public read and `project_missing_routes` cannot see it. In r103 that is 20 of 80, including
`/api/videos/{id}`, `/api/explore`, `/api/search` and `/api/live`: exactly the logged-out
surface #320 exists to keep open.

The 41 endpoints in the opposite direction (`schema=True, metadata=False`) are the only ones
where a shared precedence differs from the old any-copy-says-False rule, and there it
TIGHTENS to auth-required -- the safe direction, and the one #1202ga argued for (the schema
is the contract, the mirror is stale).

Both existing tests for this behaviour (#320, #1099) put `auth_required` at the TOP level of
the endpoint dict, a shape production never writes -- which is why neither ever failed.
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "env_generator" / "llm_generator"), str(Path(__file__).resolve().parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from test_320_explicit_public_read_on_owner_scoped_table import _backend, _handler_src

from multi_agent.runtime.backend_skeleton import render_skeleton_main
from multi_agent.runtime.route_projector import (_stated_auth_1202hi,
                                                 project_missing_routes,
                                                 resolve_endpoint_auth)

_TABLES = {"posts": {"name": "posts", "metadata": {"owner_scoped_reads": True},
                     "schema": {"columns": [
                         {"name": "id", "type": "integer", "primary_key": True},
                         {"name": "author_id", "type": "integer", "references": "users.id"},
                         {"name": "body", "type": "text"}]}},
           "users": {"name": "users", "schema": {"columns": [
               {"name": "id", "type": "integer", "primary_key": True},
               {"name": "email", "type": "text"}]}}}


def _lane_declared_public():
    """The shape a lane actually writes: schema says public, the mirror is stale."""
    return {"method": "GET", "path": "/api/posts",
            "schema": {"auth_required": False},
            "metadata": {"auth_required": True}}


def test_precedence_is_top_level_then_schema_then_mirror():
    assert _stated_auth_1202hi({"auth_required": True,
                                "schema": {"auth_required": False}}) is True
    assert _stated_auth_1202hi({"schema": {"auth_required": False},
                                "metadata": {"auth_required": True}}) is False
    assert _stated_auth_1202hi({"metadata": {"auth_required": True}}) is True
    assert _stated_auth_1202hi({"schema": {}, "metadata": {}}) is None


def test_resolver_behaviour_is_unchanged():
    ep = _lane_declared_public()
    assert resolve_endpoint_auth("GET", "/api/posts", ep, ep["metadata"]) is False


def test_route_projector_honours_the_lane_declaration(tmp_path):
    be = _backend(tmp_path)
    project_missing_routes(be, [_lane_declared_public()], owner_scoped_tables={"posts"})
    pub = _handler_src((be / "main.py").read_text(encoding="utf-8"), "GET", "/api/posts")
    assert pub, "feed handler was projected"
    assert "get_current_user" not in pub, pub
    assert "_fw_owner_val" not in pub and "user.id" not in pub, pub


def test_skeleton_emitter_agrees(tmp_path):
    src = render_skeleton_main([_lane_declared_public()], _TABLES)
    body = _handler_src(src, "GET", "/api/posts")
    assert body, "feed handler was projected"
    assert "_fw_owner_val" not in body, body


def test_stale_mirror_cannot_open_a_read_the_schema_protects(tmp_path):
    """The 41-endpoint direction: the contract says auth, the mirror says public. The
    contract wins, so this TIGHTENS rather than opening a read."""
    ep = {"method": "GET", "path": "/api/posts",
          "schema": {"auth_required": True}, "metadata": {"auth_required": False}}
    assert _stated_auth_1202hi(ep) is True
    src = render_skeleton_main([ep], _TABLES)
    body = _handler_src(src, "GET", "/api/posts")
    assert "_fw_owner_val" in body, body


class _Reg:
    """The two calls the note makes, over the record shapes r103's ledger actually holds."""
    def __init__(self, ep_schema_auth, ep_meta_auth):
        self._ep = {"GET /api/videos": {
            "id": "GET /api/videos", "method": "GET", "path": "/api/videos",
            "schema": {"auth_required": ep_schema_auth},
            "metadata": {"auth_required": ep_meta_auth}}}
        self._pg = {"fyp_feed_logged_out": {
            "id": "fyp_feed_logged_out", "name": "fyp_feed_logged_out",
            "apis_used": ["GET /api/videos"]}}

    def list_ui_pages(self):
        return self._pg

    def get_endpoints(self):
        return self._ep


class _Hubs:
    def __init__(self, reg):
        self.registryhub = reg


def _note(schema_auth, meta_auth):
    from multi_agent.runtime.deliverability import _auth_wedge_note_1202fr
    return _auth_wedge_note_1202fr(_Hubs(_Reg(schema_auth, meta_auth)),
                                   ["fyp_feed_logged_out"])


def test_auth_wedge_note_does_not_flag_a_read_the_lane_made_public():
    """The stale mirror still says True; the lane's contract says public and the projector
    now serves it public. Reporting a wedge here sends the lane back to a fixed blocker."""
    assert _note(False, True) == ""


def test_auth_wedge_note_still_fires_on_a_genuinely_gated_read():
    """The note must keep working -- this is the r96 case it was built for."""
    assert "fyp_feed_logged_out" in _note(True, True)
