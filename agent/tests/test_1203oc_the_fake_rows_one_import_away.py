r"""#1203oc: the same fabrication, one import away from #175's eyes.

#175 blocks `place.rating || '4.5'` and its own docstring names the bar -- "the user's
no-placeholder/mock bar". Its two regexes require the fabricated value to be a QUOTED LITERAL
in the same expression, so moving the literal into a module clears the gate and changes
nothing about what the viewer is shown.

r190 CARRIES BOTH IN ONE DELIVERY: its log has a single #175 rewrite
(`item.text || 'shared new posts you may like'`) while three pages read `seededVideos` out of
`lib/staticData.js` -- `MessagesDmEmptyPage` renders `video ? {…} : seededVideos[2]`, so a
feed call that returns nothing shows "Lina Park" and a caption nobody wrote.

MEASURED, 14 sites in 4 of the 104 delivered frontends (r155 6, r131 3, r190 3, r157 2), the
newest run among them. r155's `VideoFeed` sets `onError` to `videos[0].thumbnail_url`, which
paints over the exact 404 #1202g9/#1203nq exist to surface.

★ THE VOCABULARY IS THE APP'S OWN SCHEMA. A first version scored the literal's keys against a
hand-written content word list and reported FOUR icon maps, because an icon's key is literally
`comment` or `sound` (r103 `navIcons`, r121 `assets`, r56 `ICONS`). Reading `models.py`
through `model_columns_from_models_py` asks the only question that matters -- are these the
columns of a table this app serves -- and carries no vertical vocabulary.
"""
import ast
import inspect
import re
import tempfile
import textwrap
import unittest
from pathlib import Path

from env_generator.llm_generator.multi_agent.runtime import frontend_audit as FA
from env_generator.llm_generator.multi_agent.runtime.frontend_audit import (
    _MIN_RECORDS_1203OC,
    _MIN_SHARED_COLUMNS_1203OC,
    fabricated_record_arrays_1203oc as fab,
    record_arrays_1203oc as arrays,
)

MODELS = textwrap.dedent("""
    class Video(Base):
        __tablename__ = "videos"
        id = Column(Integer, primary_key=True)
        caption = Column(String)
        sound = Column(String)
        username = Column(String)
        thumbnail_url = Column(String)
""")


class _App(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.app = Path(self._tmp.name) / "app"
        self.src = self.app / "frontend" / "src"
        (self.src / "pages").mkdir(parents=True)
        (self.src / "lib").mkdir(parents=True)
        (self.app / "backend").mkdir(parents=True)
        (self.app / "backend" / "models.py").write_text(MODELS, encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, rel, body):
        p = self.src / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(body), encoding="utf-8")
        return p

    def seed_module(self, name="staticData", var="seededVideos"):
        self.write("lib/%s.js" % name, """
            export const %s = [
              {id:'v1', username:'mayarios', caption:'Rooftop count-in', sound:'City Steps'},
              {id:'v2', username:'noahskitchen', caption:'One pan chili', sound:'Pantry'}
            ];
        """ % var)


class TheModuleHopIsReported(_App):
    def test_a_page_that_fetches_and_renders_the_literal(self):
        self.seed_module()
        self.write("pages/MessagesDmEmptyPage.jsx", """
            import { seededVideos } from '../lib/staticData.js';
            import { getVideosFeed } from '../services/api.js';
            export default function P() {
              const creator = video ? {a:1} : seededVideos[2];
              return <div>{creator.caption}</div>;
            }
        """)
        rows = fab(self.app)
        self.assertEqual(len(rows), 1, rows)
        self.assertIn("MessagesDmEmptyPage.jsx:5", rows[0])
        self.assertIn("seededVideos", rows[0])

    def test_the_row_names_the_table_whose_rows_are_faked(self):
        self.seed_module()
        self.write("pages/P.jsx", """
            import { seededVideos } from '../lib/staticData.js';
            import { getVideosFeed } from '../services/api.js';
            export default function P() { return <i>{seededVideos[0].caption}</i>; }
        """)
        self.assertIn("`videos`", fab(self.app)[0])

    def test_the_fragment_contains_the_token_it_reports(self):
        """r157's `creators.map` sits past column 200 of a one-line component, and the first
        version printed the line HEAD -- a row naming a token its own evidence did not hold."""
        self.seed_module()
        pad = "const x = 1; " * 20
        self.write("pages/Wide.jsx", """
            import { seededVideos } from '../lib/staticData.js';
            import { getVideosFeed } from '../services/api.js';
            export default function P() { %s return <i>{seededVideos.map(v=>v.caption)}</i>; }
        """ % pad)
        row = fab(self.app)[0]
        frag = row.split(": `", 1)[1].split("` — ", 1)[0]
        self.assertIn("seededVideos", frag)

    def test_a_same_file_literal_counts_too(self):
        """r157 defines its fabricated `creators` in the component itself; the import hop is
        not what makes it invisible to #175."""
        self.write("pages/Own.jsx", """
            import { getVideosFeed } from '../services/api.js';
            const creators = [
              {username:'a', caption:'one', sound:'s1'},
              {username:'b', caption:'two', sound:'s2'}
            ];
            export default function P() { return <i>{creators.map(c=>c.caption)}</i>; }
        """)
        rows = fab(self.app)
        self.assertEqual(len(rows), 1, rows)
        self.assertIn("creators", rows[0])

    def test_a_literal_defined_but_never_read_is_silent(self):
        """The finding is that fabricated rows are RENDERED, not that they exist. 6 of the 9
        corpus runs that define a record array have no api-calling page reading one."""
        self.write("pages/Own.jsx", """
            import { getVideosFeed } from '../services/api.js';
            const creators = [
              {username:'a', caption:'one', sound:'s1'},
              {username:'b', caption:'two', sound:'s2'}
            ];
            export default function P() { return <i>nothing</i>; }
        """)
        self.assertEqual(fab(self.app), [])

    def test_a_one_line_module_is_still_reported(self):
        """★ The case that killed a guard I had written. A "skip the defining line" check is
        dead for a multi-line literal (the use pattern needs `name[`, a definition reads
        `name = [`) and WRONG for a one-liner, where both sit on the same line."""
        self.write("pages/One.jsx",
                   "import { getVideosFeed } from '../services/api.js';\n"
                   "const videos = [{username:'a', caption:'x', sound:'s'},"
                   "{username:'b', caption:'y', sound:'t'}]; "
                   "const first = videos[0];\n")
        rows = fab(self.app)
        self.assertEqual(len(rows), 1, rows)
        self.assertIn("One.jsx:2", rows[0])


class WhatItDoesNotReport(_App):
    def test_an_icon_map_is_not_a_table_of_rows(self):
        """★ The false positives a content word list produced: an icon's KEY is `comment` or
        `sound`. An object of components is not an array of records."""
        self.write("lib/icons.js", """
            export const navIcons = {comment: 1, sound: 2, caption: 3, username: 4};
        """)
        self.write("pages/P.jsx", """
            import { navIcons } from '../lib/icons.js';
            import { getVideosFeed } from '../services/api.js';
            export default function P() { return <i>{navIcons.comment}</i>; }
        """)
        self.assertEqual(fab(self.app), [])

    def test_ui_configuration_sharing_one_column_name_is_silent(self):
        """r164's `chips` (`label`/`type`/`testid`) is why the floor is two columns."""
        self.write("lib/cfg.js", """
            export const chips = [
              {label:'All activity', type:'all', testid:'t1'},
              {label:'Likes', type:'likes', testid:'t2'}
            ];
        """)
        self.write("pages/P.jsx", """
            import { chips } from '../lib/cfg.js';
            import { getVideosFeed } from '../services/api.js';
            export default function P() { return <i>{chips.map(c=>c.label)}</i>; }
        """)
        self.assertEqual(fab(self.app), [])

    def test_a_component_that_never_calls_the_api_is_silent(self):
        """Narrow on purpose: the claim is that fabricated rows stand where this component's
        OWN call result belongs. A purely static surface is a different finding."""
        self.seed_module()
        self.write("pages/Static.jsx", """
            import { seededVideos } from '../lib/staticData.js';
            export default function P() { return <i>{seededVideos[0].caption}</i>; }
        """)
        self.assertEqual(fab(self.app), [])

    def test_an_array_holding_a_function_is_not_data(self):
        self.write("lib/cols.js", """
            export const columns = [
              {username:'a', caption:'x', render: (r) => r.caption},
              {username:'b', caption:'y', render: (r) => r.username}
            ];
        """)
        self.write("pages/P.jsx", """
            import { columns } from '../lib/cols.js';
            import { getVideosFeed } from '../services/api.js';
            export default function P() { return <i>{columns.map(c=>c.caption)}</i>; }
        """)
        self.assertEqual(fab(self.app), [])

    def test_a_single_record_is_a_shape_default(self):
        self.write("lib/one.js", """
            export const empty = [{username:'', caption:'', sound:''}];
        """)
        self.write("pages/P.jsx", """
            import { empty } from '../lib/one.js';
            import { getVideosFeed } from '../services/api.js';
            export default function P() { return <i>{empty[0].caption}</i>; }
        """)
        self.assertEqual(fab(self.app), [])

    def test_the_env_switch_turns_it_off(self):
        import os
        self.seed_module()
        self.write("pages/P.jsx", """
            import { seededVideos } from '../lib/staticData.js';
            import { getVideosFeed } from '../services/api.js';
            export default function P() { return <i>{seededVideos[0].caption}</i>; }
        """)
        self.assertTrue(fab(self.app))
        os.environ["ENVGEN_FABRICATED_RECORDS_1203OC"] = "0"
        try:
            self.assertEqual(fab(self.app), [])
        finally:
            os.environ.pop("ENVGEN_FABRICATED_RECORDS_1203OC", None)


class AnUncheckedAppSaysSo(_App):
    """#883: the schema IS the vocabulary, so no schema means UNCHECKED, not clean."""

    def test_a_missing_models_py_announces_itself(self):
        self.seed_module()
        self.write("pages/P.jsx", """
            import { seededVideos } from '../lib/staticData.js';
            import { getVideosFeed } from '../services/api.js';
            export default function P() { return <i>{seededVideos[0].caption}</i>; }
        """)
        (self.app / "backend" / "models.py").unlink()
        said = []
        import env_generator.llm_generator.multi_agent.runtime.message_format as MF
        orig = MF.warn_once_1201
        MF.warn_once_1201 = lambda *a, **k: said.append(a)
        try:
            self.assertEqual(fab(self.app), [])
        finally:
            MF.warn_once_1201 = orig
        self.assertTrue(said, "an app with no models.py was scored as clean in silence")
        self.assertIn("UNCHECKED", " ".join(str(x) for x in said[0]))

    def test_an_unparsable_models_py_announces_itself(self):
        """3 of the corpus's 104 runs parse to no table at all."""
        self.seed_module()
        self.write("pages/P.jsx", """
            import { seededVideos } from '../lib/staticData.js';
            import { getVideosFeed } from '../services/api.js';
            export default function P() { return <i>{seededVideos[0].caption}</i>; }
        """)
        (self.app / "backend" / "models.py").write_text("# nothing here\n", encoding="utf-8")
        said = []
        import env_generator.llm_generator.multi_agent.runtime.message_format as MF
        orig = MF.warn_once_1201
        MF.warn_once_1201 = lambda *a, **k: said.append(a)
        try:
            self.assertEqual(fab(self.app), [])
        finally:
            MF.warn_once_1201 = orig
        self.assertTrue(said)
        self.assertIn("UNCHECKED", " ".join(str(x) for x in said[0]))


class TheCutDeclaresItself(_App):
    def test_a_capped_list_says_how_many_it_is_showing(self):
        self.seed_module()
        body = ["import { seededVideos } from '../lib/staticData.js';",
                "import { getVideosFeed } from '../services/api.js';"]
        for i in range(6):
            body.append("const a%d = seededVideos[%d];" % (i, i))
        self.write("pages/Many.jsx", "\n".join(body))
        rows = fab(self.app, limit=3)
        self.assertEqual(len(rows), 4, rows)
        self.assertIn("3 of 6", rows[-1])


class TheRecordParserReadsDepth(unittest.TestCase):
    def test_a_nested_objects_keys_belong_to_it(self):
        """r155's records carry `author: {display_name, …}`; a flat key scan attributed
        `display_name` to the record and matched the wrong table."""
        got = arrays("const videos = ["
                     "{id:1, caption:'a', author:{display_name:'X'}},"
                     "{id:2, caption:'b', author:{display_name:'Y'}}];")
        self.assertIn("videos", got)
        self.assertIn("caption", got["videos"][1])
        self.assertNotIn("display_name", got["videos"][1])

    def test_a_bracket_inside_a_string_does_not_unbalance_the_span(self):
        got = arrays("const rows = [{a:'[', b:'x'},{a:']', b:'y'}];\nconst after = 1;")
        self.assertEqual(got["rows"][0], 2)

    def test_a_field_in_only_one_record_is_not_shared(self):
        got = arrays("const rows = [{a:1, odd:2},{a:3}];")
        self.assertIn("a", got["rows"][1])
        self.assertNotIn("odd", got["rows"][1])

    def test_it_records_the_defining_line(self):
        got = arrays("\n\nconst rows = [{a:1},{a:2}];")
        self.assertEqual(got["rows"][2], 3)


class TheThresholdsCarryTheirMeasurement(unittest.TestCase):
    def test_the_column_floor_is_two(self):
        """At 1 the same scan reports 24 sites in 11 runs, 6 of the extra being UI config; at
        3 it loses r157's `creators` (`name`+`avatar`)."""
        self.assertEqual(_MIN_SHARED_COLUMNS_1203OC, 2)

    def test_the_record_floor_only_excludes_the_degenerate_case(self):
        """Every one of the 14 measured arrays holds at least 3 records, so this floor is not
        fitted to the data."""
        self.assertEqual(_MIN_RECORDS_1203OC, 2)


class SomebodyIsTold(unittest.TestCase):
    """#1139/#1148: both halves. A detector whose finding reaches nobody is #1041's shape."""

    @staticmethod
    def _orch_src():
        from env_generator.llm_generator.multi_agent import orchestrator as O
        return inspect.getsource(O)

    def _call_nodes(self, src, name):
        tree = ast.parse(src)
        parents = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                parents[child] = node
        out = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(
                    node.func, "attr", getattr(node.func, "id", "")) == name:
                out.append((node, parents))
        return out

    def _ancestors(self, node, parents):
        out = []
        cur = parents.get(node)
        while cur is not None:
            out.append(cur)
            cur = parents.get(cur)
        return out

    def test_the_orchestrator_calls_the_dispatcher(self):
        calls = self._call_nodes(self._orch_src(), "dispatch_fabricated_record_arrays_1203oc")
        self.assertTrue(calls, "nothing calls the #1203oc dispatcher")

    def test_the_call_has_its_own_try(self):
        node, parents = self._call_nodes(
            self._orch_src(), "dispatch_fabricated_record_arrays_1203oc")[0]
        tries = [a for a in self._ancestors(node, parents) if isinstance(a, ast.Try)]
        self.assertTrue(tries, "unguarded (#1201)")
        body = ast.dump(ast.Module(body=tries[0].body, type_ignores=[]))
        self.assertNotIn("dispatch_unstaged_seed_media_1203np", body,
                         "it shares a try with #1203np, so one failing silences the other")

    def test_it_is_not_behind_the_failed_checks_branch(self):
        """#1203ii's recorded bug: the call site was copied together with its gate, and the
        runs that ship invented rows are exactly the ones whose gate goes green."""
        src = self._orch_src()
        node, parents = self._call_nodes(
            src, "dispatch_fabricated_record_arrays_1203oc")[0]
        for anc in self._ancestors(node, parents):
            if isinstance(anc, ast.If):
                self.assertNotIn("failed_checks", ast.dump(anc.test),
                                 "the dispatch only fires when the gate is already red")

    def test_the_dispatcher_reads_its_own_detector(self):
        from env_generator.llm_generator.multi_agent.runtime.remediation_dispatcher import (
            RemediationDispatcher)
        src = inspect.getsource(
            RemediationDispatcher.dispatch_fabricated_record_arrays_1203oc)
        self.assertIn("fabricated_record_arrays_1203oc", src)
        self.assertNotIn("gate.get", src)

    def test_it_files_a_frontend_task_and_asks_for_the_third_answer(self):
        from env_generator.llm_generator.multi_agent.runtime.remediation_dispatcher import (
            RemediationDispatcher)
        src = inspect.getsource(
            RemediationDispatcher.dispatch_fabricated_record_arrays_1203oc)
        self.assertIn('assignee="frontend"', src)
        self.assertIn("SAY SO", src)

    def test_it_does_not_join_the_175_blocker_list(self):
        """#1202w6: a new wall gets a live run first. The detector reports."""
        from env_generator.llm_generator.multi_agent.runtime import deliverability as D
        self.assertNotIn("fabricated_record_arrays_1203oc", inspect.getsource(D))


class WhatTheCorpusSays(unittest.TestCase):
    """Named runs only -- the measured cases, two healthy controls, and the three runs whose
    icon maps the word-list version reported."""

    _MEASURED = {"tiktok-web-r190": 3, "tiktok-web-r155": 6, "tiktok-web-r131": 3,
                 "tiktok-web-r157": 2}
    _SILENT = ("tiktok-web-r191", "tiktok-web-r185", "tiktok-web-r103", "tiktok-web-r121",
               "tiktok-web-r56")

    @classmethod
    def setUpClass(cls):
        cls.corpus = Path(__file__).resolve().parents[2] / "generated"
        if not cls.corpus.is_dir():
            raise unittest.SkipTest("no generated/ corpus on this machine")

    def test_it_fires_on_the_measured_runs_with_the_measured_count(self):
        checked = 0
        for run, n in sorted(self._MEASURED.items()):
            app = self.corpus / run / "app"
            if not (app / "frontend" / "src").is_dir():
                continue
            checked += 1
            with self.subTest(run=run):
                self.assertEqual(len(fab(app)), n,
                                 "%s was measured at %d fabricated-record site(s)" % (run, n))
        if not checked:
            self.skipTest("no measured run on this disk")

    def test_r190_renders_a_creator_nobody_wrote(self):
        """The named case: `video ? {…} : seededVideos[2]` in MessagesDmEmptyPage."""
        app = self.corpus / "tiktok-web-r190" / "app"
        if not (app / "frontend" / "src").is_dir():
            self.skipTest("r190 is not on this disk")
        rows = fab(app)
        self.assertTrue([r for r in rows if "MessagesDmEmptyPage.jsx" in r], rows)

    def test_the_175_gate_did_not_see_any_of_them(self):
        """Same app, same tick: #175's own checker reads the frontend source and reports
        nothing about these sites. If it starts to, this ticket is redundant."""
        from env_generator.llm_generator.multi_agent.runtime.frontend_audit import (
            invented_field_fallback_blockers as b175)
        checked = 0
        for run in sorted(self._MEASURED):
            src = self.corpus / run / "app" / "frontend" / "src"
            if not src.is_dir():
                continue
            checked += 1
            names = set(re.findall(r"`(\w+)` is \d+ fabricated", " ".join(fab(src.parent))))
            with self.subTest(run=run):
                for row in b175(src):
                    self.assertFalse([n for n in names if n in row],
                                     "#175 now reports %s" % row[:120])
        if not checked:
            self.skipTest("no measured run on this disk")

    def test_it_stays_silent_on_the_controls(self):
        checked = 0
        for run in self._SILENT:
            app = self.corpus / run / "app"
            if not (app / "frontend" / "src").is_dir():
                continue
            checked += 1
            with self.subTest(run=run):
                self.assertEqual(fab(app), [],
                                 "%s started reporting -- for r103/r121/r56 that means the "
                                 "icon-map false positive is back" % run)
        if not checked:
            self.skipTest("no control run on this disk")


if __name__ == "__main__":
    unittest.main()
