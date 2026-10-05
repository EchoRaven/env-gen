r"""#1203fu: both flow-coverage producers handed `compute_flow_coverage` a RegistryHub.

`_derive_ui_spec_from_hub` opens with

    workhub = getattr(hub_registry, "workhub", None)
    if workhub is None:
        return None

so a bare `RegistryHub` -- which has no `.workhub` -- makes `compute_flow_coverage` return
`FlowCoverageReport(source="none")`, and `.failed` / `.missing` are EMPTY by construction.
`_ui_flow_failed_names` and `_ui_flow_missing_names` both called it with
`orch.hubs.registryhub`, so both returned [] on every call since #981/#280 landed.

The parameter is named `hub_registry` the whole way down (`compute_deliverability(hub_registry,
app_root, ...)`, `_flow_coverage_summary(hub_registry, app_root)`) while every working caller
passes the CONTAINER: `delivery_gate.py` does `compute_flow_coverage(hubs, None)` and
`compute_deliverability(hubs, ...)`. The name invited the wrong object.

Measured on r162's real hubs:

    passing the RegistryHub  -> spec=None, source="none", failed=[], missing=[]
    passing a container      -> source="pages", missing=5 flows

and at the artifact level, 0 of 26 `deliverability_ui_flow_missing` remediation tasks across
r14x-r16x name a single flow -- all 26 carry only the generic body.

What was dead, on the two biggest blockers in the corpus (`deliverability_ui_flow_failed` 2503
red gate records across 81 runs; `deliverability_ui_flow_missing` 1049 across 104): #280's and
#981's instance naming, #1176's auth contradiction, #1177's ui_smoke refresh, #1182's
control-absence answer, and #1203ft's replay of the walk's own words. Every one of them hangs
off these two lists being non-empty.

Same shape as #1178, which fixed it for the sibling producer `_ui_evidence_failed_pages` and
whose comment reads "the two readers must agree". Two more readers did not.

LOCAL-ONLY (agent/tests/ gitignored).
"""
from __future__ import annotations

import ast
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime import remediation_dispatcher as RD  # noqa: E402
from multi_agent.runtime.flow_coverage import _derive_ui_spec_from_hub  # noqa: E402

SRC = LLM_DIR / "multi_agent" / "runtime" / "remediation_dispatcher.py"
PRODUCERS = ("_ui_flow_failed_names", "_ui_flow_missing_names")


class _RegistryHubLike:
    """What the producers used to pass: a registry, with no `.workhub`."""

    def list_ui_pages(self):
        return {"fyp_feed_logged_out": {"name": "fyp_feed_logged_out", "critical": True}}


class _WorkHubLike:
    def list_documents(self, kind=None):
        return []


def _container():
    return types.SimpleNamespace(registryhub=_RegistryHubLike(), workhub=_WorkHubLike())


class TheWrongObjectIsEmptyByConstruction(unittest.TestCase):
    def test_a_registryhub_has_no_workhub_so_the_spec_is_none(self):
        self.assertIsNone(_derive_ui_spec_from_hub(_RegistryHubLike()))

    def test_a_container_produces_a_spec(self):
        spec = _derive_ui_spec_from_hub(_container())
        self.assertIsNotNone(spec)
        self.assertTrue(spec.get("pages"), spec)

    def test_this_is_what_made_both_lists_empty(self):
        """The distinction the producers got wrong, stated as the property it breaks."""
        from multi_agent.runtime.flow_coverage import compute_flow_coverage
        bare = compute_flow_coverage(_RegistryHubLike())
        held = compute_flow_coverage(_container())
        self.assertEqual(getattr(bare, "source", None), "none")
        self.assertNotEqual(getattr(held, "source", None), "none")


class BothProducersPassTheContainer(unittest.TestCase):
    def _call_args(self, fn_name):
        tree = ast.parse(SRC.read_text(encoding="utf-8"))
        for fn in ast.walk(tree):
            if not (isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and fn.name == fn_name):
                continue
            out = []
            for node in ast.walk(fn):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                        and node.func.id == "_cfc"):
                    out.append([ast.unparse(a) for a in node.args])
            return out
        self.fail("%s is gone" % fn_name)

    def test_neither_producer_passes_the_registryhub(self):
        for name in PRODUCERS:
            calls = self._call_args(name)
            self.assertTrue(calls, name)
            for args in calls:
                self.assertTrue(args, "%s calls _cfc with no argument" % name)
                self.assertNotIn("orch.hubs.registryhub", args[0],
                                 "%s still passes the RegistryHub" % name)
                self.assertEqual(args[0], "orch.hubs", name)

    def test_a_third_producer_cannot_be_added_the_same_way(self):
        """The RULE, not the two instances (#1202tb): every `_cfc` call in this module must be
        handed the container, so the next one has to be written correctly."""
        tree = ast.parse(SRC.read_text(encoding="utf-8"))
        bad = []
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "_cfc" and node.args):
                arg = ast.unparse(node.args[0])
                if arg != "orch.hubs":
                    bad.append((node.lineno, arg))
        self.assertEqual(bad, [], "a _cfc call is not handed the hubs container: %s" % bad)

    def test_the_producers_still_read_failed_and_missing(self):
        """The fix must not quietly change WHICH attribute each producer reads.

        Over the AST, not a byte window: my own explanatory comment pushed the attribute past
        a `src[i:i+1400]` slice on the first run of this test, which is the failure mode #943's
        ratchet exists for and the third time it bit this session."""
        tree = ast.parse(SRC.read_text(encoding="utf-8"))
        want = {"_ui_flow_failed_names": "failed", "_ui_flow_missing_names": "missing"}
        for fn in ast.walk(tree):
            if not (isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and fn.name in want):
                continue
            attrs = {a.value for n in ast.walk(fn)
                     if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "getattr"
                     and len(n.args) >= 2 and isinstance(n.args[1], ast.Constant)
                     for a in [n.args[1]]}
            self.assertIn(want.pop(fn.name), attrs,
                          "%s no longer reads its own attribute" % fn.name)
        self.assertEqual(want, {}, "a producer is gone: %s" % want)


if __name__ == "__main__":
    unittest.main()
