"""#1202fa: a chain that fails and then passes must not erase why it failed.

`record_chain_result` overwrote `last_result` unconditionally, so the next
passing run destroyed the evidence -- including the request body #1202ew records
on failing steps, which exists precisely to settle what the failure was about.
That is why oscillation has only ever been diagnosable by reconstructing it from
logs: business_chain_failing flips 115 times across 18 recent runs, and each flip
erased its own cause.
"""
import sys
import tempfile
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent))
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

from multi_agent.runtime.registryhub import RegistryHub  # noqa: E402

FAIL = {"broken": ["POST /api/x -> 400 (a create needs at least one field)"],
        "steps": [{"method": "POST", "path": "/api/x", "ok": False, "status": 400,
                   "sent_body": {"name": "Verifier 1234", "place_ids": []}},
                  {"method": "GET", "path": "/api/x", "ok": True, "status": 200}]}
PASS = {"broken": [], "steps": [{"method": "POST", "path": "/api/x", "ok": True,
                                 "status": 201}]}


class TestFlipKeepsItsCause(unittest.TestCase):

    def setUp(self):
        self.hub = RegistryHub(Path(tempfile.mkdtemp()))
        self.hub.register_verification_chain(
            "c", [{"method": "POST", "path": "/api/x", "expect": [201]}], agent="verifier")

    def _rec(self):
        return self.hub.get_verification_chains()["c"]

    def test_a_pass_does_not_erase_the_previous_failure(self):
        self.hub.record_chain_result("c", FAIL)
        self.hub.record_chain_result("c", PASS)
        rec = self._rec()
        self.assertEqual(rec["status"], "passing")
        self.assertEqual(rec["last_result"]["broken"], [], "the current result is the pass")
        kept = rec["last_failure_1202fa"]
        self.assertIn("400", kept["broken"][0])

    def test_the_request_body_survives_the_flip(self):
        """#1202ew's evidence is the whole point; a flip must not take it."""
        self.hub.record_chain_result("c", FAIL)
        self.hub.record_chain_result("c", PASS)
        steps = self._rec()["last_failure_1202fa"]["failed_steps"]
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0]["sent_body"], {"name": "Verifier 1234", "place_ids": []})

    def test_only_the_failing_steps_are_kept(self):
        """The passing steps are not evidence, and they are what would make this large."""
        self.hub.record_chain_result("c", FAIL)
        steps = self._rec()["last_failure_1202fa"]["failed_steps"]
        self.assertTrue(all(s["ok"] is False for s in steps))
        self.assertEqual(len(steps), 1, "the passing step in FAIL must not be stored")

    def test_flips_are_counted(self):
        for r in (FAIL, PASS, FAIL, PASS):
            self.hub.record_chain_result("c", r)
        self.assertEqual(self._rec()["flips_1202fa"], 3,
                         "fail->pass->fail->pass is three transitions")

    def test_a_repeat_of_the_same_verdict_is_not_a_flip(self):
        for r in (FAIL, FAIL, FAIL):
            self.hub.record_chain_result("c", r)
        self.assertEqual(self._rec()["flips_1202fa"], 0)

    def test_the_first_result_is_not_a_flip(self):
        """A chain starts 'registered'; arriving at a verdict is not oscillating."""
        self.hub.record_chain_result("c", FAIL)
        self.assertEqual(self._rec()["flips_1202fa"], 0)

    def test_a_later_failure_replaces_the_kept_one(self):
        self.hub.record_chain_result("c", FAIL)
        self.hub.record_chain_result("c", PASS)
        newer = {"broken": ["POST /api/x -> 409 (duplicate resource)"],
                 "steps": [{"method": "POST", "path": "/api/x", "ok": False, "status": 409}]}
        self.hub.record_chain_result("c", newer)
        self.assertIn("409", self._rec()["last_failure_1202fa"]["broken"][0])


if __name__ == "__main__":
    unittest.main()
