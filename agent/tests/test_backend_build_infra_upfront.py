"""Guard: the static backend build infra can be emitted upfront (no contract).

Run #6: the backend build context had no Dockerfile when validation first ran,
so the orchestrator improvised a BROKEN one (`pip install poetry` → docker build
exit 2) even though the project is uv/pyproject. write_backend_build_infra emits
the static uv Dockerfile + pyproject + reset.sh upfront so that never happens.
"""

import sys
import tempfile
import unittest
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.backend_skeleton import (  # noqa: E402
    write_backend_build_infra, write_backend_skeleton,
)


class BuildInfraUpfrontTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="bbi_"))

    def test_emits_uv_dockerfile_no_poetry(self):
        res = write_backend_build_infra(self.tmp)
        be = self.tmp / "app" / "backend"
        self.assertTrue((be / "Dockerfile").is_file())
        self.assertTrue((be / "pyproject.toml").is_file())
        self.assertTrue((be / "reset.sh").is_file())
        dockerfile = (be / "Dockerfile").read_text()
        self.assertIn("uv", dockerfile)                 # uv-based
        self.assertNotIn("pip install poetry", dockerfile)  # NOT the broken improvised one
        self.assertNotIn("poetry install", dockerfile)
        self.assertIn("Dockerfile", res["written"])

    def test_no_contract_needed(self):
        # The whole point: callable with zero endpoints/tables.
        res = write_backend_build_infra(self.tmp)
        self.assertEqual(set(res["written"]), {"pyproject.toml", "Dockerfile", "reset.sh"})

    def test_full_skeleton_reasserts_same_dockerfile(self):
        # Upfront infra then full skeleton → byte-identical Dockerfile (idempotent).
        write_backend_build_infra(self.tmp)
        before = (self.tmp / "app" / "backend" / "Dockerfile").read_text()
        write_backend_skeleton(self.tmp, endpoints=[], tables={})
        after = (self.tmp / "app" / "backend" / "Dockerfile").read_text()
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
