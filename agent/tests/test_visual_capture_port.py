"""Guard: FIX #207 — the visual gate must NEVER screenshot a fixed :8080/:3001
fallback (a persistent gmaps demo runs there).

r13 (furthest TikTok run) scored its visual fidelity against a GOOGLE MAPS
sign-in page — because `fe_port = _service_host_port(...) or 8080` fell back to
:8080 (the run-9 gmaps demo, docker-frontend-1) when the app's own frontend port
wasn't `docker compose ps`-visible yet (resolution ran BEFORE the readiness
wait). So the gate screenshotted the wrong app and compared it to THIS env's
TikTok references → a meaningless ~0 score, the real cause of the "visual never
passes" plateau on non-gmaps envs. The resolver must return the app's OWN port
or None (→ honest skip), never a magic constant.
"""

import sys
import unittest
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.visual_fidelity import _resolve_app_port  # noqa: E402


class ResolveAppPortTests(unittest.TestCase):
    def test_returns_first_resolved_service_port(self):
        calls = []

        def _r(svc):
            calls.append(svc)
            return {"frontend": 34567}.get(svc)

        self.assertEqual(_resolve_app_port(_r, ("frontend", "ui")), 34567)

    def test_falls_through_service_names(self):
        def _r(svc):
            return {"ui": 41000}.get(svc)  # 'frontend' unresolved, 'ui' resolves

        self.assertEqual(_resolve_app_port(_r, ("frontend", "ui")), 41000)

    def test_none_when_unresolved_NEVER_8080(self):
        # THE FIX: no service resolves → None (honest skip), NOT a magic :8080.
        self.assertIsNone(_resolve_app_port(lambda s: None, ("frontend", "ui")))

    def test_resolver_exception_is_none_not_fallback(self):
        def _boom(svc):
            raise RuntimeError("docker not ready")
        self.assertIsNone(_resolve_app_port(_boom, ("frontend", "ui")))

    def test_zero_or_falsy_port_treated_as_unresolved(self):
        self.assertIsNone(_resolve_app_port(lambda s: 0, ("frontend",)))


if __name__ == "__main__":
    unittest.main()
