"""#1202qk: a failing flow whose only auth_required endpoint is an identity probe (`/auth/me`)
gets no 'declare auth_required=false' note - a 401 there is the logged-out answer (r127)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_1202fr_auth_wedge_note import _Hubs, _Reg  # noqa: E402

from env_generator.llm_generator.multi_agent.runtime.deliverability import (  # noqa: E402
    _auth_wedge_note_1202fr,
)

PAGES = {"comments": {"name": "fyp_feed_comments_panel", "route": "/video/:id",
                      "apis_used": ["GET /auth/me", "GET /api/videos/{id}"]}}
EPS = {"GET /auth/me": {"method": "GET", "path": "/auth/me", "schema": {"auth_required": True}},
       "GET /api/videos/{id}": {"method": "GET", "path": "/api/videos/{id}",
                                "schema": {"auth_required": False}}}


def test_the_identity_probe_alone_produces_no_note():
    assert _auth_wedge_note_1202fr(_Hubs(pages=PAGES, eps=EPS), ["fyp_feed_comments_panel"]) == ""


def test_a_real_protected_read_still_produces_the_note():
    eps = dict(EPS)
    eps["GET /api/videos/{id}"] = {"method": "GET", "path": "/api/videos/{id}",
                                   "schema": {"auth_required": True}}
    note = _auth_wedge_note_1202fr(_Hubs(pages=PAGES, eps=eps), ["fyp_feed_comments_panel"])
    assert "GET /api/videos/{id}" in note and "/auth/me" not in note
