"""#1132: "find the include_router that was never added" is one of three fixes, asserted as the only one.

`_declared_but_unmounted_952` compares BACKEND SOURCE against the LIVE openapi. That
comparison sees exactly one thing: the source declares a route and the running app does not
serve it. #952 then asserted a cause — "This is not 'not built yet' — the handler exists and
cannot be reached; find the include_router that was never added" — which the comparison has no
way to establish. Three situations are indistinguishable from there:

    1. the router was never included (the r154 case #952 was written for);
    2. main.py's custom-routes duplicate filter DROPPED the route, logging its refusal to the
       `custom_routes` logger INSIDE the container, where no lane can see it (#1102 measured
       98 legitimate lane routes dropped across 57 runs, "invisible for hours");
    3. the running container predates the handler — nothing here measures build currency.

netflix-local-r1: 112 of these over 1h38m, all for one handler
(DELETE /api/v1/tenants/{tenant_id}). It entered custom_routes.py at 13:29:13, a build
succeeded at 13:36:22, the first warning landed at 13:36:36, and the stack cycled 80 up /
102 down throughout. A lane was told 112 times to apply the fix for cause (1).

Same lesson as #1114 and #1023: report the evidence, never assert the verdict.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))

from multi_agent.runtime import chain_executor  # noqa: E402

CHAIN_SRC = (ROOT / "env_generator" / "llm_generator" / "multi_agent" / "runtime"
             / "chain_executor.py")


def _project_with(route_src: str) -> str:
    """A minimal project tree whose backend declares one route."""
    root = Path(tempfile.mkdtemp())
    be = root / "app" / "backend"
    be.mkdir(parents=True)
    (be / "custom_routes.py").write_text(route_src, encoding="utf-8")
    return str(root)


class TheDetectionStillWorks(unittest.TestCase):
    """#1132 changes the WORDING, not the finding. The finding must survive."""

    def test_a_declared_route_the_app_does_not_serve_is_still_reported(self):
        proj = _project_with(
            '@router.delete("/api/v1/tenants/{tenant_id}")\ndef d(): ...\n')
        out = chain_executor._declared_but_unmounted_952(
            proj, [{"kind": "missing", "method": "DELETE",
                    "path": "/api/v1/tenants/tenant_0"}], "http://localhost:8000")
        self.assertEqual(len(out), 1, out)
        self.assertEqual(out[0]["method"], "DELETE")
        self.assertIn("custom_routes.py", str(out[0]["declared_in"]))

    def test_a_route_nothing_declares_is_not_reported(self):
        proj = _project_with('@router.get("/api/titles")\ndef g(): ...\n')
        out = chain_executor._declared_but_unmounted_952(
            proj, [{"kind": "missing", "method": "DELETE",
                    "path": "/api/v1/tenants/tenant_0"}], "http://localhost:8000")
        self.assertEqual(out, [])


class TheMessageNoLongerPicksOneCause(unittest.TestCase):

    def setUp(self):
        self.src = CHAIN_SRC.read_text(encoding="utf-8")
        i = self.src.index("#952 DECLARED BUT UNMOUNTED: a chain calls")
        self.msg = self.src[i:self.src.index('_u["method"]', i)]

    def test_the_unsupported_assertion_is_gone(self):
        self.assertNotIn("This is not 'not built yet'", self.msg)
        self.assertNotIn("the handler exists and cannot be reached", self.msg)

    def test_all_three_causes_are_named(self):
        self.assertIn("include_router", self.msg)          # (1)
        self.assertIn("custom_routes", self.msg)           # (2) the in-container logger
        self.assertIn("predates", self.msg)                # (3) build currency

    def test_it_says_where_the_invisible_evidence_is(self):
        """Cause (2)'s refusal is logged only inside the container — say so, or it is lost."""
        self.assertIn("container log", self.msg)

    def test_it_admits_what_it_cannot_measure(self):
        self.assertIn("build currency", self.msg)


if __name__ == "__main__":
    unittest.main()
