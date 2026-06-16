"""Tests that backend + frontend prompts teach MCP registration discipline."""

import unittest
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
PROMPTS_V3 = AGENT_DIR / "env_generator" / "llm_generator" / "multi_agent" / "prompts" / "v3"
PROMPTS_ROOT = PROMPTS_V3.parent


def _render(tpl_name: str, macros: list) -> str:
    env = Environment(loader=FileSystemLoader([str(PROMPTS_V3), str(PROMPTS_ROOT)]))
    tpl = env.get_template(tpl_name)
    mod = tpl.make_module()
    for name in macros:
        if hasattr(mod, name):
            try:
                return getattr(mod, name)()
            except TypeError:
                return getattr(mod, name)(".", "")
    raise RuntimeError(f"no macro found in {tpl_name}")


class BackendMCPPromptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.system = _render("backend_agent.j2",
                              ["backend_specifics", "backend_system_prompt"])

    def test_mentions_mcp_register_server(self) -> None:
        self.assertIn("MCP_REGISTRY_REGISTER_SERVER", self.system.upper())

    def test_mentions_mcp_register_tool(self) -> None:
        self.assertIn("MCP_REGISTRY_REGISTER_TOOL", self.system.upper())

    def test_mentions_transport_options(self) -> None:
        upper = self.system.upper()
        self.assertIn("STDIO", upper)
        self.assertIn("HTTP", upper)


class FrontendMCPPromptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.system = _render("frontend_agent.j2",
                              ["frontend_specifics", "frontend_system_prompt"])

    def test_mentions_mcp_register_consumer(self) -> None:
        self.assertIn("MCP_REGISTRY_REGISTER_CONSUMER", self.system.upper())


if __name__ == "__main__":
    unittest.main()
