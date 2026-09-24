"""Guard: FIX #206 — an aggregate/computed FRAMEWORK stub is SOFT, not a HARD wall.

r13 (furthest run) walled its delivery on GET /api/creators/suggested — a
FRAMEWORK _projected_* empty stub. Unlike a mis-named table (#200/#202/#205
resolve those), this is a genuinely-computed view: 'suggested creators' needs
an algorithm, there's no plain backing table ('creators' isn't even a table —
it's a semantic alias for users), and the lane can't edit a projected handler.
An empty 'suggested' section is an HONEST empty state, not a harmful
mock/placeholder. So a FRAMEWORK stub whose route ends in a known
aggregate/filter qualifier (suggested/recommended/popular/trending/featured/
discover/nearby/...) is downgraded from a HARD #173 blocker to a soft skip —
the no_real_data browser gate remains the backstop. A LANE custom stub, and a
non-aggregate framework stub, stay HARD.
"""

import sys
import tempfile
import unittest
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.backend_audit import stub_handler_blockers  # noqa: E402


def _backend(src, name="main.py"):
    d = Path(tempfile.mkdtemp())
    (d / name).write_text(src)
    return d


def _proj(path, fn):
    return (f'from fastapi import FastAPI, Depends\napp = FastAPI()\n\n'
            f'@app.get("{path}")\n'
            f'def {fn}(db=Depends(get_db)):\n    return {{"items": [], "total": 0}}\n')


class AggregateStubSoftTests(unittest.TestCase):
    def test_aggregate_framework_stub_not_blocked(self):
        be = _backend(_proj("/api/creators/suggested",
                            "_projected_get_api_creators_suggested_2"))
        self.assertEqual(stub_handler_blockers(be), [])

    def test_various_aggregate_qualifiers_soft(self):
        for path, fn in (
            ("/api/videos/trending", "_projected_get_api_videos_trending_1"),
            ("/api/users/recommended", "_projected_get_api_users_recommended_1"),
            ("/api/posts/popular", "_projected_get_api_posts_popular_1"),
            ("/api/streams/featured", "_projected_get_api_streams_featured_1"),
        ):
            be = _backend(_proj(path, fn))
            self.assertEqual(stub_handler_blockers(be), [],
                             f"{path} should be SOFT")

    def test_non_aggregate_framework_stub_stays_hard(self):
        be = _backend(_proj("/api/messages",
                            "_projected_get_api_messages_1"))
        self.assertEqual(len(stub_handler_blockers(be)), 1)

    def test_lane_custom_aggregate_stub_stays_hard(self):
        # a LANE custom stub (not _projected_) on an aggregate route stays HARD —
        # the lane owns it and can implement the real query.
        src = ('from fastapi import APIRouter, Depends\nrouter = APIRouter()\n\n'
               '@router.get("/api/creators/suggested")\n'
               'def suggested(db=Depends(get_db)):\n    return {"items": []}\n')
        be = _backend(src, "custom_routes.py")
        self.assertEqual(len(stub_handler_blockers(be)), 1)

    def test_env_flag_can_disable_soft(self):
        import os
        be = _backend(_proj("/api/creators/suggested",
                            "_projected_get_api_creators_suggested_2"))
        os.environ["ENVGEN_AGGREGATE_STUB_SOFT"] = "0"
        try:
            self.assertEqual(len(stub_handler_blockers(be)), 1)
        finally:
            os.environ.pop("ENVGEN_AGGREGATE_STUB_SOFT", None)


if __name__ == "__main__":
    unittest.main()
