"""Guard: FIX #198 — resolve an action segment to a PARENT-PREFIXED join table.

r8 live evidence: the lane DID model the join tables (video_likes, video_saves,
user_follows) — the right thing — but the projector's _resource_model resolves
the action segment 'like' via _match_model('like'), which only matches
'like'/'likes', NOT 'video_likes'. So POST /api/videos/{id}/like fell back to
the `videos` parent → FIX #124 flagged 'like' unmapped → 404 → business_chain
wedges DESPITE a correctly-modeled schema. The projector must also try the
parent-prefixed join name `<parent_singular>_<verb>[s]` (video_likes), so BOTH
the lane's descriptive name AND #196's bare `likes` resolve.
"""

import sys
import unittest
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime import route_projector as rp  # noqa: E402


def _models():
    return {
        "videos": {"cls": "Video", "cols": ["id", "author_id"],
                   "fks": {"author_id": "users"}},
        "video_likes": {"cls": "VideoLike", "cols": ["id", "user_id", "video_id"],
                        "fks": {"user_id": "users", "video_id": "videos"}},
        "video_saves": {"cls": "VideoSave", "cols": ["id", "user_id", "video_id"],
                        "fks": {"user_id": "users", "video_id": "videos"}},
    }


class ActionJoinResolutionTests(unittest.TestCase):
    def test_parent_prefixed_join_resolves(self):
        res = rp._resource_model("/api/videos/{id}/like", _models())
        self.assertIsNotNone(res)
        self.assertEqual(res[0], "video_likes")

    def test_bare_verb_join_still_resolves(self):
        # #196's provisioned name: a bare `likes` table
        models = {"videos": {"cls": "Video", "cols": ["id"], "fks": {}},
                  "likes": {"cls": "Like", "cols": ["id", "user_id", "video_id"],
                            "fks": {"user_id": "users", "video_id": "videos"}}}
        res = rp._resource_model("/api/videos/{id}/like", models)
        self.assertEqual(res[0], "likes")

    def test_generates_real_insert_not_404(self):
        h = rp._generate_handler("POST", "/api/videos/{id}/like", True, _models(), 0)
        self.assertNotIn("not implemented by the projection", h)
        self.assertIn('valid["video_id"] = _parent.id', h)
        self.assertIn("_fw_owner_val(VideoLike", h)
        self.assertIn("db.add(obj)", h)

    def test_unmapped_action_still_404s(self):
        # no unfollows/user_unfollows table → genuinely unmapped → keep #124 404
        models = {"users": {"cls": "User", "cols": ["id"], "fks": {}}}
        h = rp._generate_handler("POST", "/api/users/{id}/unfollow", True, models, 0)
        self.assertIn("not implemented by the projection", h)

    def test_plain_resource_paths_unchanged(self):
        # a normal collection/item path must resolve to the resource, not a join
        models = _models()
        self.assertEqual(rp._resource_model("/api/videos", models)[0], "videos")
        self.assertEqual(rp._resource_model("/api/videos/{id}", models)[0], "videos")

    def test_nested_child_collection_unchanged(self):
        # /api/videos/{id}/comments must resolve to comments (a real child
        # resource), not a `video_comments` join — comments exists as its own table
        models = {"videos": {"cls": "Video", "cols": ["id"], "fks": {}},
                  "comments": {"cls": "Comment", "cols": ["id", "video_id"],
                               "fks": {"video_id": "videos"}}}
        res = rp._resource_model("/api/videos/{id}/comments", models)
        self.assertEqual(res[0], "comments")


if __name__ == "__main__":
    unittest.main()
