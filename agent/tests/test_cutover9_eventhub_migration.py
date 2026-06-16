"""Source-level checks that eventhub.py no longer imports CRDT scaffolding."""

import sys
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent

EVENTHUB_PATH = (
    AGENT_DIR / "env_generator" / "llm_generator" / "multi_agent" / "runtime" / "eventhub.py"
)


class EventHubMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.src = EVENTHUB_PATH.read_text()

    def test_no_crdt_imports(self) -> None:
        self.assertNotRegex(self.src, r"from \.crdt_store import")
        self.assertNotRegex(self.src, r"from \.crdt_types import")
        self.assertNotIn("CRDTStore", self.src)
        self.assertNotIn("LWWMap", self.src)
        self.assertNotIn("Timestamp", self.src)

    def test_uses_jsonstore(self) -> None:
        self.assertIn("from .json_store import JsonStore", self.src)
        self.assertGreaterEqual(self.src.count("JsonStore("), 4)

    def test_constructor_uses_hub_dir(self) -> None:
        self.assertRegex(self.src, r"def __init__\(self, hub_dir")
        self.assertNotRegex(self.src, r"def __init__\(self, crdt_dir")

    def test_no_timestamp_now_calls(self) -> None:
        self.assertNotIn("Timestamp.now(", self.src)


if __name__ == "__main__":
    unittest.main()
