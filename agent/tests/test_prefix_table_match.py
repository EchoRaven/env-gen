"""Guard: FIX #205 — resolve a shorthand path segment to a `<seg>_<...>` table.

r13 live (furthest run — business_chain passed, follow works): 2 residual
stubs. One is GET /api/live ↔ table `live_streams` — 'live' is a shorthand
prefix of 'live_streams' (live + '_streams'), which #200's suffix match and the
+s/-s/-ies plurals don't cover. Resolve a segment to the UNIQUE table named
`<segment>_<something>` (underscore boundary required, uniqueness required) so
the LIVE page reads real rows instead of shipping an empty stub → #173 wall.
(The other residual, /api/creators/suggested, is an AGGREGATE/computed endpoint
with no plain table — out of scope; the user's #173 HARD-vs-SOFT call.)
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


class PrefixMatchTests(unittest.TestCase):
    def test_live_resolves_to_live_streams(self):
        res = rp._resource_model("/api/live", _m("live_streams", "users", "videos"))
        self.assertIsNotNone(res)
        self.assertEqual(res[0], "live_streams")

    def test_ambiguous_prefix_stays_none(self):
        # two `live_*` tables → ambiguous → don't guess
        res = rp._resource_model("/api/live", _m("live_streams", "live_events", "users"))
        self.assertIsNone(res)

    def test_exact_still_preferred(self):
        # a `live` table wins over `live_streams`
        res = rp._resource_model("/api/live", _m("live", "live_streams", "users"))
        self.assertEqual(res[0], "live")

    def test_requires_underscore_boundary(self):
        # 'cat' must NOT prefix-match 'category' (no '_' after cat) — only a real
        # <seg>_<...> compound qualifies, so a substring can't spuriously hit.
        res = rp._resource_model("/api/cat", _m("category", "users"))
        self.assertIsNone(res)

    def test_plain_paths_unchanged(self):
        models = _m("videos", "users", "live_streams")
        self.assertEqual(rp._resource_model("/api/videos", models)[0], "videos")


if __name__ == "__main__":
    unittest.main()
