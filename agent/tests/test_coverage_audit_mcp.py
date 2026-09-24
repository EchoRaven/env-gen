"""Tests for coverage_audit MCP extension (Cutover 22)."""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402
from multi_agent.runtime.coverage_audit import (  # noqa: E402
    compute_coverage, scan_dead_mcp_tools, scan_empty_mcp_servers,
    scan_pages_without_files,
)


class DeadMCPToolsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="cov_mcp_"))
        self.reg = HubRegistry(self.tmp)
        self.reg.mcp_registry.register_mcp_server(
            name="filesystem", transport="stdio", endpoint="./fs",
            provider="backend", agent="backend")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_no_tools_returns_empty(self) -> None:
        self.assertEqual(scan_dead_mcp_tools(self.reg), [])

    def test_tool_with_no_consumer_is_dead(self) -> None:
        self.reg.mcp_registry.register_mcp_tool(
            server_name="filesystem", tool_name="read_file",
            schema={}, provider="backend", agent="backend")
        dead = scan_dead_mcp_tools(self.reg)
        self.assertEqual(len(dead), 1)
        self.assertEqual(dead[0]["server"], "filesystem")
        self.assertEqual(dead[0]["tool"], "read_file")

    def test_tool_with_consumer_not_dead(self) -> None:
        self.reg.mcp_registry.register_mcp_tool(
            server_name="filesystem", tool_name="read_file",
            schema={}, provider="backend", agent="backend")
        self.reg.mcp_registry.register_mcp_consumer(
            server_name="filesystem", tool_name="read_file",
            file_path="frontend/src/api/fs.ts", agent="frontend")
        self.assertEqual(scan_dead_mcp_tools(self.reg), [])

    def test_compute_coverage_includes_dead_mcp_tools(self) -> None:
        self.reg.mcp_registry.register_mcp_tool(
            server_name="filesystem", tool_name="read_file",
            schema={}, provider="backend", agent="backend")
        tmp_app = Path(self.tmp) / "app"
        tmp_app.mkdir()
        (tmp_app / "main.tsx").write_text("x = 1;\n")
        report = compute_coverage(self.reg, tmp_app)
        self.assertEqual(len(report.dead_mcp_tools), 1)
        self.assertFalse(report.is_clean)
        paths = report.all_dead_paths
        self.assertIn("mcp_tool:filesystem:read_file", paths)


class EmptyMCPServerTests(unittest.TestCase):
    """A registered MCP server with zero tools is an incomplete
    construction — the verifier should be able to flag it."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="cov_mcp_empty_"))
        self.reg = HubRegistry(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_server_without_tools_is_empty(self) -> None:
        self.reg.mcp_registry.register_mcp_server(
            name="filesystem", transport="stdio", endpoint="./fs",
            provider="backend", agent="backend",
        )
        empties = scan_empty_mcp_servers(self.reg)
        self.assertEqual(len(empties), 1)
        self.assertEqual(empties[0]["server"], "filesystem")

    def test_server_with_at_least_one_tool_not_empty(self) -> None:
        self.reg.mcp_registry.register_mcp_server(
            name="filesystem", transport="stdio", endpoint="./fs",
            provider="backend", agent="backend",
        )
        self.reg.mcp_registry.register_mcp_tool(
            server_name="filesystem", tool_name="read_file",
            schema={}, provider="backend", agent="backend",
        )
        self.assertEqual(scan_empty_mcp_servers(self.reg), [])

    def test_compute_coverage_marks_empty_servers_unclean(self) -> None:
        self.reg.mcp_registry.register_mcp_server(
            name="filesystem", transport="stdio", endpoint="./fs",
            provider="backend", agent="backend",
        )
        tmp_app = Path(self.tmp) / "app"
        tmp_app.mkdir()
        (tmp_app / "main.tsx").write_text("x = 1;\n")
        report = compute_coverage(self.reg, tmp_app)
        self.assertEqual(len(report.empty_mcp_servers), 1)
        self.assertFalse(report.is_clean)
        self.assertIn("mcp_server:filesystem", report.all_dead_paths)


class PagesWithoutFilesTests(unittest.TestCase):
    """registryhub_register_ui_page(path=...) should map to an actual file on
    disk. A missing file means the agent registered a phantom page."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="cov_pages_"))
        self.reg = HubRegistry(self.tmp)
        self.app_root = self.tmp / "app"
        self.app_root.mkdir()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_no_pages_returns_empty(self) -> None:
        self.assertEqual(scan_pages_without_files(self.reg, self.app_root), [])

    def test_page_with_missing_file_is_flagged(self) -> None:
        self.reg.workhub.update_ui_page(
            "Login",
            {"path": "frontend/src/pages/Login.jsx", "status": "implemented"},
            agent="frontend",
        )
        ghosts = scan_pages_without_files(self.reg, self.app_root)
        self.assertEqual(len(ghosts), 1)
        self.assertEqual(ghosts[0]["declared_path"], "frontend/src/pages/Login.jsx")

    def test_page_with_existing_file_is_not_flagged(self) -> None:
        (self.app_root / "frontend" / "src" / "pages").mkdir(parents=True)
        (self.app_root / "frontend" / "src" / "pages" / "Login.jsx").write_text("export default()=>null")
        self.reg.workhub.update_ui_page(
            "Login",
            {"path": "frontend/src/pages/Login.jsx", "status": "implemented"},
            agent="frontend",
        )
        self.assertEqual(scan_pages_without_files(self.reg, self.app_root), [])

    def test_page_without_path_field_is_silently_ignored(self) -> None:
        """A page registered without a path is a design-phase placeholder."""
        self.reg.workhub.update_ui_page(
            "Login",
            {"status": "defined"},
            agent="frontend",
        )
        self.assertEqual(scan_pages_without_files(self.reg, self.app_root), [])

    def test_compute_coverage_marks_phantom_pages_unclean(self) -> None:
        self.reg.workhub.update_ui_page(
            "Login",
            {"path": "frontend/src/pages/Login.jsx", "status": "implemented"},
            agent="frontend",
        )
        # add a real source file so dead_files-by-itself doesn't dominate
        (self.app_root / "main.tsx").write_text("x=1")
        report = compute_coverage(self.reg, self.app_root)
        self.assertEqual(len(report.pages_without_files), 1)
        self.assertFalse(report.is_clean)
        self.assertTrue(
            any(p.startswith("page:") for p in report.all_dead_paths),
            f"Expected a page:* entry in {report.all_dead_paths}",
        )


if __name__ == "__main__":
    unittest.main()
