"""Tests for runtime/coverage_audit.py (Cutover 19)."""

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
    CoverageReport, compute_coverage, scan_dead_files,
    scan_dead_endpoints, scan_dead_tables,
)


def _write(p: Path, content: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)


class DeadEndpointsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="cov_ep_"))
        self.reg = HubRegistry(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_no_endpoints_returns_empty(self) -> None:
        self.assertEqual(scan_dead_endpoints(self.reg), [])

    def test_endpoint_without_consumer_is_dead(self) -> None:
        self.reg.registryhub.register_endpoint(
            "GET", "/api/feed", schema={}, provider="backend", agent="backend")
        dead = scan_dead_endpoints(self.reg)
        ids = [d["endpoint_id"] for d in dead]
        self.assertEqual(len(ids), 1)
        self.assertIn("GET /api/feed", " ".join(ids) + " " +
                       " ".join(d.get("path", "") for d in dead))

    def test_endpoint_with_consumer_is_not_dead(self) -> None:
        ep = self.reg.registryhub.register_endpoint(
            "GET", "/api/feed", schema={}, provider="backend", agent="backend")
        self.reg.registryhub.register_consumer(
            ep["id"], file_path="frontend/src/api/feed.ts", agent="frontend")
        self.assertEqual(scan_dead_endpoints(self.reg), [])

    def test_deprecated_endpoint_not_flagged_dead(self) -> None:
        self.reg.registryhub.register_endpoint(
            "GET", "/api/old", schema={}, provider="backend", agent="backend",
            status="deprecated")
        self.assertEqual(scan_dead_endpoints(self.reg), [])


class DeadTablesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="cov_tb_"))
        self.reg = HubRegistry(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_no_tables_returns_empty(self) -> None:
        self.assertEqual(scan_dead_tables(self.reg), [])

    def test_table_without_consumer_is_dead(self) -> None:
        self.reg.schema_hub.register_table(
            "notifications", schema={"columns": []},
            provider="backend", agent="backend")
        dead = scan_dead_tables(self.reg)
        self.assertEqual(len(dead), 1)
        self.assertEqual(dead[0]["table"], "notifications")

    def test_table_with_consumer_is_not_dead(self) -> None:
        self.reg.schema_hub.register_table(
            "users", schema={"columns": []},
            provider="backend", agent="backend")
        self.reg.schema_hub.register_table_consumer(
            "users", file_path="backend/routes/auth.py", agent="backend")
        self.assertEqual(scan_dead_tables(self.reg), [])


class DeadFilesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="cov_files_"))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_empty_app_root_returns_empty(self) -> None:
        self.assertEqual(scan_dead_files(self.tmp), [])

    def test_entry_point_not_flagged(self) -> None:
        _write(self.tmp / "frontend/src/main.tsx",
               "import App from './App';\nApp();\n")
        _write(self.tmp / "frontend/src/App.tsx", "export default function App(){}\n")
        # main.tsx is entry; App.tsx is imported -> nothing dead
        self.assertEqual(scan_dead_files(self.tmp), [])

    def test_uninported_component_is_dead(self) -> None:
        _write(self.tmp / "frontend/src/main.tsx",
               "import App from './App';\nApp();\n")
        _write(self.tmp / "frontend/src/App.tsx", "export default function App(){}\n")
        _write(self.tmp / "frontend/src/components/Dead.tsx",
               "export default function Dead(){}\n")
        dead = scan_dead_files(self.tmp)
        dead_paths = [d["path"] for d in dead]
        self.assertEqual(len(dead_paths), 1)
        self.assertTrue(any("Dead.tsx" in p for p in dead_paths))

    def test_imported_component_is_not_dead(self) -> None:
        _write(self.tmp / "frontend/src/main.tsx",
               "import App from './App';\n")
        _write(self.tmp / "frontend/src/App.tsx",
               "import Feed from './components/Feed';\nexport default function App(){}\n")
        _write(self.tmp / "frontend/src/components/Feed.tsx",
               "export default function Feed(){}\n")
        self.assertEqual(scan_dead_files(self.tmp), [])

    def test_test_files_excluded(self) -> None:
        _write(self.tmp / "frontend/src/main.tsx", "export const x = 1;\n")
        _write(self.tmp / "frontend/src/Foo.test.tsx",
               "import Foo from './Foo';\ntest('x', ()=>{});\n")
        _write(self.tmp / "frontend/src/Foo.tsx",
               "export default function Foo(){}\n")
        # Foo.test.tsx is excluded from dead check (test files always exempt)
        # Foo.tsx is imported only by the test, but tests ARE valid consumers
        self.assertEqual(scan_dead_files(self.tmp), [])

    def test_backend_entry_points_not_flagged(self) -> None:
        _write(self.tmp / "backend/server.ts",
               "import { router } from './routes';\nstartServer(router);\n")
        _write(self.tmp / "backend/routes/index.ts",
               "export const router = {};\n")
        self.assertEqual(scan_dead_files(self.tmp), [])

    def test_python_backend_unimported_module_is_dead(self) -> None:
        _write(self.tmp / "backend/app.py",
               "from routes.feed import router\n")
        _write(self.tmp / "backend/routes/__init__.py", "")
        _write(self.tmp / "backend/routes/feed.py", "router = None\n")
        _write(self.tmp / "backend/routes/dead.py", "x = 1\n")
        dead = scan_dead_files(self.tmp)
        self.assertEqual(len(dead), 1)
        self.assertTrue(dead[0]["path"].endswith("dead.py"))


class ComputeCoverageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="cov_full_"))
        self.app_root = self.tmp / "app"
        self.reg = HubRegistry(self.tmp / "hub")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_empty_report_for_clean_setup(self) -> None:
        report = compute_coverage(self.reg, self.app_root)
        self.assertIsInstance(report, CoverageReport)
        self.assertEqual(report.dead_endpoints, [])
        self.assertEqual(report.dead_tables, [])
        self.assertEqual(report.dead_files, [])
        self.assertTrue(report.is_clean)

    def test_aggregates_all_three_categories(self) -> None:
        self.reg.registryhub.register_endpoint(
            "GET", "/api/x", schema={}, provider="backend", agent="backend")
        self.reg.schema_hub.register_table(
            "t", schema={"columns": []}, provider="backend", agent="backend")
        _write(self.app_root / "frontend/src/main.tsx", "x = 1;\n")
        _write(self.app_root / "frontend/src/Dead.tsx", "export const d = 1;\n")
        report = compute_coverage(self.reg, self.app_root)
        self.assertEqual(len(report.dead_endpoints), 1)
        self.assertEqual(len(report.dead_tables), 1)
        self.assertEqual(len(report.dead_files), 1)
        self.assertFalse(report.is_clean)

    def test_all_dead_paths_property(self) -> None:
        self.reg.registryhub.register_endpoint(
            "GET", "/api/x", schema={}, provider="backend", agent="backend")
        _write(self.app_root / "frontend/src/main.tsx", "x = 1;\n")
        _write(self.app_root / "frontend/src/Dead.tsx", "x = 1;\n")
        report = compute_coverage(self.reg, self.app_root)
        paths = report.all_dead_paths
        self.assertIn("endpoint:GET /api/x", paths)
        self.assertTrue(any(p.startswith("file:") and "Dead.tsx" in p for p in paths))


if __name__ == "__main__":
    unittest.main()
