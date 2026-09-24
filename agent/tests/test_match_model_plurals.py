"""Guard: FIX #202 — _match_model handles the y→ies irregular plural.

r11 live: after its lane registered the missing tables, /api/live/streams and
/api/messages resolved (via #200 + exact match) but /api/activity STILL stubbed
— because the table is `activities` and _match_model only knew the regular
+s/-s plural, so 'activity' didn't match 'activities'. Same for category/
categories, story/stories, company/companies. A GET whose resource is an
'-y'→'-ies' noun would ship an empty stub → #173 wall.
"""

import sys
import unittest
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime import route_projector as rp  # noqa: E402


def _m(*names):
    return {n: {"cls": n.title(), "cols": ["id"], "fks": {}} for n in names}


class MatchModelPluralTests(unittest.TestCase):
    def test_y_ies_singular_segment_matches_ies_table(self):
        models = _m("activities", "users")
        self.assertEqual(rp._match_model("activity", models)[0], "activities")

    def test_ies_segment_matches_ies_table(self):
        models = _m("categories", "users")
        self.assertEqual(rp._match_model("categories", models)[0], "categories")

    def test_more_y_ies_nouns(self):
        for sing, plur in (("story", "stories"), ("company", "companies"),
                           ("category", "categories")):
            models = _m(plur, "users")
            self.assertEqual(rp._match_model(sing, models)[0], plur,
                             f"{sing} should match {plur}")

    def test_regular_plural_still_works(self):
        models = _m("videos", "users")
        self.assertEqual(rp._match_model("video", models)[0], "videos")
        self.assertEqual(rp._match_model("videos", models)[0], "videos")

    def test_no_false_match(self):
        # 'day' must NOT match an unrelated table; only a real -ies plural
        models = _m("videos", "users")
        self.assertIsNone(rp._match_model("day", models))

    def test_resource_model_resolves_activity(self):
        models = _m("activities", "users", "videos")
        res = rp._resource_model("/api/activity", models)
        self.assertIsNotNone(res)
        self.assertEqual(res[0], "activities")


if __name__ == "__main__":
    unittest.main()
