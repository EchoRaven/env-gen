import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402


class DirMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="hubdir_"))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_new_install_uses_shared_hubs(self) -> None:
        reg = HubRegistry(self.tmp)
        self.assertEqual(reg._store_dir, self.tmp / "shared" / "hubs")
        self.assertTrue((self.tmp / "shared" / "hubs").exists())
        self.assertFalse((self.tmp / "shared" / "crdt").exists())

    def test_existing_shared_crdt_is_auto_migrated(self) -> None:
        legacy = self.tmp / "shared" / "crdt"
        legacy.mkdir(parents=True)
        (legacy / "registryhub_endpoints.json").write_text(json.dumps({"existing": "value"}))
        (legacy / "eventhub_events.json").write_text(json.dumps({"e": 1}))

        reg = HubRegistry(self.tmp)

        new_dir = self.tmp / "shared" / "hubs"
        self.assertTrue(new_dir.exists())
        self.assertTrue((new_dir / "registryhub_endpoints.json").exists())
        self.assertTrue((new_dir / "eventhub_events.json").exists())
        self.assertEqual(reg._store_dir, new_dir)
        moved = json.loads((new_dir / "registryhub_endpoints.json").read_text())
        # HubRegistry init touches each hub JSON via ensure_documents (adds _meta).
        # The migrated payload must survive verbatim alongside the new meta key.
        self.assertEqual(moved.get("existing"), "value")

    def test_both_dirs_present_prefers_shared_hubs(self) -> None:
        (self.tmp / "shared" / "hubs").mkdir(parents=True)
        (self.tmp / "shared" / "hubs" / "marker_new.json").write_text("{}")
        (self.tmp / "shared" / "crdt").mkdir(parents=True)
        (self.tmp / "shared" / "crdt" / "marker_old.json").write_text("{}")

        reg = HubRegistry(self.tmp)

        self.assertEqual(reg._store_dir, self.tmp / "shared" / "hubs")
        # Pre-existing new file is preserved; old file is NOT copied over.
        self.assertTrue((self.tmp / "shared" / "hubs" / "marker_new.json").exists())
        self.assertFalse((self.tmp / "shared" / "hubs" / "marker_old.json").exists())


if __name__ == "__main__":
    unittest.main()
