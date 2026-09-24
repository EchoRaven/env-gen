"""FIX #288 — a nested interaction's parent must NOT be owner-scoped when the parent is the
app's primary PUBLIC content (tiktok r73, live).

route_projector owner-scopes a nested endpoint's PARENT lookup
(``Video.author_id == user``) whenever the parent table carries owner_scoped_reads. That is
correct for a private container (``/api/projects/{id}/tasks`` — you may only see your own
project's tasks). It is WRONG for a public social item: TikTok's videos are public (#279
already serves the FYP feed logged-out), and commenting/liking authenticates the ACTOR but
targets ANY video. Owner-scoping the parent turned "must log in to comment" into "can only
comment on your OWN videos" → a non-author's POST/GET /api/videos/{id}/comments resolved
``parent is None`` → 404 → the fyp_comments ui_flow failed, the sole remaining delivery
blocker on r73 (everything else green after #281-#287).

Fix (mirrors #279's "login wall is on interaction, not on the content"): when the parent table
IS the primary content model (_primary_content_model — the public feed source, chosen by shape),
skip the parent owner filter. A genuinely private container (not the feed's content model)
still scopes its parent, preserving the cross-user leak protection the filter was added for.
ENV-AGNOSTIC + LOCAL-ONLY (agent/tests/ gitignored).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.route_projector import _generate_handler, _primary_content_model  # noqa: E402


def _m(cls, cols, fks=None):
    return {"cls": cls, "cols": cols, "fks": fks or {}}

# videos = the richest feed-shaped table → the primary PUBLIC content model.
# projects = also timestamped but leaner → a private container, NOT primary content.
MODELS = {
    "users": _m("User", ["id", "email", "name"]),
    "videos": _m("Video", ["id", "created_at", "author_id", "caption", "video_url",
                            "thumbnail", "sound_id", "likes"],
                 fks={"author_id": "users"}),
    "comments": _m("Comment", ["id", "created_at", "video_id", "user_id", "text"],
                   fks={"video_id": "videos", "user_id": "users"}),
    "projects": _m("Project", ["id", "created_at", "owner_id", "name"],
                   fks={"owner_id": "users"}),
    "tasks": _m("Task", ["id", "created_at", "project_id", "title"],
                fks={"project_id": "projects"}),
}


def test_videos_is_the_primary_content_model():
    pc = _primary_content_model(MODELS)
    assert pc is not None and pc[0] == "videos"


def _gen(method, path, scoped):
    return _generate_handler(method, path, auth=True, models=MODELS, idx=1,
                             response_key="", owner_scoped_tables=scoped)


def test_get_comments_on_public_video_not_parent_scoped():
    src = _gen("GET", "/api/videos/{video_id}/comments", {"videos", "comments"})
    # the parent Video lookup must NOT be filtered by author_id (#288)
    assert 'getattr(Video, "author_id") == _fw_owner_val' not in src


def test_post_comment_on_public_video_not_parent_scoped():
    src = _gen("POST", "/api/videos/{id}/comments", {"videos", "comments"})
    assert 'getattr(Video, "author_id") == _fw_owner_val' not in src


def test_private_container_parent_still_scoped():
    """The越权 protection the filter exists for MUST survive: projects is a private
    container (not the primary content model), so its nested tasks stay parent-scoped."""
    src = _gen("GET", "/api/projects/{project_id}/tasks", {"projects", "tasks"})
    assert 'getattr(Project, "owner_id") == _fw_owner_val' in src


def test_unscoped_parent_unaffected():
    """When the parent table isn't owner-scoped at all, behaviour is unchanged (no filter)."""
    src = _gen("GET", "/api/videos/{video_id}/comments", set())
    assert 'author_id") == _fw_owner_val' not in src
