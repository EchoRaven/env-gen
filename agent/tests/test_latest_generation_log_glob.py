"""``_latest_generation_log`` must find both ``generation.log`` and
``generation_<ts>.log``.

Bug: the original glob was ``generation_*.log`` (requires underscore prefix),
which didn't match the actual monitor-written ``generation.log`` filename.
The result: ``coreAgents`` saw empty activity → every agent rendered as
``idle`` even while design/backend were actively making tool calls.
"""
from __future__ import annotations

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


class TestLatestGenerationLogGlob(unittest.TestCase):
    def test_finds_generation_log_without_timestamp_suffix(self):
        from live_monitor_server import _latest_generation_log
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "logs").mkdir()
            f = project / "logs" / "generation.log"
            f.write_text("18:00:00 [I] Agent.Design Agent: [design] hello\n")
            picked = _latest_generation_log(project)
            self.assertIsNotNone(picked, "generation.log without timestamp suffix not found")
            self.assertEqual(picked.name, "generation.log")

    def test_finds_timestamped_generation_log(self):
        from live_monitor_server import _latest_generation_log
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "logs").mkdir()
            f = project / "logs" / "generation_20260528_021000.log"
            f.write_text("dummy\n")
            picked = _latest_generation_log(project)
            self.assertIsNotNone(picked)
            self.assertEqual(picked.name, "generation_20260528_021000.log")

    def test_prefers_most_recently_modified_when_both_exist(self):
        from live_monitor_server import _latest_generation_log
        import time
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "logs").mkdir()
            older = project / "logs" / "generation_20200101_000000.log"
            newer = project / "logs" / "generation.log"
            older.write_text("old\n")
            time.sleep(0.02)  # ensure mtime differs
            newer.write_text("new\n")
            picked = _latest_generation_log(project)
            self.assertEqual(picked.name, "generation.log",
                             f"expected the newer file; picked {picked}")


if __name__ == "__main__":
    unittest.main()
