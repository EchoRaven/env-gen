"""#1202ew: a failing chain step must record the body it actually sent.

8847 of 8847 stored POST steps carry `body: null`. In the live era 30 of 49
failing chain steps are a dispute between what the chain sent and what the
handler expected -- and neither side can see the body, so the dispute is not
settleable by the lane, the dispatcher, or a post-mortem.
"""
import ast
import json
import sys
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent))
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

from multi_agent.runtime.chain_executor import (  # noqa: E402
    _SENT_BODY_CAP_1202EW,
    _sent_body_1202ew,
)

EXEC_SRC = (THIS_DIR.parent / "env_generator" / "llm_generator" / "multi_agent"
            / "runtime" / "chain_executor.py").read_text(encoding="utf-8")


class TestSentBodyIsRecorded(unittest.TestCase):

    def test_a_credential_keeps_its_shape_and_loses_its_value(self):
        """Presence and length are the diagnosis; the secret itself never is."""
        got = _sent_body_1202ew({"email": "a@b.io", "password": "Chain123!x"})
        self.assertEqual(got["email"], "a@b.io")
        self.assertNotIn("Chain123!x", json.dumps(got))
        self.assertEqual(got["password"], "<str:10>")

    def test_a_mangled_credential_is_still_visible_as_mangled(self):
        """Redacting outright would hide the empty-password dispute this exists to settle."""
        self.assertEqual(_sent_body_1202ew({"password": ""})["password"], "<str:0>")
        self.assertNotEqual(_sent_body_1202ew({"password": ""}),
                            _sent_body_1202ew({"password": "Chain123!x"}))

    def test_nested_structures_survive(self):
        got = _sent_body_1202ew({"a": {"b": [1, {"token": "xyz"}]}, "place_ids": []})
        self.assertEqual(got["place_ids"], [])
        self.assertEqual(got["a"]["b"][1]["token"], "<str:3>")

    def test_every_body_the_corpus_has_ever_carried_fits_uncapped(self):
        """The cap's rationale: 7351 authored bodies, largest 592 bytes."""
        self.assertGreaterEqual(_SENT_BODY_CAP_1202EW, 592 * 1.5)
        big = {"f%d" % i: "v" * 8 for i in range(20)}          # ~ 400 bytes
        self.assertIsInstance(_sent_body_1202ew(big), dict)     # not truncated

    def test_an_oversized_body_truncates_instead_of_bloating_the_hub(self):
        got = _sent_body_1202ew({"blob": "x" * (_SENT_BODY_CAP_1202EW * 2)})
        self.assertIsInstance(got, str)
        self.assertLessEqual(len(got), _SENT_BODY_CAP_1202EW + 32)
        self.assertIn("truncated", got)

    def test_a_body_that_is_not_a_mapping_is_itself_the_finding(self):
        """The handler reads `body: dict = None`, so a string arrives as NO body."""
        self.assertIsNone(_sent_body_1202ew(None))
        self.assertEqual(_sent_body_1202ew("just a string"), "just a string")

    def test_recording_never_raises(self):
        class Awkward:
            def __repr__(self): raise RuntimeError("no")
        self.assertIsNotNone(_sent_body_1202ew({"x": Awkward()}))

    def test_the_field_reaches_a_step_record_through_the_real_executor(self):
        """A mechanism that is written but never wired is the most expensive mistake in
        this repo. Drives the real execute_chain over a stubbed transport and compares
        the recorded body against what the transport actually received."""
        from multi_agent.runtime import chain_executor as ce
        on_the_wire = []

        def fake_http(method, url, *, token=None, body=None, timeout=10,
                      form=False, headers=None):
            on_the_wire.append((url, body))
            if url.endswith("/auth/register"):
                return {"status": 201, "body_text": '{"access_token":"T"}', "error": None}
            return {"status": 400,
                    "body_text": '{"detail":"a create needs at least one field"}',
                    "error": None}

        real = ce._http
        try:
            ce._http = fake_http
            res = ce.execute_chain("http://x", {"name": "probe", "steps": [
                {"action": "register", "method": "POST", "path": "/auth/register",
                 "body": {"email": "c@t.io", "password": "Chain123!x"},
                 "expect": [200, 201], "save": {"token": "access_token"}},
                {"action": "create", "method": "POST", "path": "/api/saved-lists",
                 "auth": "token", "body": {"name": "Verifier ${rand}", "place_ids": []},
                 "expect": [200, 201]}]})
        finally:
            ce._http = real

        by_path = {s["path"]: s for s in res["steps"]}
        failing = by_path["/api/saved-lists"]
        self.assertFalse(failing["ok"])
        wire = [b for u, b in on_the_wire if "saved-lists" in u][0]
        self.assertEqual(failing["sent_body"], wire)
        self.assertNotIn("${rand}", json.dumps(failing["sent_body"]),
                         "the recorded body must be the SUBSTITUTED one that went out")
        self.assertNotIn("sent_body", by_path["/auth/register"],
                         "a passing step records nothing")

    def test_it_is_recorded_only_on_failing_steps(self):
        """A passing step's body is not evidence, and 2842 passing chains would bloat."""
        # The property is that the INNERMOST `if` around the record tests `ok` — not that
        # the guarded block is short. The original check used `len(seg.splitlines()) <= 4`
        # as a proxy for "directly guards", which #1202gb broke by adding a second
        # statement to the same correct guard. Find the innermost enclosing If instead.
        tree = ast.parse(EXEC_SRC)
        target = None
        for node in ast.walk(tree):
            seg = ast.get_source_segment(EXEC_SRC, node) or ""
            if isinstance(node, ast.Assign) and 'entry["sent_body"]' in seg:
                target = node
                break
        self.assertIsNotNone(target, "the sent_body record is gone")
        found = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.If):
                continue
            if any(stmt is target for stmt in node.body):   # directly in THIS if's body
                found.append(ast.dump(node.test))
        self.assertTrue(found, "no `if` directly guards the sent_body record")
        for test in found:
            self.assertIn("'ok'", test.replace('"', "'"),
                          "the record must be guarded by the step's ok flag")
            self.assertIn("Not", test, "guarded by `not ok`, not by `ok`")

    def test_the_recorded_body_is_the_one_that_was_sent(self):
        """Recording the AUTHORED body would answer the wrong question: the disputes
        are created by the substitution and repair passes between the two."""
        tree = ast.parse(EXEC_SRC)
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                  and 'entry["sent_body"]' in (ast.get_source_segment(EXEC_SRC, n) or ""))
        record_line = next(n.lineno for n in ast.walk(fn)
                           if isinstance(n, ast.Subscript)
                           and isinstance(getattr(n, "slice", None), ast.Constant)
                           and n.slice.value == "sent_body")
        rebinds = [n.lineno for n in ast.walk(fn) if isinstance(n, ast.Assign)
                   for t in ast.walk(n) if isinstance(t, ast.Name)
                   and t.id == "body" and isinstance(t.ctx, ast.Store)]
        self.assertTrue(rebinds, "expected `body` to be rebound by the repair passes")
        self.assertGreater(record_line, max(r for r in rebinds if r < record_line),
                           "the record must follow every rebinding of `body`")


if __name__ == "__main__":
    unittest.main()
