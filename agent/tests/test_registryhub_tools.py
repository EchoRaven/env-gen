import asyncio
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

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402
from tools.hub_tools import create_hub_tools  # noqa: E402


REQUIRED_TOOLS = {
    "registryhub_register_endpoint",
    "registryhub_update_schema",
    "registryhub_list_endpoints",
    "registryhub_get_endpoint",
    "registryhub_register_consumer",
    "registryhub_get_dependencies_for_file",
    "registryhub_get_breaking_changes",
    "registryhub_record_contract_test",
    "registryhub_deprecate_endpoint",
    "registryhub_register_table",
    "registryhub_list_tables",
    "registryhub_register_table_consumer",
    "registryhub_get_table_breaking_changes",
}


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class RegistryHubToolsTests(unittest.TestCase):
    def _hubs_and_tools(self, td):
        ws = HubRegistry(Path(td))
        tools = create_hub_tools(agent_id="backend", hub_workspace=ws.hubs)
        return ws.hubs, {tool.NAME: tool for tool in tools}

    def test_all_required_registryhub_tools_are_exported(self):
        with tempfile.TemporaryDirectory() as td:
            _, tool_by_name = self._hubs_and_tools(td)
            missing = REQUIRED_TOOLS - set(tool_by_name.keys())
            self.assertEqual(missing, set(), f"missing tools: {missing}")

    def test_registryhub_register_endpoint_tool_writes_through(self):
        with tempfile.TemporaryDirectory() as td:
            hubs, tool_by_name = self._hubs_and_tools(td)
            tool = tool_by_name["registryhub_register_endpoint"]
            result = _run(tool._run(method="GET", path="/api/feed",
                                    schema={"response": {"posts": []}}, provider="backend"))
            self.assertTrue(result.success if hasattr(result, "success") else True)
            self.assertIn("GET /api/feed", hubs.registryhub.get_endpoints())

    def test_registryhub_list_endpoints_tool_returns_dict(self):
        with tempfile.TemporaryDirectory() as td:
            hubs, tool_by_name = self._hubs_and_tools(td)
            hubs.registryhub.register_endpoint("GET", "/api/feed", schema={}, provider="backend", agent="backend")
            tool = tool_by_name["registryhub_list_endpoints"]
            result = _run(tool._run())
            data = result.data if hasattr(result, "data") else result
            self.assertIn("GET /api/feed", data.get("endpoints", data))

    def test_registryhub_deprecate_endpoint_tool_marks_deprecated(self):
        with tempfile.TemporaryDirectory() as td:
            hubs, tool_by_name = self._hubs_and_tools(td)
            hubs.registryhub.register_endpoint("GET", "/api/old", schema={}, provider="backend", agent="backend")
            tool = tool_by_name["registryhub_deprecate_endpoint"]
            result = _run(tool._run(endpoint_id="GET /api/old", replacement_id="GET /api/new"))
            data = result.data if hasattr(result, "data") else result
            self.assertEqual(data.get("status"), "deprecated")

    def test_registryhub_record_contract_test_tool_persists_result(self):
        # Phase 4.4 mechanism proper (commit-pending) added a runtime
        # gate at registryhub.record_api_test that admits {verifier} only.
        # This test exercises the tool wrapper which propagates the
        # bound agent_id into the hub call. Use a verifier-bound
        # tool fixture so the test exercises tool persistence under
        # the actual phase=4.4 production identity rather than the
        # backend-bound default.
        with tempfile.TemporaryDirectory() as td:
            ws = HubRegistry(Path(td))
            tools = create_hub_tools(agent_id="verifier", hub_workspace=ws.hubs)
            hubs = ws.hubs
            tool_by_name = {tool.NAME: tool for tool in tools}
            hubs.registryhub.register_endpoint("GET", "/api/feed", schema={}, provider="backend", agent="backend")
            tool = tool_by_name["registryhub_record_contract_test"]
            _run(tool._run(
                endpoint_id="GET /api/feed",
                result={"passed": True, "duration_ms": 12},
                evidence={"trace": "200 OK"},
            ))
            tests = hubs.registryhub.snapshot()["contract_tests"]
            self.assertEqual(len(tests), 1)


if __name__ == "__main__":
    unittest.main()
