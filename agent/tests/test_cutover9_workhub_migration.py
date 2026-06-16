import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent

STORES_PATH = (
    AGENT_DIR
    / "env_generator" / "llm_generator" / "multi_agent" / "runtime"
    / "hubs" / "workhub" / "stores.py"
)
SERVICE_PATH = (
    AGENT_DIR
    / "env_generator" / "llm_generator" / "multi_agent" / "runtime"
    / "hubs" / "workhub" / "service.py"
)


class WorkHubMigrationTests(unittest.TestCase):
    def test_stores_uses_jsonstore(self) -> None:
        src = STORES_PATH.read_text()
        self.assertIn("from ...json_store import JsonStore", src)
        self.assertNotIn("CRDTStore", src)
        self.assertNotIn("LWWMap", src)

    def test_stores_uses_hub_dir_parameter(self) -> None:
        src = STORES_PATH.read_text()
        self.assertRegex(src, r"def create\(cls, hub_dir")
        self.assertNotIn("crdt_dir", src)

    def test_service_drops_timestamp_import(self) -> None:
        src = SERVICE_PATH.read_text()
        self.assertNotRegex(src, r"from \.\.\.crdt_types import")
        self.assertNotIn("Timestamp", src)

    def test_service_uses_hub_dir_parameter(self) -> None:
        src = SERVICE_PATH.read_text()
        # WorkHub signature is `__init__(self, hub_dir, eventhub=...)` after this cutover.
        self.assertRegex(src, r"def __init__\(self, hub_dir")
        self.assertNotIn("crdt_dir", src)


if __name__ == "__main__":
    unittest.main()
