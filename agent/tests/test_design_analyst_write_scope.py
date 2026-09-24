"""The one-shot design_analyst OWNS design/design_system.json + design/crops/ — it MUST be a
writer on the design/ route, else the write-scope gate fails closed and the whole measure-per-
component phase silently produces nothing. Regression for the routing-table entry. LOCAL-ONLY.
"""

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.path_routed_workspace import PathRoutedWorkspace  # noqa: E402


class DesignAnalystWriteScope(unittest.TestCase):
    def _ws(self, who):
        # SEPARATE base/code roots — else design/ resolves into the code-root worktree and the
        # "agent owns its worktree → True" rule masks the design/ route's writer gate.
        base = tempfile.mkdtemp()
        code = tempfile.mkdtemp()
        return PathRoutedWorkspace(base_root=base, code_root=code, agent_id=who)

    def test_design_analyst_can_write_design_system_and_crops(self):
        ws = self._ws("design_analyst")
        self.assertTrue(ws.is_write_allowed("design/design_system.json", "design_analyst"))
        self.assertTrue(ws.is_write_allowed("design/design_system.md", "design_analyst"))
        self.assertTrue(ws.is_write_allowed("design/crops/home__nav.png", "design_analyst"))
        self.assertTrue(ws.is_write_allowed("design/component_specs/home.json", "design_analyst"))

    def test_design_route_still_gated_for_a_random_agent(self):
        # the route stays an allowlist — an unlisted agent id is still denied (fail-closed)
        ws = self._ws("api_test_user")
        self.assertFalse(ws.is_write_allowed("design/design_system.json", "api_test_user"))


if __name__ == "__main__":
    unittest.main()
