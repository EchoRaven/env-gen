"""STRUCTURAL guard (2026-06-19): App.jsx is the framework-owned router/entry point,
so a ui_page may NOT be named `App` (nor the react-router idents). An agent that
registers such a page is rejected at the source (it must rename) — otherwise the
projected router redeclares `App` and the whole frontend build fails. The
orchestrator's kickoff-finalize path is left to pass (the projector aliases as a
backstop) so finalization can't crash.
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


class ReservedUiPageNameGuard(unittest.TestCase):
    def setUp(self):
        from multi_agent.runtime.hub_registry import HubRegistry
        self._td = tempfile.mkdtemp()
        self.reg = HubRegistry(Path(self._td)).registryhub

    def test_agent_cannot_register_App_page(self):
        with self.assertRaises(ValueError) as cm:
            self.reg.register_ui_page(name="App", component="App", route="/app", agent="frontend")
        self.assertIn("RESERVED", str(cm.exception))

    def test_router_idents_rejected(self):
        for n in ("Routes", "Route", "React", "BrowserRouter"):
            with self.assertRaises(ValueError):
                self.reg.register_ui_page(name=n, component=n, route="/x", agent="frontend")

    def test_descriptive_name_ok(self):
        rec = self.reg.register_ui_page(name="NotesAppPage", component="NotesAppPage",
                                        route="/", agent="frontend")
        self.assertEqual(rec.get("component"), "NotesAppPage")

    def test_orchestrator_finalize_not_rejected(self):
        # finalize must NOT raise — the projector's reserved-name alias is the backstop.
        rec = self.reg.register_ui_page(name="App", component="App", route="/app",
                                        agent="orchestrator")
        self.assertTrue(rec)


if __name__ == "__main__":
    unittest.main()
