"""Tests for WorkHub retro helpers (Cutover 16)."""

import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402


class WorkHubRetroTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="wh_retro_"))
        self.reg = HubRegistry(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_list_retros_empty(self) -> None:
        self.assertEqual(self.reg.gate_registry.list_retros(), [])

    def test_list_retros_filters_only_retro_kind(self) -> None:
        self.reg.workhub.create_page(title="design", agent="d", kind="design")
        self.reg.workhub.create_page(title="r1", agent="orch", kind="retro",
                                       metadata={"generation_id": 1000.0})
        retros = self.reg.gate_registry.list_retros()
        self.assertEqual(len(retros), 1)
        self.assertEqual(retros[0]["title"], "r1")

    def test_get_latest_retro_for_generation_returns_match(self) -> None:
        self.reg.workhub.create_page(title="r-old", agent="orch", kind="retro",
                                       metadata={"generation_id": 1000.0})
        self.reg.workhub.create_page(title="r-new", agent="orch", kind="retro",
                                       metadata={"generation_id": 2000.0})
        r = self.reg.gate_registry.get_latest_retro_for_generation(2000.0)
        self.assertIsNotNone(r)
        self.assertEqual(r["title"], "r-new")

    def test_get_latest_retro_for_generation_returns_none_when_no_match(self) -> None:
        self.reg.workhub.create_page(title="r1", agent="orch", kind="retro",
                                       metadata={"generation_id": 1000.0})
        self.assertIsNone(self.reg.gate_registry.get_latest_retro_for_generation(9999.0))

    def test_get_latest_retro_returns_most_recent_when_multiple_for_same_gen(self) -> None:
        # Same generation_id used by two retros (e.g., revised retro)
        p1 = self.reg.workhub.create_page(title="r1", agent="orch", kind="retro",
                                            metadata={"generation_id": 1000.0})
        time.sleep(0.01)
        p2 = self.reg.workhub.create_page(title="r2", agent="orch", kind="retro",
                                            metadata={"generation_id": 1000.0})
        latest = self.reg.gate_registry.get_latest_retro_for_generation(1000.0)
        self.assertEqual(latest["id"], p2["id"])


if __name__ == "__main__":
    unittest.main()
