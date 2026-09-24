"""docker_up build-context readiness gate (B3).

Smoke #4: the verifier ran docker_up(build=True) ~2.5 min in — before the
backend lane had merged its Dockerfile — so compose's `build: ../app/backend`
fast-failed. The orchestrator then misdiagnosed this transient "artifact not
ready yet" as a real "missing backend Dockerfile" code defect and assigned a
bogus remediation, and the verifier gave up without retrying.

``_missing_build_contexts`` lets docker_up distinguish "build context not
present yet" (defer + retry) from a genuine build/runtime failure, so a
premature validation defers cleanly instead of derailing the run.
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path


def _reset_event_loop():
    # asyncio.run() closes the global loop; leave a fresh open one so later
    # async tests in the suite don't inherit a closed loop.
    try:
        asyncio.set_event_loop(asyncio.new_event_loop())
    except Exception:
        pass

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))

COMPOSE = """version: '3.8'
services:
  database:
    build: ../app/database
  backend:
    build: ../app/backend
  frontend:
    build: ../app/frontend
  cache:
    image: redis:7
"""


def _scaffold(tmp: Path, present: list) -> Path:
    """Write a compose file + Dockerfiles for the named services; return the
    compose file path."""
    (tmp / "docker").mkdir(parents=True, exist_ok=True)
    compose = tmp / "docker" / "docker-compose.yml"
    compose.write_text(COMPOSE)
    for svc in present:
        d = tmp / "app" / svc
        d.mkdir(parents=True, exist_ok=True)
        (d / "Dockerfile").write_text("FROM scratch\n")
    return compose


class MissingBuildContextsTests(unittest.TestCase):
    def test_reports_services_with_missing_dockerfile(self):
        from tools.docker_tools import _missing_build_contexts  # noqa
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            compose = _scaffold(tmp, present=["database"])  # backend+frontend missing
            missing = _missing_build_contexts(compose)
            self.assertIn("backend", missing)
            self.assertIn("frontend", missing)
            self.assertNotIn("database", missing)
            self.assertNotIn("cache", missing)  # image-only service, no build

    def test_empty_when_all_present(self):
        from tools.docker_tools import _missing_build_contexts
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            compose = _scaffold(tmp, present=["database", "backend", "frontend"])
            self.assertEqual(_missing_build_contexts(compose), [])

    def test_service_filter_scopes_the_check(self):
        from tools.docker_tools import _missing_build_contexts
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            compose = _scaffold(tmp, present=["database"])
            # Only checking 'database' (present) → no missing, even though
            # backend/frontend are absent.
            self.assertEqual(_missing_build_contexts(compose, service="database"), [])
            self.assertEqual(_missing_build_contexts(compose, service="backend"), ["backend"])


class DockerUpReadinessWiringTests(unittest.TestCase):
    def tearDown(self):
        _reset_event_loop()

    def _make_tool(self, base_root: Path):
        import types
        from tools.docker_tools import DockerUpTool
        ws = types.SimpleNamespace(base_root=base_root)
        return DockerUpTool(workspace=ws)

    def test_execute_returns_not_ready_when_build_context_missing(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            _scaffold(tmp, present=["database"])  # backend/frontend Dockerfiles absent
            tool = self._make_tool(tmp)
            result = asyncio.run(tool.execute(build=True))
            self.assertFalse(result.success)
            self.assertTrue(result.metadata.get("not_ready"))
            self.assertIn("VALIDATION_NOT_READY", result.error_message)
            self.assertIn("backend", result.metadata.get("missing_build_contexts", []))


class DockerUpFreshVolumeTests(unittest.TestCase):
    """smoke #5: a sandbox env must boot from a clean DB. A full-env docker_up
    tears down volumes first (down -v) so a stale postgres volume can't ignore
    POSTGRES_PASSWORD on re-init → false 'password authentication failed' on a
    correct app."""

    def tearDown(self):
        _reset_event_loop()

    def _make_tool(self, base_root):
        import types
        from tools.docker_tools import DockerUpTool
        return DockerUpTool(workspace=types.SimpleNamespace(base_root=base_root))

    def _run_recorded(self, tmp, **kw):
        import tools.docker_tools as dt

        calls = []

        class _R:
            returncode = 0
            stderr = ""
            stdout = ""

        orig = dt._run_compose
        dt._run_compose = lambda compose_file, args, **k: (calls.append(list(args)) or _R())
        try:
            result = asyncio.run(self._make_tool(tmp).execute(**kw))
        finally:
            dt._run_compose = orig
        return result, calls

    def test_full_boot_tears_down_volumes_before_up(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            _scaffold(tmp, present=["database", "backend", "frontend"])
            result, calls = self._run_recorded(tmp)
            self.assertTrue(result.success, getattr(result, "error_message", ""))
            self.assertEqual(calls[0], ["down", "-v", "--remove-orphans"])
            self.assertIn("up", calls[1])

    def test_fresh_false_preserves_volumes(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            _scaffold(tmp, present=["database", "backend", "frontend"])
            result, calls = self._run_recorded(tmp, fresh=False)
            self.assertTrue(result.success)
            self.assertNotIn(["down", "-v", "--remove-orphans"], calls)
            self.assertIn("up", calls[0])


if __name__ == "__main__":
    unittest.main()
