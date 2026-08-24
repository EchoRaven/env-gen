"""#1086 — the owner is told to relay names it has no way to obtain.

`deliverability_dead_artifacts` is owned by BACKEND, and its remediation advice ends:

    If the breakdown names `files` or `pages_without_files`, those are FRONTEND:
    bug_create for frontend WITH THE NAMES rather than deleting their declarations.

The backend agent receives the blocker string via `_gate_blocker_prose_983`, and the string is

    "670 dead artifact(s) (Cutover 19 gate) — endpoints=3, files=249"

— kinds and counts, no names. `_coverage_summary` reduces the report to counts before it ever
reaches the gate, and the tool that would answer the question, `coverage_audit_check`, is
orchestrator-only (`gate_registry.py:388`: *"coverage_tools bundle restricts callers to
orchestrator"*; `base.py`: *"bundle-intersected, so ONLY the orchestrator … ever sees them"*).
So the instruction is unfollowable by the lane that owns it.

This is exactly #1042 one step further. That fix restored the KINDS with the same reasoning —
*"'7 dead artifact(s)' cannot be acted on and cannot even be routed"* — and the breakdown was
already computed one function up; only the sum was printed. The names are in the same report,
discarded at the same place, and `_flow_coverage_summary` already names its instances with
`join_capped` two functions away.

Names are prefixed by kind so the routing sentence can be acted on without a second lookup,
and capped by the same helper, which declares the remainder.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime.deliverability import _coverage_summary  # noqa: E402
from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402


class _App:
    def __init__(self, files: dict):
        self.root = Path(tempfile.mkdtemp(prefix="dead_1086_"))
        for rel, text in files.items():
            p = self.root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")

    def close(self):
        shutil.rmtree(self.root, ignore_errors=True)


class TheSummaryCarriesTheNames(unittest.TestCase):

    def setUp(self):
        self.hubdir = Path(tempfile.mkdtemp(prefix="hub_1086_"))
        self.reg = HubRegistry(self.hubdir)

    def tearDown(self):
        shutil.rmtree(self.hubdir, ignore_errors=True)

    def test_a_dead_file_is_named(self):
        app = _App({"frontend/src/App.jsx": "export default function App(){return null;}\n",
                    "frontend/src/components/Orphan.jsx":
                        "export default function Orphan(){return null;}\n"})
        try:
            s = _coverage_summary(self.reg, app.root)
            self.assertFalse(s["is_clean"])
            names = s.get("dead_names") or []
            self.assertTrue(any("Orphan.jsx" in n for n in names),
                            f"the dead file is not named: {names}")
            self.assertTrue(any(n.startswith("files:") for n in names),
                            f"names are not prefixed by kind: {names}")
        finally:
            app.close()

    def test_the_kinds_breakdown_still_survives(self):
        """#1042's contract is untouched."""
        app = _App({"frontend/src/App.jsx": "export default function App(){return null;}\n",
                    "frontend/src/components/Orphan.jsx": "export default function O(){}\n"})
        try:
            s = _coverage_summary(self.reg, app.root)
            self.assertEqual(s["dead_count_by_kind"]["files"], 1)
        finally:
            app.close()

    def test_a_clean_tree_names_nothing(self):
        app = _App({"frontend/src/App.jsx":
                    "import Used from './Used';\nexport default function App(){return <Used/>;}\n",
                    "frontend/src/Used.jsx": "export default function Used(){return null;}\n"})
        try:
            s = _coverage_summary(self.reg, app.root)
            self.assertEqual(s.get("dead_names") or [], [])
        finally:
            app.close()

    def test_the_name_list_is_bounded(self):
        files = {"frontend/src/App.jsx": "export default function App(){return null;}\n"}
        for i in range(40):
            files[f"frontend/src/components/Orphan{i}.jsx"] = f"export default function O{i}(){{}}\n"
        app = _App(files)
        try:
            s = _coverage_summary(self.reg, app.root)
            self.assertEqual(s["dead_count_by_kind"]["files"], 40)
            self.assertLessEqual(len(s.get("dead_names") or []), 20,
                                 "an unbounded name list would blow up the blocker string")
        finally:
            app.close()


class TheBlockerNamesThem(unittest.TestCase):
    """Asserted on the real blocker string, not on a source window.

    The first version of this case read a byte slice around the message literal, and #943's
    ratchet rejected it on the spot — *"a window sized in bytes breaks when a COMMENT grows"* —
    while this commit was adding a long comment three lines above the slice. The behaviour is
    what matters anyway: build the report and read what the gate actually says."""

    def setUp(self):
        self.hubdir = Path(tempfile.mkdtemp(prefix="hub_1086b_"))
        self.reg = HubRegistry(self.hubdir)

    def tearDown(self):
        shutil.rmtree(self.hubdir, ignore_errors=True)

    def _blocker(self, app_root):
        from multi_agent.runtime.deliverability import compute_deliverability
        rep = compute_deliverability(self.reg, app_root)
        return next((b for b in (rep.blockers or []) if "dead artifact(s)" in b), "")

    def test_the_blocker_string_carries_the_names(self):
        app = _App({"frontend/src/App.jsx": "export default function App(){return null;}\n",
                    "frontend/src/components/Orphan.jsx": "export default function O(){}\n"})
        try:
            b = self._blocker(app.root)
            self.assertTrue(b, "no dead-artifact blocker was produced")
            self.assertIn("files=1", b, "#1042's kinds breakdown regressed")
            self.assertIn("Orphan.jsx", b, f"the blocker still names nothing: {b}")
        finally:
            app.close()

    def test_many_dead_files_do_not_blow_the_string_up(self):
        files = {"frontend/src/App.jsx": "export default function App(){return null;}\n"}
        for i in range(40):
            files[f"frontend/src/components/Orphan{i}.jsx"] = f"export default function O{i}(){{}}\n"
        app = _App(files)
        try:
            b = self._blocker(app.root)
            self.assertIn("files=40", b)
            self.assertLess(len(b), 1200, "the name list is not capped")
        finally:
            app.close()


if __name__ == "__main__":
    unittest.main()
