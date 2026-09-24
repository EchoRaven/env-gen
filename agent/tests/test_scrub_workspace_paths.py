"""Guard: PATH FIREWALL — absolute env/worktree roots are stripped from
agent-facing tool output so the model perceives its workspace as ROOT.

youtube run #13: a `read` error echoed the absolute host path
`/data/common/haibotong/forgingground-gen/generated/youtube/registryhub.json`;
the orchestrator LEARNED that path and wrote a `script.py` walking
`/data/common/.../generated/youtube`. Agents must never see absolute host
paths — only workspace-relative ones.
"""

import sys
import unittest
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.agents.runtime.step_pipeline.helpers import (  # noqa: E402
    scrub_workspace_paths,
)

_ENV = "/data/common/haibotong/forgingground-gen/generated/youtube"
_WT = _ENV + "/worktrees/orchestrator"


class ScrubWorkspacePathsTests(unittest.TestCase):
    def test_env_root_stripped_to_relative(self):
        msg = f"read: path not found: {_ENV}/registryhub.json"
        self.assertEqual(
            scrub_workspace_paths(msg, [_ENV]),
            "read: path not found: registryhub.json")
        self.assertNotIn("/data/common", scrub_workspace_paths(msg, [_ENV]))

    def test_worktree_root_wins_over_env_root(self):
        # Longest (most specific) root strips first → tightest relative path.
        msg = f"wrote {_WT}/app/frontend/src/pages/Home.jsx"
        self.assertEqual(
            scrub_workspace_paths(msg, [_ENV, _WT]),
            "wrote app/frontend/src/pages/Home.jsx")

    def test_bare_root_renders_as_dot(self):
        self.assertEqual(scrub_workspace_paths(f"cwd is {_ENV}", [_ENV]), "cwd is .")

    def test_multiple_occurrences(self):
        msg = f"{_ENV}/a.json and {_ENV}/b.json both missing"
        self.assertEqual(
            scrub_workspace_paths(msg, [_ENV]),
            "a.json and b.json both missing")

    def test_no_root_in_text_unchanged(self):
        self.assertEqual(
            scrub_workspace_paths("app/backend/main.py ok", [_ENV]),
            "app/backend/main.py ok")

    def test_empty_or_falsy_roots_ignored(self):
        self.assertEqual(scrub_workspace_paths("x", []), "x")
        self.assertEqual(scrub_workspace_paths("x", ["", None, "/"]), "x")

    def test_non_string_passthrough(self):
        self.assertEqual(scrub_workspace_paths({"a": 1}, [_ENV]), {"a": 1})
        self.assertIsNone(scrub_workspace_paths(None, [_ENV]))

    def test_trailing_slash_root_normalized(self):
        msg = f"{_ENV}/shared/hubs/x.json"
        self.assertEqual(
            scrub_workspace_paths(msg, [_ENV + "/"]), "shared/hubs/x.json")


if __name__ == "__main__":
    unittest.main()
