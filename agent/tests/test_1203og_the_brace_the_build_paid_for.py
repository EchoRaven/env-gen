r"""#1203og: a closing bracket with no opener, before the docker build pays for it.

MEASURED over every `compose_build_failure*` log in the corpus: 145 failures, and the
composition has CHANGED. 84 were the tar/EOF context break #1203mm fixed -- and both runs that
carry its `.dockerignore` (r190, r191) have ZERO of those. The leading cause now is a SYNTAX
ERROR in a lane file: 26 logs, and in r191 it is 10 of 10, every one the same stray `}`:

    src/pages/SettingsMoreMenuPage.jsx:19:0: ERROR: Unexpected "}"

The lane rewrote the component as an 18-line function and left the previous file's final `}`
behind. ATTRIBUTED, not assumed: the lane's own commit `07d4b15` (17:15:45) already carries the
extra brace and the integration copy two seconds later is faithful -- so this is lane-authored,
and what the framework did was spend TEN docker builds discovering it, each one a build cycle
and a window in which #1202lx's own warning says the visual verdict describes an older image.

★ ONLY THE CLOSER-WITHOUT-OPENER CASE, from measurement rather than caution. Over the 3525
delivered frontend sources:
  * "a closing bracket at depth 0" flags 0 files, and it names the SAME line esbuild does
    (r191's broken blob scans to line 19 against esbuild's `19:0`);
  * "the file ends with unclosed brackets" flags 105 (3%), every one a false positive from a
    regex literal the scanner deliberately does not parse. That half is not reported -- a 3%
    false-positive rate on a build-blocking diagnosis is the #566j mistake.

DIAGNOSIS ONLY (#1202w6): the build still runs, the retry still happens, nothing edits the
file. Deleting one of two braces is a guess about which one the author meant.
"""
import inspect
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from env_generator.llm_generator.multi_agent.runtime import validation_runner as VR
from env_generator.llm_generator.multi_agent.runtime.frontend_audit import (
    _bracket_scan_1203og as scan,
    record_unparsable_frontend_files_1203og as record,
    unparsable_frontend_files_1203og as unparsable,
)


class TheScannerFindsTheStrayCloser(unittest.TestCase):
    def test_r191s_exact_shape(self):
        src = textwrap.dedent("""
            export default function P() {
              return (
                <div>hi</div>
              );
            }
            }
        """)
        depth, neg = scan(src)
        self.assertEqual(depth, -1)
        self.assertEqual(neg, 7)

    def test_a_balanced_file_is_clean(self):
        self.assertEqual(scan("const a = () => { return [1, 2]; };\n"), (0, None))

    def test_an_unclosed_file_reports_no_line(self):
        """The half that is NOT reported: 105 of 3525 delivered files look like this and every
        one is a regex literal."""
        depth, neg = scan("const a = () => {\n  return 1;\n")
        self.assertGreater(depth, 0)
        self.assertIsNone(neg)

    def test_a_brace_in_a_string_is_not_a_bracket(self):
        self.assertEqual(scan("const a = '}}}';\n"), (0, None))

    def test_a_brace_in_a_template_literal_is_not_a_bracket(self):
        self.assertEqual(scan("const a = `}} ${ {x: 1}.x } }}`;\n"), (0, None))

    def test_a_brace_in_a_comment_is_not_a_bracket(self):
        self.assertEqual(scan("// }}}\n/* }}} */\nconst a = 1;\n"), (0, None))

    def test_an_escaped_quote_does_not_end_the_string(self):
        self.assertEqual(scan("const a = 'it\\'s }';\nconst b = 2;\n"), (0, None))

    def test_the_line_number_counts_newlines_inside_skipped_regions(self):
        src = "/* one\ntwo\nthree */\n}\n"
        self.assertEqual(scan(src)[1], 4)

    def test_hostile_input_never_raises(self):
        for bad in (None, "", "`unterminated", "'unterminated", "/* unterminated"):
            with self.subTest(src=repr(bad)[:20]):
                self.assertIsInstance(scan(bad), tuple)


class _Tree(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.src = Path(self._tmp.name) / "src"
        (self.src / "pages").mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, rel, body):
        (self.src / rel).write_text(textwrap.dedent(body), encoding="utf-8")


class TheRowCarriesWhereAndWhat(_Tree):
    def test_the_row_names_the_file_the_line_and_the_text(self):
        self.write("pages/SettingsMoreMenuPage.jsx", """
            export default function P() {
              return <div />;
            }
            }
        """)
        rows = unparsable(self.src)
        self.assertEqual(len(rows), 1, rows)
        self.assertIn("SettingsMoreMenuPage.jsx:5", rows[0])
        self.assertIn("}", rows[0].split(" — ")[0])
        self.assertIn("closing bracket with no opener", rows[0])

    def test_a_clean_tree_is_silent(self):
        self.write("pages/Fine.jsx", "export default function P() { return <i />; }\n")
        self.assertEqual(unparsable(self.src), [])

    def test_node_modules_and_dist_are_skipped(self):
        for d in ("node_modules", "dist"):
            (self.src / d).mkdir()
            (self.src / d / "x.js").write_text("}\n", encoding="utf-8")
        self.assertEqual(unparsable(self.src), [])

    def test_a_missing_directory_returns_empty(self):
        self.assertEqual(unparsable(Path("/nope/src")), [])

    def test_several_files_and_the_cut_declares_itself(self):
        for i in range(9):
            (self.src / ("B%d.jsx" % i)).write_text("const a = 1;\n}\n", encoding="utf-8")
        rows = unparsable(self.src, limit=3)
        self.assertEqual(len(rows), 4, rows)
        self.assertIn("3 of 9", rows[-1])


class TheBuildPathSaysWhere(unittest.TestCase):
    def test_the_builder_runs_the_scan(self):
        src = inspect.getsource(VR._build_with_retry)
        self.assertIn("unparsable_frontend_files_1203og", src)

    def test_the_scan_runs_BEFORE_the_retry_loop(self):
        """Inside the loop it would re-read the same files on every attempt and say nothing
        new; the point is to name the cause once, before the first build."""
        import ast
        tree = ast.parse(inspect.getsource(VR))
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                  and n.name == "_build_with_retry")
        loop = next(n for n in fn.body if isinstance(n, ast.For))
        call_lines = [n.lineno for n in ast.walk(fn)
                      if isinstance(n, ast.Call) and getattr(
                          n.func, "id", getattr(n.func, "attr", "")) == "_unp1203og"]
        self.assertTrue(call_lines, "nothing calls the scan")
        self.assertLess(max(call_lines), loop.lineno)

    def test_the_failure_detail_carries_the_rows(self):
        """★ BEHAVIOUR, not text-in-source. The first version asserted `_note_1203og` and
        "the retry cannot" appeared in the source, and mutations OG11/OG12 (drop the note from
        the detail / reword it) both read MISSED -- the name is still DEFINED after the drop,
        and that phrase also occurs in the log line. The only honest check is to run the thing
        and read what it returns."""
        import subprocess
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            src = root / "app" / "frontend" / "src"
            src.mkdir(parents=True)
            (src / "Broken.jsx").write_text("const a = 1;\n}\n", encoding="utf-8")
            docker = root / "docker"
            docker.mkdir()
            calls = []

            def _fake(compose_file, *args, cwd=None, timeout=None):
                calls.append(args)
                return subprocess.CompletedProcess(
                    args=["docker"], returncode=1, stdout="", stderr="boom"), False

            orig = VR._compose_capture
            VR._compose_capture = _fake
            try:
                ok, detail = VR._build_with_retry(docker / "docker-compose.yml", docker)
            finally:
                VR._compose_capture = orig
        self.assertFalse(ok)
        self.assertIn("Broken.jsx:2", detail)
        self.assertIn("retry cannot", detail)
        self.assertTrue(calls, "the build was skipped, which is a control-flow change")

    def test_a_clean_tree_adds_nothing_to_the_detail(self):
        import subprocess
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            src = root / "app" / "frontend" / "src"
            src.mkdir(parents=True)
            (src / "Fine.jsx").write_text("const a = 1;\n", encoding="utf-8")
            docker = root / "docker"
            docker.mkdir()
            orig = VR._compose_capture
            VR._compose_capture = lambda *a, **k: (subprocess.CompletedProcess(
                args=["docker"], returncode=1, stdout="", stderr="boom"), False)
            try:
                ok, detail = VR._build_with_retry(docker / "docker-compose.yml", docker)
            finally:
                VR._compose_capture = orig
        self.assertFalse(ok)
        self.assertNotIn("#1203og", detail)

    def test_it_does_not_change_the_build_control_flow(self):
        """#1202w6: no early return, no skipped retry, no file edit. The scan is diagnosis."""
        import ast
        tree = ast.parse(inspect.getsource(VR))
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                  and n.name == "_build_with_retry")
        src_lines = inspect.getsource(VR).splitlines()
        loop = next(n for n in fn.body if isinstance(n, ast.For))
        before = "\n".join(src_lines[fn.lineno - 1:loop.lineno - 1])
        self.assertNotIn("return ", before.split("_unparsable_1203og", 1)[-1],
                         "the pre-scan returns early, which is a control-flow change")
        self.assertNotIn("write_text", inspect.getsource(VR._build_with_retry))

    def test_its_own_try(self):
        src = inspect.getsource(VR._build_with_retry)
        i = src.index("unparsable_frontend_files_1203og")
        self.assertIn("try:", src[:i].rsplit("\n\n", 1)[-1],
                      "the scan is not guarded; a scan fault must not fail the build")


class TheFindingReachesAFile(unittest.TestCase):
    """#947's ratchet caught the first draft of this ticket and it was right: the rows went to
    `_LOG.warning` and to the build-failure detail string, and neither is a file a run keeps.
    Worse, the pre-registered criterion was reading `compose_build_failure*.log` for the
    marker -- a file `_compose` writes from the docker transcript alone -- so it could never
    have confirmed. These tests are what the ratchet's allowlist entry is backed by."""

    def test_the_recorder_writes_the_row_and_it_reads_back(self):
        import json
        with tempfile.TemporaryDirectory() as d:
            self.assertTrue(record(d, ["Broken.jsx:2: } — a closing bracket with no opener"]))
            led = Path(d) / "logs" / "unparsable_frontend_1203og.jsonl"
            self.assertTrue(led.is_file())
            row = json.loads(led.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(row["count"], 1)
            self.assertIn("Broken.jsx:2", row["files"][0])
            self.assertIn("at", row)

    def test_an_empty_finding_is_not_landed(self):
        """#1039: "the scan found nothing" is not evidence, and a row saying nothing would make
        the criterion read a clean run as a reported one."""
        with tempfile.TemporaryDirectory() as d:
            self.assertFalse(record(d, []))
            self.assertFalse(record(d, None))
            self.assertFalse(record(None, ["x"]))
            self.assertFalse(list(Path(d).rglob("unparsable_frontend_1203og.jsonl")))

    def test_the_build_path_calls_the_recorder(self):
        import subprocess
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            src = root / "app" / "frontend" / "src"
            src.mkdir(parents=True)
            (src / "Broken.jsx").write_text("const a = 1;\n}\n", encoding="utf-8")
            docker = root / "docker"
            docker.mkdir()
            orig = VR._compose_capture
            VR._compose_capture = lambda *a, **k: (subprocess.CompletedProcess(
                args=["docker"], returncode=1, stdout="", stderr="boom"), False)
            try:
                VR._build_with_retry(docker / "docker-compose.yml", docker)
            finally:
                VR._compose_capture = orig
            led = root / "logs" / "unparsable_frontend_1203og.jsonl"
            self.assertTrue(led.is_file(), "the build path logged but persisted nothing")


class WhatTheCorpusSays(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.corpus = Path(__file__).resolve().parents[2] / "generated"
        if not cls.corpus.is_dir():
            raise unittest.SkipTest("no generated/ corpus on this machine")

    def test_no_delivered_tree_is_flagged(self):
        """The false-positive measurement, as an assertion: 0 of 3525 delivered sources carry
        a closer at depth 0. If this starts failing, read it -- a delivered app that cannot
        parse is a worse finding than the one this file is about."""
        flagged = []
        for src in sorted(self.corpus.glob("*/app/frontend/src")):
            if unparsable(src):
                flagged.append(src.parts[-4])
        self.assertEqual(flagged, [], "these delivered trees do not parse: %s" % flagged)

    def test_r191s_broken_blob_is_caught_at_the_line_esbuild_named(self):
        run = self.corpus / "tiktok-web-r191"
        if not (run / ".git").is_dir():
            self.skipTest("r191 has no git history on this disk")
        blob = subprocess.run(
            ["git", "-C", str(run), "show",
             "07d4b15:app/frontend/src/pages/SettingsMoreMenuPage.jsx"],
            capture_output=True, text=True).stdout
        if not blob.strip():
            self.skipTest("that commit is not in this clone")
        depth, neg = scan(blob)
        self.assertEqual(neg, 19, "esbuild reported 19:0; the scan says %r" % neg)
        self.assertLess(depth, 0)

    def test_the_unclosed_half_really_is_noisy(self):
        """Why only one half is reported, as a measurement rather than a claim: the delivered
        corpus has files that end unclosed, and they build fine."""
        unclosed = 0
        for src in sorted(self.corpus.glob("*/app/frontend/src")):
            for f in list(src.rglob("*.jsx")) + list(src.rglob("*.js")):
                if "node_modules" in f.parts:
                    continue
                try:
                    d, neg = scan(f.read_text(encoding="utf-8", errors="ignore"))
                except Exception:
                    continue
                if d > 0 and neg is None:
                    unclosed += 1
        self.assertGreater(unclosed, 20,
                           "the unclosed half stopped being noisy (%d files), so the "
                           "asymmetry this check is built on needs re-measuring" % unclosed)


if __name__ == "__main__":
    unittest.main()
