"""Stub shape honors the declared response_key (youtube run #16, 2026-06-20):

GET /api/auth/me has no resolvable model ("auth" has no table), so the projector
fell through to the COLLECTION stub `{"items": [], "total": 0}` — but the contract
declared response_key='item'. The business_endpoints_correct_shape gate then failed
forever ("returns a list but the contract is a single item") → STUCK-ABORT. The
non-param GET stub must emit the shape the contract declares.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from multi_agent.runtime.route_projector import _generate_handler  # noqa: E402


class ProjectorStubResponseKeyTests(unittest.TestCase):
    def test_non_param_get_item_key_stubs_single(self):
        src = _generate_handler("GET", "/api/auth/me", True, {}, 0, "item")
        self.assertIn('return {"item": {}}', src)
        self.assertNotIn('"items"', src)

    def test_non_param_get_items_key_stubs_collection(self):
        src = _generate_handler("GET", "/api/videos", True, {}, 1, "items")
        self.assertIn('return {"items": [], "total": 0}', src)

    def test_non_param_get_no_response_key_defaults_collection(self):
        # backward-compatible: absent response_key keeps the prior collection shape
        src = _generate_handler("GET", "/api/feed", True, {}, 2, "")
        self.assertIn('return {"items": [], "total": 0}', src)

    def test_param_get_unchanged_single_resource(self):
        # a parameterized GET with no model still 404s (single-resource by contract)
        src = _generate_handler("GET", "/api/widgets/{widgetId}", True, {}, 3, "item")
        self.assertIn("status_code=404", src)


if __name__ == "__main__":
    unittest.main()
