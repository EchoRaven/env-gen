r"""#1203f5: #576 picked its shell by a count that included imports it cannot replicate.

#576 mounts the app's own shared shell into a projected page that renders none, by emitting

    import Comp from '../components/Comp.jsx';
    ...
    <Comp />

and its docstring says the component is chosen as the one "3 of the lane's own pages already
use" in exactly that form. The count it actually ran was
``re.findall(r"from '\.\./components/([A-Za-z0-9_]+)\.jsx'", txt)`` -- every reference to the
module, NAMED imports included.

r130, in the delivered app: five pages carry `import { Icon } from '../components/icons.jsx'`
and icons.jsx has no `export default`. `icons` therefore ranked first with 5 against a
runner-up of 2, cleared the dominance gate, and the pass would have written
`import icons from '../components/icons.jsx'` into a projected page -- "default is not
exported by src/components/icons.jsx", a HARD Rollup failure that takes the frontend image
down, which is the failure class #578 and the stub repairs exist to prevent. It would also
have emitted `<icons />`, which JSX reads as an unknown HTML element rather than a component.

This never fired because #1202cw refused every write from this site (32 refusals over 8 runs).
#1203f3 earned that site its declaration, so the write now lands -- and a judgement that was
safe only because the write was dropped stops being safe the moment the path opens. Hence the
two readings here: the vote counts only DEFAULT importers, which is the usage being
replicated, and the chosen module is then asked directly whether it has a default export and
whether JSX can even render its name.
"""
import sys
import tempfile
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent))
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

from multi_agent.runtime.frontend_scaffold import (                      # noqa: E402
    mount_shared_nav_on_projected_pages as mount,
    _has_default_export_1203f5 as has_default,
)

_PROJECTED = """import React from 'react';
export default function Lonely() {
  return (
    <div data-projected="ref" className="flex min-h-screen">
      <main className="flex-1"><section>x</section></main>
    </div>
  );
}
"""


def _app(pages, comps):
    fe = Path(tempfile.mkdtemp()) / "frontend"
    (fe / "src" / "pages").mkdir(parents=True)
    (fe / "src" / "components").mkdir(parents=True)
    for name, src in comps.items():
        (fe / "src" / "components" / name).write_text(src, encoding="utf-8")
    for name, src in pages.items():
        (fe / "src" / "pages" / name).write_text(src, encoding="utf-8")
    return fe


def _r130_shape():
    """Five named importers of a default-less module, plus a chromeless projected page."""
    pages = {"Lonely.jsx": _PROJECTED}
    for i in range(5):
        pages["Sib%d.jsx" % i] = (
            "import { Icon } from '../components/icons.jsx';\n"
            "export default function Sib%d(){ return <Icon/> }\n" % i)
    return _app(pages, {"icons.jsx": "export const Icon = () => null;\n"})


class TheVoteCountsOnlyUsagesItCanReplicate(unittest.TestCase):
    def test_the_r130_shape_mounts_nothing(self):
        fe = _r130_shape()
        before = (fe / "src" / "pages" / "Lonely.jsx").read_text(encoding="utf-8")
        res = mount(fe)
        self.assertIsNone(res.get("nav"), res)
        self.assertFalse(res.get("mounted"), res)
        self.assertEqual((fe / "src" / "pages" / "Lonely.jsx").read_text(encoding="utf-8"),
                         before, "wrote a default import of a module that has no default")

    def test_a_named_importer_does_not_outvote_default_importers(self):
        pages = {"Lonely.jsx": _PROJECTED}
        for i in range(5):
            pages["Named%d.jsx" % i] = (
                "import { Icon } from '../components/icons.jsx';\n"
                "export default function N%d(){ return <Icon/> }\n" % i)
        for i in range(3):
            pages["Def%d.jsx" % i] = (
                "import Shell from '../components/Shell.jsx';\n"
                "export default function D%d(){ return <Shell/> }\n" % i)
        fe = _app(pages, {"icons.jsx": "export const Icon = () => null;\n",
                          "Shell.jsx": "export default function Shell(){ return <nav/> }\n"})
        res = mount(fe)
        self.assertEqual(res.get("nav"), "Shell",
                         "the shell the pages actually mount must win: %r" % (res,))
        src = (fe / "src" / "pages" / "Lonely.jsx").read_text(encoding="utf-8")
        self.assertIn("<Shell", src)
        self.assertNotIn("icons", src)

    def test_a_default_and_named_import_on_one_line_still_counts(self):
        """`import Shell, { X } from '...'` IS a default import."""
        pages = {"Lonely.jsx": _PROJECTED}
        for i in range(3):
            pages["Sib%d.jsx" % i] = (
                "import Shell, { Side } from '../components/Shell.jsx';\n"
                "export default function S%d(){ return <Shell><Side/></Shell> }\n" % i)
        fe = _app(pages, {"Shell.jsx": "export const Side = () => null;\n"
                                       "export default function Shell(){ return <nav/> }\n"})
        self.assertEqual(mount(fe).get("nav"), "Shell")


class TheChosenModuleIsAskedDirectly(unittest.TestCase):
    def _three_importers(self, comp, comp_src):
        pages = {"Lonely.jsx": _PROJECTED}
        for i in range(3):
            pages["Sib%d.jsx" % i] = (
                "import %s from '../components/%s.jsx';\n"
                "export default function S%d(){ return <%s/> }\n" % (comp, comp, i, comp))
        return _app(pages, {"%s.jsx" % comp: comp_src})

    def test_a_lowercase_module_is_not_mounted(self):
        fe = self._three_importers("widgets",
                                   "export default function widgets(){ return null }\n")
        res = mount(fe)
        self.assertIsNone(res.get("nav"), res)
        self.assertIn("HTML tag", res.get("skipped") or "", res)

    def test_a_module_without_a_default_export_is_not_mounted(self):
        """Three pages default-import it anyway -- a frontend that is already broken must
        not be the reason a second file breaks."""
        fe = self._three_importers("Shell", "export const Shell = () => null;\n")
        res = mount(fe)
        self.assertIsNone(res.get("nav"), res)
        self.assertIn("default export", res.get("skipped") or "", res)

    def test_the_positive_control_still_mounts(self):
        fe = self._three_importers("Shell",
                                   "export default function Shell(){ return <nav/> }\n")
        res = mount(fe)
        self.assertEqual(res.get("nav"), "Shell", res)
        self.assertIn("Lonely", res.get("mounted") or [], res)


class TheDefaultExportTest(unittest.TestCase):
    def _mod(self, src):
        p = Path(tempfile.mkdtemp()) / "X.jsx"
        p.write_text(src, encoding="utf-8")
        return p

    def test_export_default_function(self):
        self.assertTrue(has_default(self._mod("export default function X(){}\n")))

    def test_export_braced_as_default(self):
        self.assertTrue(has_default(self._mod("const X=1;\nexport { X as default };\n")))

    def test_named_only(self):
        self.assertFalse(has_default(self._mod("export const X = 1;\n")))

    def test_the_word_default_in_a_comment_is_not_an_export(self):
        self.assertFalse(has_default(self._mod("// export default X was removed\n"
                                               "export const X = 1;\n")))

    def test_an_unreadable_module_is_not_mountable(self):
        d = Path(tempfile.mkdtemp())
        self.assertFalse(has_default(d / "Gone.jsx"))


if __name__ == "__main__":
    unittest.main()
