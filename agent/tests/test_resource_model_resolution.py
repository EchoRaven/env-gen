"""Guard: FIX #200 — resolve GET paths whose segments don't literally equal the
table name, so the projector emits a REAL DB-reading handler instead of an
empty-collection stub (which #173 then HARD-blocks — and, being a FRAMEWORK
handler in main.py, the lane can't fix → guaranteed wall).

r10 live evidence: three FRAMEWORK-projected GET handlers shipped
{"items": [], "total": 0} stubs and walled delivery on #173:
  GET /api/live/streams  ↔ table `live_streams`  (path split across 2 segments)
  GET /api/messages      ↔ table `direct_messages` (table is a <qualifier>_<seg>)
  GET /api/activity       ↔ no table (genuinely unmappable — out of scope)
Two deterministic resolution rungs added to _resource_model, tried only AFTER
the exact/plural match fails so no existing resolution changes:
  1. multi-segment join: adjacent non-param segments joined with '_' → live_streams
  2. suffix match: a table whose name ends with '_<segment>[s]' → direct_messages
"""

import sys
import unittest
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime import route_projector as rp  # noqa: E402


def _m(*names):
    return {n: {"cls": n.title().replace("_", ""), "cols": ["id"], "fks": {}}
            for n in names}


class ResolutionTests(unittest.TestCase):
    def test_multi_segment_join(self):
        models = _m("live_streams", "videos", "users")
        res = rp._resource_model("/api/live/streams", models)
        self.assertIsNotNone(res)
        self.assertEqual(res[0], "live_streams")

    def test_multi_segment_join_with_param_tail(self):
        models = _m("live_streams", "users")
        res = rp._resource_model("/api/live/streams/{id}", models)
        self.assertEqual(res[0], "live_streams")

    def test_suffix_match_qualified_table(self):
        models = _m("direct_messages", "users", "videos")
        res = rp._resource_model("/api/messages", models)
        self.assertEqual(res[0], "direct_messages")

    def test_exact_match_still_preferred_over_suffix(self):
        # if both `messages` and `direct_messages` exist, the EXACT one wins
        models = _m("messages", "direct_messages", "users")
        res = rp._resource_model("/api/messages", models)
        self.assertEqual(res[0], "messages")

    def test_genuinely_unmappable_stays_none(self):
        # /api/activity with no activity/*_activity table → still None (honest)
        models = _m("notifications", "users", "videos")
        res = rp._resource_model("/api/activity", models)
        self.assertIsNone(res)

    def test_plain_paths_unchanged(self):
        models = _m("videos", "users", "live_streams")
        self.assertEqual(rp._resource_model("/api/videos", models)[0], "videos")
        self.assertEqual(rp._resource_model("/api/videos/{id}", models)[0], "videos")

    def test_suffix_no_false_match_on_short_segment(self):
        # a 1-2 char segment must not suffix-match a big table (avoid noise)
        models = _m("categories", "users")
        # /api/es must NOT match categori-ES
        res = rp._resource_model("/api/es", models)
        self.assertIsNone(res)

    def test_generates_real_handler_for_joined_table(self):
        models = {"live_streams": {"cls": "LiveStream",
                                   "cols": ["id", "title"], "fks": {}},
                  "users": {"cls": "User", "cols": ["id"], "fks": {}}}
        h = rp._generate_handler("GET", "/api/live/streams", False, models, 0)
        self.assertIn("db.query(LiveStream)", h)
        self.assertNotIn('"items": []', h.replace('"items": [', '"items": [ '))


if __name__ == "__main__":
    unittest.main()
