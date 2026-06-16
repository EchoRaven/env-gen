import json
import sys
import tempfile
import unittest
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))


class TestUserGatesEndpoints(unittest.TestCase):
    def setUp(self):
        from live_monitor_server import _HUB_REGISTRY_CACHE, _SSE_HUB_CACHE
        _HUB_REGISTRY_CACHE.clear()
        _SSE_HUB_CACHE.clear()
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        from live_monitor_server import create_project_call
        self.project_id = create_project_call(self.root, {"name": "gates-test"})["id"]

    def tearDown(self):
        from live_monitor_server import _HUB_REGISTRY_CACHE, _SSE_HUB_CACHE
        _HUB_REGISTRY_CACHE.clear()
        _SSE_HUB_CACHE.clear()
        self._tmp.cleanup()

    def test_list_gates_empty(self):
        from live_monitor_server import list_user_gates_call
        result = list_user_gates_call(self.root, self.project_id)
        self.assertEqual(result, {"gates": []})

    def test_create_gate_validates_and_persists(self):
        from live_monitor_server import create_user_gate_call, list_user_gates_call
        result = create_user_gate_call(self.root, self.project_id, {
            "name": "README present",
            "type": "file_exists",
            "params": {"path": "README.md"},
        })
        self.assertNotIn("error", result, result)
        self.assertIn("id", result)
        gates = list_user_gates_call(self.root, self.project_id)["gates"]
        self.assertEqual(len(gates), 1)
        self.assertEqual(gates[0]["name"], "README present")
        # Each gate in the list includes its current status
        self.assertIn("status", gates[0])
        self.assertEqual(gates[0]["status"]["passed"], False)

    def test_create_gate_rejects_invalid(self):
        from live_monitor_server import create_user_gate_call
        result = create_user_gate_call(self.root, self.project_id, {
            "type": "unknown_type", "name": "x", "params": {},
        })
        self.assertIn("error", result)

    def test_update_gate_changes_params(self):
        from live_monitor_server import (
            create_user_gate_call, update_user_gate_call, list_user_gates_call,
        )
        created = create_user_gate_call(self.root, self.project_id, {
            "name": "gate1", "type": "file_exists", "params": {"path": "a.txt"},
        })
        update_user_gate_call(self.root, self.project_id, created["id"], {
            "params": {"path": "b.txt"},
        })
        gates = list_user_gates_call(self.root, self.project_id)["gates"]
        self.assertEqual(gates[0]["params"]["path"], "b.txt")

    def test_delete_gate(self):
        from live_monitor_server import (
            create_user_gate_call, delete_user_gate_call, list_user_gates_call,
        )
        created = create_user_gate_call(self.root, self.project_id, {
            "name": "gate1", "type": "file_exists", "params": {"path": "x.txt"},
        })
        delete_user_gate_call(self.root, self.project_id, created["id"])
        self.assertEqual(list_user_gates_call(self.root, self.project_id)["gates"], [])

    def test_evaluate_specific_gate(self):
        from live_monitor_server import create_user_gate_call, evaluate_user_gate_call
        created = create_user_gate_call(self.root, self.project_id, {
            "name": "g", "type": "file_exists", "params": {"path": "nope.txt"},
        })
        result = evaluate_user_gate_call(self.root, self.project_id, created["id"])
        self.assertFalse(result["passed"])
        self.assertIn("nope.txt", result["message"])

    def test_deliver_includes_user_gate_blockers(self):
        from live_monitor_server import create_user_gate_call, deliver_project_call
        create_user_gate_call(self.root, self.project_id, {
            "name": "needs README", "type": "file_exists", "params": {"path": "README.md"},
        })
        result = deliver_project_call(self.root, self.project_id, {})
        # Should be blocked because the gate fails
        self.assertFalse(result.get("delivered", False))
        blockers = result.get("report", {}).get("blockers", [])
        # User gate failure should appear with a user_gate: prefix
        self.assertTrue(any("user_gate:" in b or "needs README" in b for b in blockers),
                        f"Expected user gate blocker, got: {blockers}")

    def test_gates_persisted_across_resolve(self):
        from live_monitor_server import (
            create_user_gate_call, list_user_gates_call, _HUB_REGISTRY_CACHE,
        )
        create_user_gate_call(self.root, self.project_id, {
            "name": "g", "type": "file_exists", "params": {"path": "x"},
        })
        # Clear caches to force reload from disk
        _HUB_REGISTRY_CACHE.clear()
        gates_file = self.root / self.project_id / ".user_gates.json"
        self.assertTrue(gates_file.exists())
        gates = list_user_gates_call(self.root, self.project_id)["gates"]
        self.assertEqual(len(gates), 1)


if __name__ == "__main__":
    unittest.main()
