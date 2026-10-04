r"""#1203f2: a build-integrity repair reported `repaired` for a write #1202cw refused.

`repair_frontend_missing_local_exports` exists for ONE input: a lane module that is
imported for a name it does not export, which HARD-fails Rollup ("X is not exported by
Y") → the frontend image will not build → docker_up FAIL → no successful run → no
delivery. Its two write sites called `_fw_write_1202cw` as a bare statement and appended
to `result["repaired"]` on the next line, so the return value never decided anything.

#1202cw refuses a framework write onto a lane-owned file unless the site declares why.
The target of this repair is lane-owned BY DEFINITION, so the refusal is the normal case
and it is PERMANENT -- #1202cw's "let the next tick try" never arrives, because the next
tick meets the same condition. Measured over the corpus: 31 "Frontend missing local
exports stubbed" claims across 8 runs, of which 2 landed; r154 refused one file 25 times
and announced it once (the warning is per-key-first-hit) while saying "stubbed" 4 times
for the SAME name -- the identical repetition is itself the proof nothing was written.

The fix is not to omit the claim, which would read as "nothing needed repairing" and
trade one silence for another. It is two things:

  * These writes APPEND -- `tgt_src.rstrip() + "\n" + lines` keeps every byte the lane
    wrote -- so #1202cw's concern does not apply to them, and `framework_append_1203f2`
    lets them say so in a way that is CHECKED against the file on disk rather than
    asserted by the caller.
  * A write that still does not land goes to `result["unwritten"]`, which heal_pipeline
    announces as a standing build-breaker, the way #1202cb already announces the case
    where no repair is possible.

`repair_frontend_named_default_imports` REWRITES import statements rather than appending,
so it cannot earn the declaration; its refusals join the `unrepairable` list #1202cb
already publishes.

WHY THE SUITE COULD NOT SEE THIS: `test_local_export_reexport_drift.py` builds its
fixture at `<tmp>/src/App.jsx`. `_app_relative_1202cw` finds no `app/` segment there, so
`path_is_lane_owned_1202cw` is False and the guard never engages. The regression test
proved the repair works in the one configuration where nothing could refuse it. Every
tree below is rooted at `<tmp>/app/frontend/`, and `test_the_fixture_is_lane_owned`
pins that so it cannot drift back.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from env_generator.llm_generator.multi_agent.runtime import frontend_scaffold as fs
from env_generator.llm_generator.multi_agent.runtime import path_routed_workspace as prw


def _fe(files):
    """A frontend tree at the shape real runs have: <tmp>/app/frontend/src/..."""
    d = Path(tempfile.mkdtemp()) / "app" / "frontend"
    for rel, txt in files.items():
        p = d / "src" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(txt, encoding="utf-8")
    return d


def _ledger_reset():
    for b in prw._LANE_CLOBBERS_1202CW.values():
        b.clear()


class FixtureEngagesTheGuard(unittest.TestCase):
    def test_the_fixture_is_lane_owned(self):
        """The whole defect lives behind this predicate; a fixture that is False here
        cannot observe it, which is why the existing drift test never did."""
        fe = _fe({"components/Widget.jsx": "const Thing = 1;\n"})
        target = fe / "src" / "components" / "Widget.jsx"
        self.assertTrue(prw.path_is_lane_owned_1202cw(target),
                        "fixture is outside app/frontend/ -- the guard will not engage "
                        "and this file would prove nothing")


class TheAppendNowLands(unittest.TestCase):
    def setUp(self):
        _ledger_reset()

    def test_a_reexport_lands_on_a_lane_owned_module(self):
        fe = _fe({
            "components/Widget.jsx":
                "import { createContext } from 'react';\n"
                "const ThingCtx = createContext();\n"
                "function Widget(){ return null; }\n"
                "export default Widget;\n",
            "pages/UsesIt.jsx":
                "import { ThingCtx } from '../components/Widget';\n"
                "export default function UsesIt(){ return null; }\n",
        })
        res = fs.repair_frontend_missing_local_exports(fe)
        src = (fe / "src" / "components" / "Widget.jsx").read_text(encoding="utf-8")
        self.assertIn("export { ThingCtx };", src,
                      "the re-export did not land on a lane-owned module")
        self.assertTrue(res.get("reexported"), res)
        self.assertFalse(res.get("unwritten"), res)

    def test_a_missing_name_is_stubbed_on_a_lane_owned_module(self):
        fe = _fe({
            "components/Icons.jsx": "export const IconHome = () => null;\n",
            "pages/UsesIt.jsx":
                "import { IconHome, IconMissing } from '../components/Icons';\n"
                "export default function UsesIt(){ return null; }\n",
        })
        res = fs.repair_frontend_missing_local_exports(fe)
        src = (fe / "src" / "components" / "Icons.jsx").read_text(encoding="utf-8")
        self.assertIn("IconMissing", src, "the stub did not land")
        self.assertIn("export const IconHome", src,
                      "the lane's own export was lost -- an append must keep every byte")
        self.assertTrue(res.get("repaired"), res)
        self.assertFalse(res.get("unwritten"), res)

    def test_the_landing_is_recorded_as_declared_not_refused(self):
        fe = _fe({
            "components/Icons.jsx": "export const IconHome = () => null;\n",
            "pages/UsesIt.jsx":
                "import { IconMissing } from '../components/Icons';\n"
                "export default function UsesIt(){ return null; }\n",
        })
        fs.repair_frontend_missing_local_exports(fe)
        led = prw.lane_clobbers_1202cw()
        self.assertFalse(led["refused"],
                         "#1202cw's own note says `refused` should stay empty; a declared "
                         "append must not land there: %r" % (led["refused"],))
        self.assertTrue(any("Icons.jsx" in k for k in led["declared"]),
                        "the census must still SEE the write: %r" % (led,))


class TheDeclarationIsEarnedNotAsserted(unittest.TestCase):
    def setUp(self):
        _ledger_reset()

    def test_a_non_additive_text_is_refused(self):
        fe = _fe({"components/Widget.jsx": "const Thing = 1;\nexport default Thing;\n"})
        target = fe / "src" / "components" / "Widget.jsx"
        before = target.read_text(encoding="utf-8")
        ok = prw.framework_append_1203f2(
            target, "export const Thing = 2;\n", ticket="#1203f2 test")
        self.assertFalse(ok, "a rewrite must not pass as an append")
        self.assertEqual(target.read_text(encoding="utf-8"), before,
                         "a refused append must not fall back to a raw write")

    def test_the_check_reads_the_file_not_the_callers_idea_of_it(self):
        """A caller holding a STALE read must not be able to argue its way into a
        clobber: the predicate is about the bytes on disk."""
        fe = _fe({"components/Widget.jsx": "LANE WROTE MORE SINCE\nconst Thing = 1;\n"})
        target = fe / "src" / "components" / "Widget.jsx"
        stale = "const Thing = 1;\n"            # what the caller read a moment ago
        ok = prw.framework_append_1203f2(
            target, stale.rstrip() + "\nexport { Thing };\n", ticket="#1203f2 test")
        self.assertFalse(ok, "appending to a stale read would drop the lane's newer bytes")
        self.assertIn("LANE WROTE MORE SINCE", target.read_text(encoding="utf-8"))

    def test_a_true_append_is_allowed(self):
        fe = _fe({"components/Widget.jsx": "const Thing = 1;\n"})
        target = fe / "src" / "components" / "Widget.jsx"
        cur = target.read_text(encoding="utf-8")
        ok = prw.framework_append_1203f2(
            target, cur.rstrip() + "\nexport { Thing };\n", ticket="#1203f2 test")
        self.assertTrue(ok)
        after = target.read_text(encoding="utf-8")
        self.assertTrue(after.startswith("const Thing = 1;"), after)
        self.assertIn("export { Thing };", after)

    def test_an_absent_file_is_an_ordinary_first_write(self):
        d = Path(tempfile.mkdtemp()) / "app" / "frontend" / "src" / "components"
        ok = prw.framework_append_1203f2(
            d / "New.jsx", "export const A = 1;\n", ticket="#1203f2 test")
        self.assertTrue(ok, "nothing to preserve must not read as a clobber")


class AnUnlandedRepairSaysSo(unittest.TestCase):
    def setUp(self):
        _ledger_reset()

    def test_unwritten_replaces_the_repaired_claim(self):
        fe = _fe({
            "components/Icons.jsx": "export const IconHome = () => null;\n",
            "pages/UsesIt.jsx":
                "import { IconMissing } from '../components/Icons';\n"
                "export default function UsesIt(){ return null; }\n",
        })
        real = fs._fw_append_1203f2
        fs._fw_append_1203f2 = lambda *a, **k: False
        try:
            res = fs.repair_frontend_missing_local_exports(fe)
        finally:
            fs._fw_append_1203f2 = real
        self.assertFalse(res.get("repaired"),
                         "claimed a stub it did not write: %r" % (res,))
        self.assertTrue(res.get("unwritten"), res)
        self.assertTrue(any("Icons.jsx" in str(x) for x in res["unwritten"]), res)

    def test_a_refused_named_default_rewrite_becomes_an_unrepairable_breaker(self):
        fe = _fe({
            "components/NavBar.jsx":
                "function NavBar(){ return null; }\nexport default NavBar;\n",
            "pages/UsesIt.jsx":
                "import { NavBar } from '../components/NavBar';\n"
                "export default function UsesIt(){ return null; }\n",
        })
        real = fs._fw_write_1202cw
        fs._fw_write_1202cw = lambda *a, **k: False
        try:
            res = fs.repair_frontend_named_default_imports(fe)
        finally:
            fs._fw_write_1202cw = real
        self.assertFalse(res.get("fixed"),
                         "claimed a rewrite it did not write: %r" % (res,))
        self.assertTrue(res.get("unrepairable"), res)
        self.assertTrue(any("#1202cw refused" in u for u in res["unrepairable"]), res)


class TheAnnouncementReachesTheReader(unittest.TestCase):
    def test_heal_pipeline_publishes_unwritten(self):
        """Structural, not positional: the loop must read the key the repair writes and
        hand it to the logger. A fact that reaches only the repair's return value has
        not reached anyone."""
        import ast
        p = (ROOT / "env_generator" / "llm_generator" / "multi_agent" / "runtime"
             / "heal_pipeline.py")
        tree = ast.parse(p.read_text(encoding="utf-8"))
        found = False
        for node in ast.walk(tree):
            if not isinstance(node, ast.For):
                continue
            it = ast.dump(node.iter)
            if "'unwritten'" not in it and '"unwritten"' not in it:
                continue
            body = ast.dump(ast.Module(body=node.body, type_ignores=[]))
            if "warning" in body and "1203f2" in body:
                found = True
        self.assertTrue(found,
                        "nothing hands `unwritten` to the logger, so an unlanded "
                        "build-breaker repair is still silent")


if __name__ == "__main__":
    unittest.main()
