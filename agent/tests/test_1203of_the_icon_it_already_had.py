r"""#1203of: the same character, in a project that already has the icon.

`#1203kd` returns [] "as soon as any file imports a real icon library, because a project that
has one made a deliberate choice about the glyph that is left". That sentence is a HYPOTHESIS,
and the corpus falsifies it.

MEASURED over the 104 delivered frontends: 25 import a library and 16 of those still use a
character as an icon -- 92 sites one import anywhere in the tree switches `#1203kd` off for. 63
are a glyph whose concept the set offers, and in 37 the app ALREADY IMPORTS THAT VERY ICON:
r115's `TikTokUI.jsx` imports `Heart` and writes `♥`; `netflix-local-r8` imports `Play` and
writes `▶` on five pages while `LanguageFilters.jsx` imports `ChevronDown` and writes `▾`.

NOT HISTORICAL: r183 writes `♪` beside an imported `Music2`, r180 the same with `Music`, and
r190's `profile-fix.css` draws the three profile tabs as `▦`, `⚑`, `♡` in `::before` content
while the project imports lucide. The user's bar names this axis as the weakest thing shipped --
iconography mean 0.577 over 251 PASSING screens, min 0.22.

★ THE MAP ONLY HAS TO BE CORRECT, NOT COMPLETE. netflix-r7's `🍿` has no lucide equivalent and
is deliberately never reported: a missing entry costs a missed finding, never a wrong one, and a
false blocker here is what #566j already cost this repo.
"""
import inspect
import tempfile
import textwrap
import unittest
from pathlib import Path

from env_generator.llm_generator.multi_agent.runtime import scaffolder as SC
from env_generator.llm_generator.multi_agent.runtime.frontend_audit import (
    _GLYPH_LIBRARY_ICON_1203OF as MAP,
    _imported_icon_names_1203of as imported_names,
    glyph_icon_findings_1203kd as kd,
    glyph_icons_with_a_real_icon_available_1203of as of_,
)


def _of_try_source() -> str:
    """The source of the `try` that wraps the #1203of dispatch, via the AST.

    Not a slice: #943 forbids a fixed-width source window in a test, and it failed this file
    on the first run for exactly that (`src[i:i+2600]`).
    """
    import ast
    src = inspect.getsource(SC)
    tree = ast.parse(src)
    parents = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    target = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(
                node.func, "id", getattr(node.func, "attr", "")) == "_gi1203of":
            target = node
    assert target is not None, "nothing calls the #1203of detector"
    cur, tries = parents.get(target), []
    while cur is not None:
        if isinstance(cur, ast.Try):
            tries.append(cur)
        cur = parents.get(cur)
    node = min(tries, key=lambda n: (n.end_lineno or 0) - n.lineno)
    lines = src.splitlines(True)
    return "".join(lines[node.lineno - 1:node.end_lineno])


class _Tree(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.src = Path(self._tmp.name) / "src"
        self.src.mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, rel, body):
        p = self.src / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(body), encoding="utf-8")


class TheGlyphIsReportedWhenTheIconIsThere(_Tree):
    def test_the_app_already_imports_that_very_icon(self):
        """r183's case: `♪` in a file whose project imports `Music2`."""
        self.write("TikTokUI.jsx", """
            import { Music2, Home } from 'lucide-react';
            export const Note = () => <span className="note">♪</span>;
        """)
        rows = of_(self.src)
        self.assertEqual(len(rows), 1, rows)
        self.assertIn("ALREADY IMPORTS `Music2`", rows[0])
        self.assertIn("♪", rows[0])

    def test_the_icon_is_merely_available_in_the_set(self):
        self.write("Page.jsx", """
            import { Home } from 'lucide-react';
            export const Like = () => <button>♡</button>;
        """)
        rows = of_(self.src)
        self.assertEqual(len(rows), 1, rows)
        self.assertIn("`Heart` is in the icon set", rows[0])

    def test_the_import_and_the_glyph_may_be_in_different_files(self):
        """r8's shape: `Play` imported in one page, `▶` written in four others. The claim is
        about what the PROJECT has in scope."""
        self.write("Imports.jsx", "import { Play } from 'lucide-react';\n")
        self.write("Movies.jsx", "export const P = () => <span>▶</span>;\n")
        rows = of_(self.src)
        self.assertEqual(len(rows), 1, rows)
        self.assertIn("ALREADY IMPORTS `Play`", rows[0])

    def test_a_css_pseudo_element_counts(self):
        """r190's three profile tabs are `::before { content: '▦' }` in a minified file."""
        self.write("App.jsx", "import { Home } from 'lucide-react';\n")
        self.write("profile-fix.css",
                   ".a::before{content:'▦'}.b::before{content:'⚑'}.c::before{content:'♡'}\n")
        rows = of_(self.src)
        self.assertEqual(len(rows), 3, rows)
        self.assertTrue(all("LayoutGrid" in r or "Flag" in r or "Heart" in r for r in rows))

    def test_the_fragment_is_centred_on_the_glyph(self):
        """A minified stylesheet's first 90 characters never showed the glyph the finding is
        about -- the rule `#1203kt` established, now shared with this check."""
        self.write("App.jsx", "import { Home } from 'lucide-react';\n")
        # ONE minified line, with the glyph past column 200 -- the first version put it on a
        # SHORT second line, where the whole line is returned and the centring never runs, so
        # mutation OF6 (`col = 0`) read MISSED against a test that was not exercising it.
        self.write("big.css",
                   ".x{" + "padding:0;" * 25 + "}.y::before{content:'♡'}.z{color:red}\n")
        rows = [r for r in of_(self.src) if "big.css" in r]
        self.assertEqual(len(rows), 1, rows)
        frag = rows[0].split(" — ")[0].split(": ", 2)[-1]
        self.assertIn("♡", frag)
        self.assertTrue(frag.lstrip().startswith("…"),
                        "the fragment starts at the line head, so the window is not centred: "
                        "%r" % frag)


class WhatItStaysSilentAbout(_Tree):
    def test_a_project_with_no_icon_library_is_kd_s_half(self):
        """#1032: reporting it here too would give one defect two owners."""
        self.write("Page.jsx", "export const Like = () => <button>♡</button>;\n")
        self.assertEqual(of_(self.src), [])
        self.assertTrue(kd(self.src), "kd should own this one")

    def test_the_two_checks_never_both_report(self):
        self.write("Page.jsx", """
            import { Home } from 'lucide-react';
            export const Like = () => <button>♡</button>;
        """)
        self.assertTrue(of_(self.src))
        self.assertEqual(kd(self.src), [])

    def test_a_glyph_with_no_library_equivalent_is_not_reported(self):
        """netflix-r7's `🍿`. A missing map entry costs a missed finding, never a wrong one."""
        self.write("Page.jsx", """
            import { Home } from 'lucide-react';
            export const Snack = () => <span>🍿</span>;
        """)
        self.assertEqual(of_(self.src), [])

    def test_a_glyph_inside_a_sentence_is_copy(self):
        """Inherited from #1203kd's shape: the glyph must be the whole content."""
        self.write("Page.jsx", """
            import { Home } from 'lucide-react';
            export const C = () => <p>We ♡ our creators and so will you</p>;
        """)
        self.assertEqual(of_(self.src), [])

    def test_a_missing_directory_returns_empty(self):
        self.assertEqual(of_(Path("/nope/src")), [])

    def test_an_unreadable_file_does_not_stop_the_scan(self):
        self.write("App.jsx", "import { Home } from 'lucide-react';\n")
        (self.src / "broken.css").write_bytes(b"\xff\xfe\x00bad")
        self.write("Page.jsx", "export const L = () => <i>♡</i>;\n")
        self.assertTrue(of_(self.src))


class TheCutDeclaresItself(_Tree):
    def test_a_capped_list_says_how_many_it_is_showing(self):
        self.write("App.jsx", "import { Home } from 'lucide-react';\n")
        body = ["export const P = () => <div>"]
        body += ["<span>♡</span>"] * 20
        body.append("</div>;")
        self.write("Many.jsx", "".join(body) + "\n")
        rows = of_(self.src, limit=4)
        self.assertEqual(len(rows), 5, rows)
        self.assertIn("4 of 20", rows[-1])


class TheMapIsCorrectRatherThanComplete(unittest.TestCase):
    def test_every_entry_names_at_least_one_icon(self):
        for glyph, names in MAP.items():
            with self.subTest(glyph=glyph):
                self.assertTrue(names)
                self.assertTrue(all(n and n[0].isupper() for n in names), names)

    def test_the_corpus_glyphs_that_matter_are_covered(self):
        """The ones the measurement actually found behind a library import."""
        for ch in ("♡", "♥", "♪", "▶", "✓", "⌄", "▾",
                   "⚑", "▦", "⌗", "↗", "✎"):
            with self.subTest(glyph=ch):
                self.assertIn(ch, MAP)

    def test_a_glyph_with_no_icon_is_absent_on_purpose(self):
        self.assertNotIn("\U0001F37F", MAP)       # 🍿, netflix-r7


class TheImportReaderReadsTheProject(unittest.TestCase):
    def test_named_imports_and_aliases(self):
        got = imported_names([(Path("a.jsx"),
                               "import { Heart, Play as Go } from 'lucide-react';")])
        self.assertEqual(got, {"Heart", "Play"})

    def test_other_libraries_count_too(self):
        got = imported_names([(Path("a.jsx"),
                               "import { FiHeart } from 'react-icons/fi';")])
        self.assertIn("FiHeart", got)

    def test_an_unrelated_import_does_not(self):
        self.assertEqual(imported_names([(Path("a.jsx"),
                                          "import { useState } from 'react';")]), set())


class SomebodyIsTold(unittest.TestCase):
    def test_the_scaffolder_files_a_task(self):
        src = inspect.getsource(SC)
        self.assertIn("glyph_icons_with_a_real_icon_available_1203of", src)
        self.assertIn('_sc1203of("task:glyph_icons_with_library"', src)

    def test_it_does_not_share_its_state_key_with_kd(self):
        """A shared key would make one check's rows suppress the other's task."""
        src = inspect.getsource(SC)
        self.assertIn('_sc1203kd("task:glyph_icons"', src)
        self.assertNotIn('_sc1203of("task:glyph_icons"', src)

    def test_the_task_names_the_cheap_repair(self):
        """#943: the block is the enclosing `try`, read from the AST — a fixed-width window
        (`src[i:i+2600]`) is what the ratchet forbids, and it caught this file."""
        block = _of_try_source()
        self.assertIn("lucide-react", block)
        self.assertIn("ALREADY IMPORTS", block)

    def test_its_own_try(self):
        import ast
        tree = ast.parse(inspect.getsource(SC))
        parents = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                parents[child] = node
        target = None
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(
                    node.func, "id", getattr(node.func, "attr", "")) == "_gi1203of":
                target = node
        self.assertIsNotNone(target, "nothing calls the #1203of detector")
        cur, tries = parents.get(target), []
        while cur is not None:
            if isinstance(cur, ast.Try):
                tries.append(cur)
            cur = parents.get(cur)
        self.assertTrue(tries, "unguarded (#1201)")
        body = ast.dump(ast.Module(body=tries[0].body, type_ignores=[]))
        self.assertNotIn("glyph_icon_findings_1203kd", body,
                         "it shares a try with #1203kd, so one failing silences the other")


class WhatTheCorpusSays(unittest.TestCase):
    """Named runs only: the decisive already-imported cases, r190's CSS tabs, and controls."""

    _FIRES = ("tiktok-web-r183", "tiktok-web-r190", "netflix-local-r8", "tiktok-web-r115")
    _SILENT = ("tiktok-web-r191", "tiktok-web-r185")

    @classmethod
    def setUpClass(cls):
        cls.corpus = Path(__file__).resolve().parents[2] / "generated"
        if not cls.corpus.is_dir():
            raise unittest.SkipTest("no generated/ corpus on this machine")

    def _src(self, run):
        p = self.corpus / run / "app" / "frontend" / "src"
        return p if p.is_dir() else None

    def test_it_fires_on_the_measured_runs(self):
        checked = 0
        for run in self._FIRES:
            src = self._src(run)
            if src is None:
                continue
            checked += 1
            with self.subTest(run=run):
                self.assertTrue(of_(src), "%s was measured with glyph icons" % run)
        if not checked:
            self.skipTest("no measured run on this disk")

    def test_r183_is_the_decisive_case(self):
        src = self._src("tiktok-web-r183")
        if src is None:
            self.skipTest("r183 is not on this disk")
        self.assertTrue([r for r in of_(src) if "ALREADY IMPORTS" in r],
                        "the already-imported case is what falsifies #1203kd's reason")

    def test_r190_reports_its_css_tabs(self):
        src = self._src("tiktok-web-r190")
        if src is None:
            self.skipTest("r190 is not on this disk")
        rows = of_(src)
        self.assertEqual(len([r for r in rows if ".css" in r]), 3, rows)

    def test_the_controls_stay_silent(self):
        checked = 0
        for run in self._SILENT:
            src = self._src(run)
            if src is None:
                continue
            checked += 1
            with self.subTest(run=run):
                self.assertEqual(of_(src), [])
        if not checked:
            self.skipTest("no control run on this disk")

    def test_no_run_is_reported_by_both_checks(self):
        """#1032 on real data, not only on a fixture."""
        both = []
        for src in sorted(self.corpus.glob("*/app/frontend/src")):
            if of_(src) and kd(src):
                both.append(src.parts[-4])
        self.assertEqual(both, [], "these runs have two owners for one defect: %s" % both)


if __name__ == "__main__":
    unittest.main()
