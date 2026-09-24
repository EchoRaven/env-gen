"""DECOMPOSITION VisualFidelity slice A: `_compile_reference_materials` extracted
to runtime.reference_materials.compile_reference_materials. Pins the function's
result contract + the orchestrator shim's attribute-write semantics (which attrs
get written on which path — the behavior-preservation risk).

LOCAL-ONLY (agent/tests/ is gitignored per repo policy) — run for verification.
"""

import asyncio
import logging
import sys
import unittest
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime import reference_materials as rm  # noqa: E402
from multi_agent.runtime.reference_materials import (  # noqa: E402
    ReferenceCompileResult, compile_reference_materials,
)


class CompileFnTests(unittest.TestCase):
    def test_no_references_returns_raw_classified_empty(self):
        res = asyncio.run(compile_reference_materials(
            "build a blog", output_dir="/tmp/x", llm=None,
            logger=logging.getLogger("t"), reference_images=[]))
        self.assertEqual(res.requirements, "build a blog")
        self.assertTrue(res.classified)          # classify ran
        self.assertEqual(res.images, [])
        self.assertEqual(res.docs, [])
        self.assertIsNone(res.spec)              # never compiled

    def test_classify_failure_leaves_state_untouched(self):
        # classify_references raising ⇒ classified=False so the shim won't
        # overwrite the orchestrator's prior reference_images/_docs.
        orig = rm.classify_references
        rm.classify_references = lambda paths: (_ for _ in ()).throw(RuntimeError("boom"))
        try:
            res = asyncio.run(compile_reference_materials(
                "req", output_dir="/tmp/x", llm=None,
                logger=logging.getLogger("t"), reference_images=["a.png"]))
        finally:
            rm.classify_references = orig
        self.assertEqual(res.requirements, "req")
        self.assertFalse(res.classified)
        self.assertIsNone(res.images)
        self.assertIsNone(res.spec)


class ShimWriteContractTests(unittest.TestCase):
    """The Orchestrator shim must write reference_images/_docs ONLY when
    classified, and reference_spec/_summary ONLY when a spec compiled."""

    def _stub_orch(self):
        from multi_agent.orchestrator import Orchestrator
        o = object.__new__(Orchestrator)
        o.output_dir = "/tmp/x"
        o.llm = None
        o._logger = logging.getLogger("t")
        o._reference_images = ["PRIOR"]   # sentinel prior state
        return o

    def _run_with(self, result):
        o = self._stub_orch()
        orig = rm.compile_reference_materials

        async def fake(*a, **k):
            return result
        rm.compile_reference_materials = fake
        try:
            out = asyncio.run(o._compile_reference_materials("req"))
        finally:
            rm.compile_reference_materials = orig
        return o, out

    def test_classified_with_spec_writes_all(self):
        o, out = self._run_with(ReferenceCompileResult(
            "req+SUMMARY", classified=True, images=["i.png"], docs=["d.md"],
            spec={"screens": [1]}, spec_summary="SUMMARY"))
        self.assertEqual(out, "req+SUMMARY")
        self.assertEqual(o._reference_images, ["i.png"])
        self.assertEqual(o._reference_docs, ["d.md"])
        self.assertEqual(o._reference_spec, {"screens": [1]})
        self.assertEqual(o._reference_spec_summary, "SUMMARY")

    def test_classified_without_spec_writes_images_not_spec(self):
        o, out = self._run_with(ReferenceCompileResult(
            "req", classified=True, images=[], docs=[]))
        self.assertEqual(out, "req")
        self.assertEqual(o._reference_images, [])     # overwritten (classified)
        self.assertEqual(o._reference_docs, [])
        self.assertFalse(hasattr(o, "_reference_spec"))  # NOT written

    def test_unclassified_leaves_prior_state(self):
        o, out = self._run_with(ReferenceCompileResult("req", classified=False))
        self.assertEqual(out, "req")
        self.assertEqual(o._reference_images, ["PRIOR"])  # untouched
        self.assertFalse(hasattr(o, "_reference_docs"))


if __name__ == "__main__":
    unittest.main()
