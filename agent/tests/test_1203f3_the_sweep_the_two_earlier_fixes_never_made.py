r"""#1203f3: the remaining build-integrity repairs reported writes #1202cw had refused.

#317 fixed this at one site ("it said `normalized: [12 files]` while writing none of them").
#1202iy fixed it at a second, with the measurement that makes the shape unmistakable: r133
logged "#1202sd rewrote 1 <Route path>" 38 times over 1h45m, always the same route, while the
DELIVERED App.jsx still carried the broken path. An identical line repeating is the proof that
nothing was written -- a landed repair removes its own precondition.

Neither fix was swept across the siblings. Harvesting the `#1202cw refused ... from <site>`
lines across the corpus names exactly eight functions, six of which still called
`_fw_write_1202cw` as a bare statement and recorded success on the next line. #1203f2 took the
two missing-export repairs; this is the rest.

Each declaration below rests on a condition the FRAMEWORK computes, not on a judgement of
mine, because a predicate I invent over-matches:

  * the nav mount only touches a page carrying the framework's own `data-projected=` marker,
    so it is the projector revising its own output -- #1202cw calls it the lane's only because
    ownership is decided by DIRECTORY and projected pages live in src/pages/;
  * the token-key repair is the same subject #317 already declares at a sibling site;
  * the api-path rewrite fires only where exactly ONE contract route can match;
  * the two dedupe repairs remove only what their dedupe function proved redundant and route
    everything else to `conflicts`.

MEASURED HARM, in delivered apps: the nav mount was refused 32 times across 8 runs. Checking
the DELIVERED tree of each, r124 and r138 ship 7 refused pages that still do not render the
shell their siblings do. All four of r138's -- for_you, messages_dm_empty,
notifications_activity, live_discover -- are in that run's `visual_screens_below` (7 screens,
blocking average 0.1457), by the mechanism the function's own docstring measured on r139: two
projected pages differing in one `<TopNav />` line scored 0.28 against 0.85. The other six runs
are not counted either way: this check reads the FINAL page set, and the dominance gate is
evaluated per call, so a run that fails the gate at delivery may well have passed it when the
refusal happened. 7 is the floor, not the total.
"""
import sys
import tempfile
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent))
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

from multi_agent.runtime import frontend_scaffold as fs           # noqa: E402
from multi_agent.runtime import path_routed_workspace as prw      # noqa: E402


def _fe(files):
    """A frontend tree at the shape real runs have, so the guard actually engages."""
    d = Path(tempfile.mkdtemp()) / "app" / "frontend"
    for rel, txt in files.items():
        p = d / "src" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(txt, encoding="utf-8")
    return d


def _reset():
    for b in prw._LANE_CLOBBERS_1202CW.values():
        b.clear()


_SHELL = "export default function Shell(){ return null }\n"


def _nav_tree():
    """Three pages import Shell; one PROJECTED page does not."""
    files = {"components/Shell.jsx": _SHELL}
    for i in range(3):
        files["pages/Sib%dPage.jsx" % i] = (
            "import Shell from '../components/Shell.jsx';\n"
            "export default function Sib%d(){ return <Shell/> }\n" % i)
    files["pages/Lonely.jsx"] = (
        "import React from 'react';\n"
        "export default function Lonely(){\n"
        '  return (<div data-projected="ref" className="flex min-h-screen">\n'
        "    <main>x</main>\n"
        "  </div>);\n"
        "}\n")
    return _fe(files)


class TheNavMountLandsOnItsOwnProjectedPage(unittest.TestCase):
    def setUp(self):
        _reset()

    def test_the_mount_lands(self):
        fe = _nav_tree()
        res = fs.mount_shared_nav_on_projected_pages(fe)
        self.assertEqual(res.get("nav"), "Shell", res)
        self.assertIn("Lonely", res.get("mounted") or [], res)
        src = (fe / "src" / "pages" / "Lonely.jsx").read_text(encoding="utf-8")
        self.assertIn("<Shell", src, "the nav was not mounted on the projected page")
        self.assertIn("components/Shell.jsx", src, "the import was not added")

    def test_the_landing_is_declared_not_refused(self):
        fe = _nav_tree()
        fs.mount_shared_nav_on_projected_pages(fe)
        led = prw.lane_clobbers_1202cw()
        self.assertFalse(led["refused"], led["refused"])
        self.assertTrue(any("Lonely.jsx" in k for k in led["declared"]), led)

    def test_a_page_without_the_marker_is_still_never_touched(self):
        """The declaration must not widen WHICH pages this pass may write."""
        fe = _nav_tree()
        plain = fe / "src" / "pages" / "Plain.jsx"
        plain.write_text("import React from 'react';\n"
                         "export default function Plain(){ return <div><main/></div> }\n",
                         encoding="utf-8")
        before = plain.read_text(encoding="utf-8")
        fs.mount_shared_nav_on_projected_pages(fe)
        self.assertEqual(plain.read_text(encoding="utf-8"), before,
                         "a page with no projected marker is lane work and must stand")

    def test_a_refused_mount_is_reported_as_unmounted(self):
        fe = _nav_tree()
        real = fs._fw_write_1202cw
        fs._fw_write_1202cw = lambda *a, **k: False
        try:
            res = fs.mount_shared_nav_on_projected_pages(fe)
        finally:
            fs._fw_write_1202cw = real
        self.assertFalse(res.get("mounted"), "claimed a mount it did not write: %r" % (res,))
        self.assertIn("Lonely", res.get("unmounted") or [], res)


class TheTokenKeyRepairLands(unittest.TestCase):
    def setUp(self):
        _reset()

    def _tree(self):
        return _fe({
            "services/api.js":
                "const TOKEN_KEY = 'tiktok_token';\n"
                "export function getToken(){ return localStorage.getItem(TOKEN_KEY); }\n",
            "pages/LoginPage.jsx":
                "export default function LoginPage(){\n"
                "  localStorage.setItem('access_token', 't');\n"
                "  return null;\n"
                "}\n",
        })

    def test_the_extra_key_is_written(self):
        fe = self._tree()
        res = fs.repair_token_key_mismatch_1108(fe)
        self.assertTrue(res.get("added"), res)
        self.assertFalse(res.get("unwritten"), res)
        src = (fe / "src" / "pages" / "LoginPage.jsx").read_text(encoding="utf-8")
        self.assertIn("tiktok_token", src, "the read-only key is still never written")
        self.assertIn("'access_token'", src, "the lane's own write was lost")

    def test_a_refusal_is_reported_not_claimed(self):
        fe = self._tree()
        real = fs._fw_write_1202cw
        fs._fw_write_1202cw = lambda *a, **k: False
        try:
            res = fs.repair_token_key_mismatch_1108(fe)
        finally:
            fs._fw_write_1202cw = real
        self.assertFalse(res.get("added"), "claimed keys it did not write: %r" % (res,))
        self.assertTrue(res.get("unwritten"), res)


class TheDedupeRepairsLand(unittest.TestCase):
    def setUp(self):
        _reset()

    def test_duplicate_imports_are_collapsed_on_a_lane_file(self):
        fe = _fe({"App.jsx":
                  "import React from 'react';\n"
                  "import { useState } from 'react';\n"
                  "import { useState } from 'react';\n"
                  "export default function App(){ return null }\n"})
        res = fs.repair_frontend_duplicate_imports(fe)
        src = (fe / "src" / "App.jsx").read_text(encoding="utf-8")
        self.assertEqual(src.count("useState"), 1,
                         "the duplicate binding still breaks the build:\n%s" % src)
        self.assertTrue(res.get("repaired"), res)

    def test_a_refused_dedupe_is_announced_as_a_standing_conflict(self):
        fe = _fe({"App.jsx":
                  "import React from 'react';\n"
                  "import { useState } from 'react';\n"
                  "import { useState } from 'react';\n"
                  "export default function App(){ return null }\n"})
        real = fs._fw_write_1202cw
        fs._fw_write_1202cw = lambda *a, **k: False
        try:
            res = fs.repair_frontend_duplicate_imports(fe)
        finally:
            fs._fw_write_1202cw = real
        self.assertFalse(res.get("repaired"), "claimed a dedupe it did not write: %r" % (res,))
        self.assertTrue(any("#1202cw refused" in c for c in res.get("conflicts") or []), res)


class EverySiteMeasuredRefusedIsNowAccountedFor(unittest.TestCase):
    """The sweep, not a list of examples (#1202tb): every call that hands its result to the
    caller must have looked at what came back."""

    def test_no_measured_site_discards_its_write_result(self):
        import ast
        p = (THIS_DIR.parent / "env_generator" / "llm_generator" / "multi_agent" / "runtime"
             / "frontend_scaffold.py")
        tree = ast.parse(p.read_text(encoding="utf-8"))
        # the eight functions the corpus logs actually caught being refused
        MEASURED = {
            "mount_shared_nav_on_projected_pages", "repair_token_key_mismatch_1108",
            "repair_frontend_missing_local_exports", "repair_frontend_named_default_imports",
            "repair_frontend_unmatchable_routes_1202sd", "repair_frontend_duplicate_declarations",
            "repair_frontend_duplicate_imports", "reconcile_frontend_api_paths",
        }
        bare = []
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)): continue
            if fn.name not in MEASURED: continue
            for node in ast.walk(fn):
                if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
                    continue
                f = node.value.func
                if (getattr(f, "id", None) or getattr(f, "attr", None)) in (
                        "_fw_write_1202cw", "_fw_append_1203f2"):
                    bare.append("%s:%d" % (fn.name, node.lineno))
        self.assertEqual(bare, [],
                         "these sites still discard what the guard returned, so they can "
                         "report a repair that never happened: %s" % bare)


if __name__ == "__main__":
    unittest.main()
