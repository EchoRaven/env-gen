"""DECOMPOSITION #3 (PROPOSAL #8 — Scaffolder): the 9 deterministic-scaffolding
methods moved from the Orchestrator into runtime.scaffolder.Scaffolder. Pins the
shim delegation (all 9), the lazy _scaffolder property, and a functional smoke
that the moved bodies still run (docker-compose + README produced).

LOCAL-ONLY (agent/tests/ is gitignored per repo policy) — run for verification.
"""

import asyncio
import logging
import sys
import types
import unittest
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.scaffolder import Scaffolder  # noqa: E402


def run(coro):
    return asyncio.run(coro)


_SHIMS = {
    "_generate_docker": ("generate_docker", True),
    "_generate_database": ("generate_database", True),
    "_generate_backend_skeleton": ("generate_backend_skeleton", False),
    "_seed_base_scaffold": ("seed_base_scaffold", True),
    "_register_contract_surface": ("register_contract_surface", False),
    "_generate_mcp": ("generate_mcp", True),
    "_scaffold_design_readme": ("scaffold_design_readme", False),
    "_scaffold_frontend_baseline": ("scaffold_frontend_baseline", False),
    "_scaffold_frontend_pages": ("scaffold_frontend_pages", False),
}


class ShimDelegationTests(unittest.TestCase):
    def test_lazy_scaffolder_cached(self):
        from multi_agent.orchestrator import Orchestrator
        o = object.__new__(Orchestrator)
        s = o._scaffolder
        self.assertIsInstance(s, Scaffolder)
        self.assertIs(s, o._scaffolder)   # cached in __dict__

    def test_all_nine_shims_delegate(self):
        from multi_agent.orchestrator import Orchestrator
        for shim, (target, is_async) in _SHIMS.items():
            o = object.__new__(Orchestrator)
            calls = []

            class FakeScaffolder:
                pass
            fake = FakeScaffolder()
            # bind a recorder for the target (async or sync to match the shim)
            if is_async:
                async def _rec(*a, _t=target, **k):
                    calls.append(_t)
                setattr(fake, target, _rec)
            else:
                setattr(fake, target, lambda *a, _t=target, **k: calls.append(_t))
            o.__dict__["_scaffolder_instance"] = fake
            meth = getattr(o, shim)
            if is_async:
                run(meth())
            else:
                meth()
            self.assertEqual(calls, [target], f"{shim} should delegate to {target}")


class FunctionalSmokeTests(unittest.TestCase):
    def _orch(self, tmp):
        o = types.SimpleNamespace()
        o.output_dir = Path(tmp)
        o._logger = logging.getLogger("t")
        o.context = types.SimpleNamespace(
            db_port=15432, backend_internal_port=8081, api_port=18081, ui_port=15173)
        o.hubs = types.SimpleNamespace(registryhub=None)
        return o

    def test_generate_docker_writes_compose_with_ports(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            sc = Scaffolder(self._orch(tmp))
            run(sc.generate_docker())
            compose = Path(tmp) / "docker" / "docker-compose.yml"
            self.assertTrue(compose.exists())
            txt = compose.read_text()
            self.assertIn("15432", txt)   # db_port
            self.assertIn("18081:8081", txt)  # api_port:backend_internal_port
            self.assertIn("postgres:16", txt)

    def test_scaffold_design_readme_writes_when_missing(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            sc = Scaffolder(self._orch(tmp))
            sc.scaffold_design_readme()
            readme = Path(tmp) / "design" / "README.md"
            self.assertTrue(readme.exists())
            self.assertIn("docker compose up", readme.read_text())

    def test_scaffold_design_readme_idempotent_keeps_existing(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            readme = Path(tmp) / "design" / "README.md"
            readme.parent.mkdir(parents=True)
            readme.write_text("EXISTING CONTENT")
            sc = Scaffolder(self._orch(tmp))
            sc.scaffold_design_readme()
            self.assertEqual(readme.read_text(), "EXISTING CONTENT")  # not clobbered


if __name__ == "__main__":
    unittest.main()
