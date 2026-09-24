"""#1202fe: the framework-owned refusal must name where SEED ROWS go.

#661's empty-state reminder tells the backend, verbatim, to "Add realistic seed
rows (>=3) ... to app/backend/seed_data.json". netflix-r41 (live) shows the lane
trying to obey by editing seed_data.PY -- framework-owned -- being denied, and
being redirected to custom_routes.py, where seed rows do not go.

That closes a loop the run cannot escape: thin seeds are what #661 blames for
empty-state screens (17% of failing visual judgments in the current corpus, none
of which has ever cleared the bar). The answer existed in another module.
"""
import sys
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent))
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

from multi_agent.runtime.path_routed_workspace import (  # noqa: E402
    path_is_lane_owned_1202cw,
)

TOOLING = (THIS_DIR.parent / "env_generator" / "llm_generator" / "multi_agent"
           / "agents" / "runtime" / "tooling.py").read_text(encoding="utf-8")
VISUAL = (THIS_DIR.parent / "env_generator" / "llm_generator" / "multi_agent"
          / "runtime" / "visual_fidelity.py").read_text(encoding="utf-8")


def _refusal_text():
    i = TOOLING.index("are FRAMEWORK-OWNED files")
    return TOOLING[i:TOOLING.index("),", i)]


class TestRefusalNamesTheSeedFile(unittest.TestCase):

    def test_the_refusal_names_seed_data_json(self):
        self.assertIn("seed_data.json", _refusal_text())

    def test_it_still_names_the_other_two_destinations(self):
        """The seed clause is an addition, not a replacement."""
        t = _refusal_text()
        self.assertIn("custom_routes.py", t)
        self.assertIn("registryhub_", t)

    def test_the_file_it_names_is_actually_writable_by_a_lane(self):
        """Directing a lane at a second denied path would be worse than silence."""
        self.assertTrue(path_is_lane_owned_1202cw(Path("app/backend/seed_data.json")))
        self.assertFalse(path_is_lane_owned_1202cw(Path("app/backend/seed_data.py")),
                         "seed_data.py is the framework-owned one the lane tried")

    def test_it_agrees_with_the_file_661_asks_for(self):
        """Two modules telling a lane two different files is how r41 got stuck."""
        # Landmark-anchored, not a fixed window (#943): the block ends where the task
        # is actually created, and a byte count would drift with every edit above it.
        i = VISUAL.index("#661: NAME THE TABLES")
        asks = VISUAL[i:VISUAL.index("create_task", i)]
        self.assertIn("seed_data.json", asks)
        self.assertIn("seed_data.json", _refusal_text())


if __name__ == "__main__":
    unittest.main()
