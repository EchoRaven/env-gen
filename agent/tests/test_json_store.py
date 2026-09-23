"""Tests for the JsonStore replacement for CRDTStore + LWWMap."""

import json
import os
import sys
import shutil
import tempfile
import time
import unittest
from unittest import mock
from pathlib import Path

# Add the agent package to path (matches the pattern used by other tests).
THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.json_store import JsonStore  # noqa: E402


class JsonStoreBasicTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp(prefix="jsonstore_")
        self.path = Path(self.tmpdir) / "store.json"

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_empty_store_returns_empty_value(self) -> None:
        store = JsonStore(self.path)
        self.assertEqual(store.value(), {})
        self.assertIsNone(store.get("missing"))

    def test_set_then_value_returns_inserted_pair(self) -> None:
        store = JsonStore(self.path)
        store.set("alpha", {"x": 1}, agent="orch")
        self.assertEqual(store.value(), {"alpha": {"x": 1}})
        self.assertEqual(store.get("alpha"), {"x": 1})

    def test_set_persists_across_instances(self) -> None:
        store1 = JsonStore(self.path)
        store1.set("alpha", {"x": 1}, agent="orch")
        store2 = JsonStore(self.path)
        self.assertEqual(store2.value(), {"alpha": {"x": 1}})

    def test_delete_removes_key(self) -> None:
        store = JsonStore(self.path)
        store.set("alpha", 1)
        store.set("beta", 2)
        store.delete("alpha")
        self.assertEqual(store.value(), {"beta": 2})
        self.assertIsNone(store.get("alpha"))


class JsonStoreUpdateCompatTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp(prefix="jsonstore_")
        self.path = Path(self.tmpdir) / "store.json"

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_update_with_set_third_arg_ignored(self) -> None:
        store = JsonStore(self.path)
        store.update(lambda m: m.set("alpha", {"x": 1}, "ignored_ts_arg"))
        self.assertEqual(store.value(), {"alpha": {"x": 1}})

    def test_update_with_delete(self) -> None:
        store = JsonStore(self.path)
        store.set("alpha", 1)
        store.update(lambda m: m.delete("alpha", "ignored_ts_arg"))
        self.assertEqual(store.value(), {})

    def test_update_identity_mutator_touches_meta(self) -> None:
        store = JsonStore(self.path)
        v0 = store.get_version()
        store.update(lambda m: m, change_info={"system": "ensure"})
        self.assertGreater(store.get_version(), v0)

    def test_update_returns_post_write_snapshot(self) -> None:
        store = JsonStore(self.path)
        snap = store.update(lambda m: m.set("alpha", 7))
        self.assertEqual(snap, {"alpha": 7})

    def test_version_increments_per_write(self) -> None:
        store = JsonStore(self.path)
        self.assertEqual(store.get_version(), 0)
        store.set("a", 1)
        self.assertEqual(store.get_version(), 1)
        store.set("b", 2)
        self.assertEqual(store.get_version(), 2)
        store.delete("a")
        self.assertEqual(store.get_version(), 3)


class JsonStoreLegacyLWWMapReadTests(unittest.TestCase):
    """Existing shared/crdt/ files were written by CRDTStore(LWWMap); the new
    JsonStore must read them transparently and persist in the new flat shape
    on the first write."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp(prefix="jsonstore_legacy_")
        self.path = Path(self.tmpdir) / "store.json"

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_legacy(self) -> None:
        legacy = {
            "type": "LWWMap",
            "entries": {
                "alpha": {
                    "type": "LWWRegister",
                    "value": {"x": 1},
                    "timestamp": {"wall_time": 1.0, "logical": 0, "node_id": "old"},
                },
                "beta": {
                    "type": "LWWRegister",
                    "value": 42,
                    "timestamp": {"wall_time": 2.0, "logical": 0, "node_id": "old"},
                },
            },
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(legacy))

    def test_legacy_file_reads_as_flat_dict(self) -> None:
        self._write_legacy()
        store = JsonStore(self.path)
        self.assertEqual(store.value(), {"alpha": {"x": 1}, "beta": 42})
        self.assertEqual(store.get("alpha"), {"x": 1})

    def test_legacy_file_drops_lww_register_timestamps_on_first_write(self) -> None:
        self._write_legacy()
        store = JsonStore(self.path)
        store.set("gamma", 99, agent="orch")
        on_disk = json.loads(self.path.read_text())
        self.assertNotIn("type", on_disk)
        self.assertNotIn("entries", on_disk)
        self.assertEqual(on_disk.get("alpha"), {"x": 1})
        self.assertEqual(on_disk.get("beta"), 42)
        self.assertEqual(on_disk.get("gamma"), 99)
        self.assertIn("_meta", on_disk)
        self.assertEqual(on_disk["_meta"]["last_modified_by"], "orch")

    def test_legacy_lwwmap_entry_with_null_value_is_filtered(self) -> None:
        # CRDTStore used set(key, None, ts) for deletes; legacy reader must
        # drop entries whose value is None.
        legacy = {
            "type": "LWWMap",
            "entries": {
                "alpha": {"type": "LWWRegister", "value": None,
                          "timestamp": {"wall_time": 1.0, "logical": 0, "node_id": "x"}},
                "beta": {"type": "LWWRegister", "value": "live",
                         "timestamp": {"wall_time": 2.0, "logical": 0, "node_id": "x"}},
            },
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(legacy))
        store = JsonStore(self.path)
        self.assertEqual(store.value(), {"beta": "live"})


class SaveFailureTempCleanupTests(unittest.TestCase):
    """#1202ap: a write that dies partway must not leave its temp file behind."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp(prefix="jsonstore_1202ap_")
        self.path = Path(self.tmpdir) / "store.json"

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_failed_save_removes_its_temp_file(self) -> None:
        """The corpus had 5 orphaned temps, the worst 2.4MB of a 6.5MB target, written
        the same day /data reached 99%. Nothing reclaims them, so writes that fail
        because the disk is full leave the disk fuller. The live file must survive
        untouched (os.replace is atomic) and the error must still reach the caller.
        """
        store = JsonStore(self.path)
        store.set("keep_me", {"v": 1})
        before = self.path.read_bytes()

        def _no_space(*_a, **_k):
            raise OSError(28, "No space left on device")

        # #1202sj moved the serialisation off `json.dump` (its `indent=` was forcing the
        # pure-Python encoder). Inject at fsync instead, which is BETTER placed for what this
        # test asserts: a real ENOSPC dies with the temp file already on disk, which is the
        # only state in which "the orphan must be cleaned up" means anything. Failing during
        # serialisation would make the cleanup assertion vacuous — no temp would exist yet.
        with mock.patch("multi_agent.runtime.json_store.os.fsync", _no_space):
            with self.assertRaises(OSError):
                store.set("added_while_full", {"v": 2})

        leftovers = sorted(Path(self.tmpdir).glob("*.tmp"))
        self.assertEqual(leftovers, [], f"orphaned temp survived a failed write: {leftovers}")
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(JsonStore(self.path).get("keep_me"), {"v": 1})


if __name__ == "__main__":
    unittest.main()

