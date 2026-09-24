"""#1202gp — the primary CONTENT model must not be missed just because it has no timestamp.

Live evidence, tiktok-web-r98 (`app/backend/main.py`, three occurrences):

    _parent = db.query(Video).filter(getattr(Video, "id") == id).filter(
        getattr(Video, "author_id") == _fw_owner_val(Video, "author_id", user)).first()
    if _parent is None:
        raise HTTPException(status_code=404, detail="parent resource not found")

i.e. "you may only like / save / comment on videos YOU authored" — projected code the lane
cannot fix. #288 exists precisely to skip that parent filter for the app's primary PUBLIC
content, but its guard `_primary_content_model` REQUIRED a timestamp column ("a feed is
chronological"), and the generated `videos` table has none of its 13 columns time-shaped.
So the guard picked `messages` (r98) / `suggested_creators` (r96) / nothing at all (r97) and
`videos` kept the filter. The chain ledger shows the cost: the verifier CREATED video 42/43
(POST /api/videos -> 201) and every child write then 404'd — 19 of r98's 34 chain failures.

The signal that does hold across domains is ATTACHMENT: the primary content is what the other
tables hang off by a `<singular>_id` column. Measured over the whole corpus — tiktok
`videos` 19/22 runs, netflix `titles` ~41/45, instagram `posts` 18/18, googlemaps `places` —
and where the old ladder answered correctly (instagram) the new rung AGREES, so it is
additive: with no attachments anywhere, the timestamp ladder is left untouched.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.route_projector import (  # noqa: E402
    _generate_handler, _primary_content_model)


# Verbatim from generated/tiktok-web-r98/shared/hubs/registryhub_tables.json through the
# PRODUCER (`_models_meta`): `cols` is a list of STRINGS, and the content tables carry an
# EMPTY `fks` map — the attachment signal therefore cannot rely on `fks` being populated.
R98 = {
    "users": {"cls": "User", "cols": ["id", "username", "email"], "fks": {}},
    "videos": {"cls": "Video", "cols": ["id", "author_id", "caption", "video_url",
                                        "thumbnail", "duration", "sound_id", "category",
                                        "views", "likes", "comments", "shares", "saves"],
               "fks": {}},
    "comments": {"cls": "Comment", "cols": ["id", "video_id", "user_id", "username",
                                            "avatar", "text", "likes", "parent_id"],
                 "fks": {}},
    "video_likes": {"cls": "VideoLike", "cols": ["id", "user_id", "video_id"], "fks": {}},
    "video_saves": {"cls": "VideoSave", "cols": ["id", "user_id", "video_id"], "fks": {}},
    "messages": {"cls": "Message", "cols": ["id", "user_id", "peer_id", "last_message",
                                            "unread", "updated_at"],
                 "fks": {"user_id": "users", "peer_id": "users"}},
}


def test_the_timestampless_content_table_still_wins():
    """r98's actual models: `videos` has no timestamp, `messages` has one."""
    picked = _primary_content_model(R98)
    assert picked is not None, "returned None — every nested parent then gets owner-filtered"
    assert picked[0] == "videos", "picked %r; messages only wins on the timestamp rung" % (
        picked[0],)


def test_the_parent_filter_is_deliberately_left_on_the_narrow_predicate():
    """#747 — the 404 cascade is NOT fixed here, and that exclusion is deliberate.

    r98's `POST /api/videos/{id}/like` 404s because `videos` is owner-scoped AND #288's
    exemption misses it. Widening the exemption to the attachment winner would have fixed the
    404 — and dropped cross-user isolation in a project tracker, where `projects(user_id)` +
    `tasks(user_id, project_id)` is the SAME shape as `videos(author_id)` + `video_likes(
    user_id, video_id)`. `test_route_projector_nested_isolation` caught exactly that.

    Public-vs-private is semantic (#1202gd measured this over 116 backends / 267 tables), so
    the exemption stays on `_feed_shaped_model_288` until the reference spec's declared
    `visibility` reaches the projector. This test pins the trade so a later widening is a
    deliberate act, not an accident: the parent filter is STILL applied to owner-scoped
    content here, and that is the known, recorded cost.
    """
    src = _generate_handler("POST", "/api/videos/{id}/like", True, R98, 0,
                            owner_scoped_tables=["videos", "video_likes", "comments"])
    parent = [l for l in src.split("\n") if "_parent = db.query(" in l]
    assert parent, "no parent lookup projected at all:\n%s" % src
    assert "author_id" in parent[0], (
        "the exemption widened without the declared-visibility signal — check that the "
        "isolation ratchet still holds before accepting this:\n%s" % parent[0])


def test_a_genuinely_private_container_keeps_its_parent_filter():
    """#288's protection must survive: a private container that is NOT the content model."""
    models = dict(R98)
    models["projects"] = {"cls": "Project", "cols": ["id", "owner_id", "name", "created_at"],
                          "fks": {"owner_id": "users"}}
    models["tasks"] = {"cls": "Task", "cols": ["id", "project_id", "owner_id", "title"],
                       "fks": {"project_id": "projects", "owner_id": "users"}}
    assert _primary_content_model(models)[0] == "videos"
    src = _generate_handler("POST", "/api/projects/{id}/tasks", True, models, 0,
                            owner_scoped_tables=["projects", "tasks"])
    parent = [l for l in src.split("\n") if "_parent = db.query(" in l or "parent = db.query(" in l]
    assert parent and "owner_id" in parent[0], (
        "a private container lost its parent scoping — cross-user leak:\n%s" % (parent or src))


def test_the_case_the_old_ladder_got_right_is_unchanged():
    """instagram: `posts` won on the timestamp rung and must still win."""
    models = {
        "users": {"cls": "User", "cols": ["id", "username"], "fks": {}},
        "posts": {"cls": "Post", "cols": ["id", "user_id", "caption", "image_url",
                                          "created_at"],
                  "fks": {"user_id": "users"}},
        "post_likes": {"cls": "PostLike", "cols": ["id", "user_id", "post_id"], "fks": {}},
        "stories": {"cls": "Story", "cols": ["id", "user_id", "media_url", "created_at"],
                    "fks": {"user_id": "users"}},
    }
    assert _primary_content_model(models)[0] == "posts"


def test_with_no_attachments_the_timestamp_ladder_is_left_alone():
    """smoke-notes' shape: nothing hangs off anything, so the old answer must stand."""
    models = {
        "users": {"cls": "User", "cols": ["id", "username"], "fks": {}},
        "notes": {"cls": "Note", "cols": ["id", "user_id", "body", "created_at"],
                  "fks": {"user_id": "users"}},
    }
    picked = _primary_content_model(models)
    assert picked is not None and picked[0] == "notes"


def test_the_attachment_rung_is_documented_where_it_is_decided():
    """#747 — a deliberate ranking change has to be readable at the decision, not only here."""
    import inspect
    doc = inspect.getsource(_primary_content_model)
    assert "1202gp" in doc, "the attachment rung is undocumented at its decision site"


def test_the_resourceless_feed_route_serves_content_not_direct_messages():
    """The second, independent consequence of the same miss — r98's own main.py:

        @app.get("/api/explore")
        def _projected_get_api_explore_8(db=Depends(get_db)):
            rows = db.query(Message).limit(100).all()

    The EXPLORE feed served direct messages, because a resource-less feed route resolves its
    model through `_primary_content_model` too. The same run's `/api/search` was CORRECT
    (`db.query(Video)`) — it goes through `_search_target_model`, the sibling chooser that
    already dropped the timestamp requirement (#569). Two sibling routes, one ledger, one
    right and one wrong: the difference was only which chooser they asked.
    """
    src = _generate_handler("GET", "/api/explore", False, R98, 8)
    q = [l.strip() for l in src.split("\n") if "db.query(" in l]
    assert q, "no query projected:\n%s" % src
    assert "db.query(Video)" in q[0], "explore feed is not serving the content model: %s" % q[0]
    assert "Message" not in q[0], "explore feed is serving direct messages: %s" % q[0]
