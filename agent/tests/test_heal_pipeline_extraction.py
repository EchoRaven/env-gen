"""DECOMPOSITION #5 (PROPOSAL #8 — HealPipeline): the 12 delivery-time
repair/merge/commit steps moved from the Orchestrator into
runtime.heal_pipeline.HealPipeline. Pins: (a) two repairs run end-to-end through
their re-pathed inline imports (entrypoint append + AS wiring), and (b) the
orchestrator shim delegates on a bare stub (fresh-construct, unbound-on-stub).

LOCAL-ONLY (agent/tests/ is gitignored per repo policy) — run for verification.
"""

import logging
import sys
import tempfile
import types
import unittest
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.heal_pipeline import HealPipeline  # noqa: E402


def _orch(tmp):
    return types.SimpleNamespace(output_dir=Path(tmp), _logger=logging.getLogger("t"))


class FunctionalTests(unittest.TestCase):
    def test_repair_backend_entrypoint_appends_uvicorn(self):
        with tempfile.TemporaryDirectory() as tmp:
            be = Path(tmp) / "app" / "backend"
            be.mkdir(parents=True)
            (be / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n")
            HealPipeline(_orch(tmp)).repair_backend_entrypoint()
            src = (be / "main.py").read_text()
            self.assertIn("uvicorn.run", src)
            self.assertIn('__main__', src)

    def test_repair_backend_entrypoint_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            be = Path(tmp) / "app" / "backend"
            be.mkdir(parents=True)
            original = ('from fastapi import FastAPI\napp = FastAPI()\n'
                        'if __name__ == "__main__":\n    import uvicorn\n'
                        '    uvicorn.run(app)\n')
            (be / "main.py").write_text(original)
            HealPipeline(_orch(tmp)).repair_backend_entrypoint()
            self.assertEqual((be / "main.py").read_text(), original)  # untouched

    def test_repair_backend_as_wiring_injects_router(self):
        with tempfile.TemporaryDirectory() as tmp:
            be = Path(tmp) / "app" / "backend"
            be.mkdir(parents=True)
            (be / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n")
            (be / "oauth_routes.py").write_text("def build_router(s, j):\n    ...\n")
            HealPipeline(_orch(tmp)).repair_backend_as_wiring()
            src = (be / "main.py").read_text()
            self.assertIn("build_router", src)
            self.assertIn("include_router", src)

    def test_empty_dir_is_safe_noop(self):
        # No app/backend → every repair returns cleanly (best-effort contract).
        with tempfile.TemporaryDirectory() as tmp:
            hp = HealPipeline(_orch(tmp))
            hp.repair_backend_auth()
            hp.repair_backend_packaging()
            hp.repair_ddl_from_orm()
            hp.repair_handler_fk_aliases()
            hp.repair_psycopg_dsn()
            hp.repair_frontend_api()
            hp.repair_backend_entrypoint()
            hp.repair_backend_as_wiring()
            hp.merge_committed_agent_work()  # non-git dir → clean return
            hp.commit_framework_delivery()


class ShimDelegationTests(unittest.TestCase):
    def test_unbound_shim_on_stub_runs_real_logic(self):
        # The orchestrator shim constructs a fresh HealPipeline(self); calling the
        # unbound method on a SimpleNamespace stub must run the real repair.
        from multi_agent.orchestrator import Orchestrator
        with tempfile.TemporaryDirectory() as tmp:
            be = Path(tmp) / "app" / "backend"
            be.mkdir(parents=True)
            (be / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n")
            stub = _orch(tmp)
            Orchestrator._repair_backend_entrypoint(stub)
            self.assertIn("uvicorn.run", (be / "main.py").read_text())


if __name__ == "__main__":
    unittest.main()
