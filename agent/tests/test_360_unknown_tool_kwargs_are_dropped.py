"""#360: an unaccepted kwarg drops instead of hard-erroring the tool call.

The dispatcher invokes tools as `exec_fn(**tool_args)`, so any argument the
model supplies that the callee's signature does not accept raises
`TypeError: execute() got an unexpected keyword argument '...'` and the whole
call is lost. 124 such failures across the corpus:

    34 'uses'   14 'branch'   12 'task_id'   9 'error'
     8 'check'   6 'ref'       4 'metadata'   4 'agent_branch'

('metadata' is the ui_flow contract from #340 — agents trying to pass metadata
to codehub_record_check, which has no such parameter.)

This is the same class as #335: an LLM-authored argument list reaching a strict
boundary unnormalised. Dropping the surplus keys with a WARNING keeps the call
alive and makes the mismatch visible, instead of discarding a turn.

It also makes the second half of this commit safe. `deliver_project` advertises
`force_deliver` in its schema and binds it in its signature, and the parameter
is read NOWHERE in the entire package -- a fabricated affordance. Agents set
`force_deliver: True` 367 times across the corpus believing they were escalating
past the gate; nothing happened. Deleting it from a strict-splat dispatcher
would have converted those 367 calls into hard TypeErrors, which is why the
generic fix lands first.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _filter(fn, args):
    from multi_agent.agents.runtime.tooling import drop_unaccepted_kwargs
    return drop_unaccepted_kwargs(fn, args)


class SurplusArgumentsAreDropped(unittest.TestCase):

    def test_an_unaccepted_kwarg_is_removed(self):
        def execute(pr_id, name, status, evidence=None):
            pass
        kept, dropped = _filter(execute, {"pr_id": "main", "name": "x",
                                          "status": "success", "metadata": {}})
        self.assertNotIn("metadata", kept)
        self.assertEqual(dropped, ["metadata"])

    def test_accepted_kwargs_pass_through_untouched(self):
        def execute(pr_id, name, status, evidence=None):
            pass
        args = {"pr_id": "main", "name": "x", "status": "success",
                "evidence": {"a": 1}}
        kept, dropped = _filter(execute, dict(args))
        self.assertEqual(kept, args)
        self.assertEqual(dropped, [])

    def test_several_surplus_keys_are_all_reported(self):
        def execute(a):
            pass
        kept, dropped = _filter(execute, {"a": 1, "branch": "x", "ref": "y"})
        self.assertEqual(kept, {"a": 1})
        self.assertEqual(sorted(dropped), ["branch", "ref"])

    def test_the_call_actually_succeeds_after_filtering(self):
        def execute(a, b=2):
            return a + b
        kept, _ = _filter(execute, {"a": 1, "surprise": 9})
        self.assertEqual(execute(**kept), 3)


class ToolsThatAcceptAnythingKeepEverything(unittest.TestCase):

    def test_var_keyword_signature_is_left_alone(self):
        def execute(a, **kw):
            pass
        args = {"a": 1, "anything": 2, "else_": 3}
        kept, dropped = _filter(execute, dict(args))
        self.assertEqual(kept, args)
        self.assertEqual(dropped, [])


class DegenerateInputs(unittest.TestCase):

    def test_empty_args(self):
        def execute(a=None):
            pass
        self.assertEqual(_filter(execute, {}), ({}, []))

    def test_uninspectable_callee_is_left_alone(self):
        """The defensive branch: if inspection fails we must not guess.
        (`print` was my first choice and is a bad example -- it IS inspectable
        in 3.11, signature (*args, sep, end, file, flush), so its surplus keys
        are correctly dropped.)"""
        kept, dropped = _filter(None, {"anything": 1})
        self.assertEqual(kept, {"anything": 1})
        self.assertEqual(dropped, [])

    def test_an_inspectable_builtin_still_gets_filtered(self):
        kept, dropped = _filter(print, {"sep": " ", "anything": 1})
        self.assertEqual(kept, {"sep": " "})
        self.assertEqual(dropped, ["anything"])


class TheFabricatedForceDeliverIsGone(unittest.TestCase):
    """Declared in the schema, bound in the signature, read nowhere."""

    def _src(self):
        from tools import agent_interaction_tools
        return Path(agent_interaction_tools.__file__).read_text()

    def test_not_in_the_signature(self):
        self.assertNotIn("force_deliver: bool = False", self._src())

    def test_not_advertised_in_the_schema(self):
        self.assertNotIn('"force_deliver"', self._src())

    def test_it_is_read_nowhere_in_the_package(self):
        hits = []
        for p in (LLM_DIR / "multi_agent").rglob("*.py"):
            if "force_deliver" in p.read_text(errors="ignore"):
                hits.append(p.name)
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
