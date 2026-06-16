"""Guard: a frontend kickoff part counts as substance for ALL first-class
declarations (ui_pages / screens / user_flows / ui_components), not only
ui_pages/screens.

Bug it pins: the frontend legitimately submits its section in parts (the guard's
own message says "SUBMIT IN PARTS"). A `user_flows`-only part sent via the generic
workhub_add_meeting_decision tool was rejected as "NO substantive content" — even
though user_flows is a first-class frontend declaration (dedicated
kickoff_declare_user_flow tool). That rejection + its misleading "mangled/empty"
message is what sent the orchestrator into bash-based kickoff recovery. Empty
shells / null skeletons must STILL read as no-substance.
"""

import sys
import unittest
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.kickoff.section_substance import (  # noqa: E402
    section_has_substance, decision_has_substance,
)


class FrontendSubstanceTests(unittest.TestCase):
    def test_user_flows_only_is_substance(self):
        c = {"user_flows": [{"id": "auth_login", "description": "log in", "critical": True}]}
        self.assertTrue(section_has_substance(c, "frontend"))

    def test_ui_components_only_is_substance(self):
        c = {"ui_components": [{"id": "video_card", "component": "VideoCard"}]}
        self.assertTrue(section_has_substance(c, "frontend"))

    def test_ui_pages_still_substance(self):
        self.assertTrue(section_has_substance({"ui_pages": [{"id": "home", "route": "/"}]}, "frontend"))

    def test_empty_shell_is_not_substance(self):
        # The race-guard the check exists for: empty lists / null skeletons must NOT pass.
        self.assertFalse(section_has_substance({"ui_pages": [], "user_flows": []}, "frontend"))
        self.assertFalse(section_has_substance({"user_flows": [None, None]}, "frontend"))

    def test_metadata_only_is_not_substance(self):
        # auth_model/done_def alone (no pages/flows/components) is thin metadata, not buildable content.
        self.assertFalse(section_has_substance({"auth_model": "jwt_bearer", "done_def": ["x"]}, "frontend"))

    def test_decision_wrapper_shapes(self):
        # Both the {"section","content":{...}} and flat shapes resolve a user_flows part.
        nested = {"section": "frontend", "content": {"user_flows": [{"id": "f1", "description": "d"}]}}
        self.assertTrue(decision_has_substance(nested, "frontend"))
        flat = {"section": "frontend", "user_flows": [{"id": "f1", "description": "d"}]}
        self.assertTrue(decision_has_substance(flat, "frontend"))

    def test_backend_and_verifier_unchanged(self):
        self.assertTrue(section_has_substance({"endpoints": [{"path": "/api/x", "method": "GET"}]}, "backend"))
        self.assertFalse(section_has_substance({"user_flows": [{"id": "f"}]}, "backend"))  # not a backend key
        self.assertTrue(section_has_substance({"predicates": [{"id": "p", "description": "d"}]}, "verifier"))


if __name__ == "__main__":
    unittest.main()
