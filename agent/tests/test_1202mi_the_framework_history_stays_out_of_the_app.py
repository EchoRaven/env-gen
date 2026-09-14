"""#1202mi: framework ticket tags and past-run names must not ship inside the
generated application.

Measured on the 161 environments on disk before this landed: 140 carried at
least one ticket tag in `app/backend/main.py`, 73 named another run, and
tiktok-r122's carried 46 tags and 7 run names. The standing rule (2026-06-18,
commit 880a449) had cleaned exactly this and it regressed.

The dangerous part is the scrub itself, so most of what follows is about what it
must NOT do. `#471`, `#528`, `#390` and `#568` are real tags in the emitted
Python AND valid three-digit CSS colours; r122's frontend holds 36 colours of
that shape. A pattern-driven scrub would silently repaint the app.
"""
import ast
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime.provenance_scrub import (  # noqa: E402
    scrub_provenance_1202mi as scrub)


def _code_without_docstrings(src):
    tree = ast.parse(src)
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef,
                          ast.AsyncFunctionDef)):
            b = getattr(n, "body", None)
            if (b and isinstance(b[0], ast.Expr)
                    and isinstance(b[0].value, ast.Constant)
                    and isinstance(b[0].value.value, str)):
                b.pop(0)
                if not b:
                    b.append(ast.Pass())
    return ast.dump(tree)


class ProvenanceLeavesCommentsAndDocstrings(unittest.TestCase):

    def test_a_tag_in_a_comment_goes(self):
        src = "# #1202db enforces the owner foreign key\nX = 1\n"
        out = scrub(src, "main.py")
        self.assertNotIn("#1202db", out)
        self.assertIn("enforces the owner foreign key", out)

    def test_a_tag_in_a_docstring_goes_and_the_sentence_survives(self):
        src = ('def f():\n'
               '    """#1202ie: say which two types a mismatch is about."""\n'
               '    return 1\n')
        out = scrub(src, "main.py")
        self.assertNotIn("1202ie", out)
        self.assertIn("say which two types a mismatch is about", out)

    def test_a_past_run_becomes_an_anonymous_one(self):
        src = ('def f():\n'
               '    """Probed on netflix-r42\'s delivered artifact: 8 of 12 failed."""\n'
               '    return 1\n')
        out = scrub(src, "main.py")
        self.assertNotIn("netflix-r42", out)
        self.assertIn("an earlier run", out)
        self.assertIn("8 of 12 failed", out, "the rationale must survive")

    def test_fix_and_proposal_prefixes_go_with_their_number(self):
        """The largest family by far: `FIX #93` occurs 681 times across the
        generated backends, and the first draft of the pattern missed every one
        of them because it demanded three digits."""
        cases = [("# FIX #124 the projection serves a stub\nX = 1\n",
                  "the projection serves a stub"),
                 ("# PROPOSAL #26 anti-thrash notices\nX = 1\n",
                  "anti-thrash notices"),
                 ("# Fix #63 temporal alias columns\nX = 1\n",
                  "temporal alias columns"),
                 ("# FIX #93 owner scoping\nX = 1\n", "owner scoping")]
        for src, survives in cases:
            out = scrub(src, "main.py")
            comment = out.split("\n")[0]
            self.assertNotIn("#", comment[1:], comment)
            self.assertNotRegex(comment, r"(?i)\b(fix|proposal|round)\b")
            self.assertIn(survives, out)

    def test_a_bare_low_number_in_quoted_error_text_is_left_alone(self):
        """A projected comment quotes `dictionary update sequence element #0 has
        length N`. That `#0` is part of the message, not provenance -- which is
        why the bare pattern requires three digits."""
        src = ('# raises "dictionary update sequence element #0 has length 3"\n'
               'X = 1\n')
        self.assertEqual(scrub(src, "main.py"), src)

    def test_the_other_run_shape_is_caught_too(self):
        """The corpus uses two: `netflix-r42` and `outlook run-47`."""
        src = '# Fix for outlook run-47 and instagram MM run #16\nX = 1\n'
        out = scrub(src, "main.py")
        self.assertNotIn("run-47", out)
        self.assertNotIn("run #16", out)
        self.assertIn("an earlier run", out)


class ItRemovesProvenanceNotEnglish(unittest.TestCase):
    """The first version swept `\\(\\s*\\)` to clean up what `(#1202db)` became,
    and ate the parentheses off every `finish()` in the prose around it. Measured
    over the generated backends on disk, that rule cost 555 function-call
    references; this one costs none."""

    def test_a_call_in_the_same_sentence_keeps_its_parens(self):
        src = ('def f():\n'
               '    """The lane calls finish() when done (#1202db); '
               'see check_inbox()."""\n'
               '    return 1\n')
        out = scrub(src, "main.py")
        self.assertNotIn("1202db", out)
        self.assertIn("finish()", out)
        self.assertIn("check_inbox()", out)
        self.assertIn("done; see", out, "spacing was not repaired")

    def test_a_docstring_of_pure_calls_is_untouched(self):
        src = ('def g():\n'
               '    """Uses tuple() and dict(). No provenance here."""\n'
               '    return 2\n')
        self.assertEqual(scrub(src, "main.py"), src)

    def test_a_comment_that_led_with_its_tag_does_not_become_a_sphinx_marker(self):
        out = scrub("# FIX #93: call reset() then seed()\nX = 1\n", "main.py")
        self.assertFalse(out.startswith("#:"), out)
        self.assertIn("call reset() then seed()", out)

    def test_indentation_inside_a_docstring_survives(self):
        src = ('def h():\n'
               '    """Head (#1202db).\n'
               '\n'
               '        indented block\n'
               '            deeper still\n'
               '    """\n'
               '    return 3\n')
        out = scrub(src, "main.py")
        self.assertIn("        indented block", out)
        self.assertIn("            deeper still", out)


class WhatItMustNeverTouch(unittest.TestCase):
    """Each of these would be a regression worse than the leak."""

    def test_a_three_digit_css_colour_in_python_code_survives(self):
        """`#528` is a real ticket tag. It is also a colour. Position, not
        pattern, is what tells them apart."""
        src = 'BRAND = "#528"\nDARK = "#111"\nACCENT = "#FE2C55"\n'
        self.assertEqual(scrub(src, "theme.py"), src)

    def test_a_css_file_is_not_python_and_is_returned_untouched(self):
        css = ".a{color:#333}.b{background:#111}.c{border:1px solid #471}"
        self.assertEqual(scrub(css, "styles.css"), css)
        self.assertEqual(scrub(css, ""), css, "no filename must not mean 'try it'")

    def test_a_tag_inside_a_runtime_string_survives(self):
        """Load bearing: test_1166_dropped_routes_must_be_dropped_for_something
        asserts this exact substring is present in the emitted source, and
        detectors read these back out of a run's logs."""
        src = ('def f(log, n):\n'
               '    log.warning("#1166 restored %d lane route(s)", n)\n')
        out = scrub(src, "main.py")
        self.assertIn("#1166 restored", out)

    def test_code_is_never_rewritten(self):
        src = ('# #943 no fixed windows\n'
               'def handler(request):\n'
               '    """#1202db owner FK, see netflix-r42."""\n'
               '    token = "#528"\n'
               '    return {"colour": "#111", "n": 1202}\n')
        out = scrub(src, "main.py")
        self.assertNotIn("1202db", out)
        self.assertEqual(_code_without_docstrings(src),
                         _code_without_docstrings(out))

    def test_unparseable_python_is_left_exactly_alone(self):
        """A file that cannot be parsed gives no way to tell a tag from a
        colour. Shipping a tag beats shipping a broken file."""
        src = "# #1202db\ndef broken(:\n"
        self.assertEqual(scrub(src, "main.py"), src)

    def test_text_without_provenance_is_returned_identically(self):
        src = 'def f():\n    """Plain docstring."""\n    return "#111"\n'
        self.assertEqual(scrub(src, "main.py"), src)


class ItIsWiredWhereTheProjectorsWrite(unittest.TestCase):
    """A scrubber no write path calls is the defect, not the fix."""

    def test_the_framework_write_choke_point_applies_it(self):
        from multi_agent.runtime.path_routed_workspace import (
            framework_write_1202cw)
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "main.py"
            ok = framework_write_1202cw(
                target,
                '# #1202db projected on netflix-r42\nHANDLER = "#528"\n')
            self.assertTrue(ok)
            got = target.read_text(encoding="utf-8")
            self.assertNotIn("1202db", got)
            self.assertNotIn("netflix-r42", got)
            self.assertIn('"#528"', got, "the code's own value must survive")

    def test_backend_skeleton_scrubs_its_direct_writes(self):
        """It writes main.py with `.write_text`, bypassing the choke point."""
        from multi_agent.runtime import backend_skeleton
        out = backend_skeleton._scrub_1202mi(
            '# #1202ie on tiktok-r107\nX = 1\n', "main.py")
        self.assertNotIn("1202ie", out)
        self.assertNotIn("tiktok-r107", out)


class TheRealArtifactsComeOutClean(unittest.TestCase):
    """Validation against the environments on disk, not against a fixture."""

    def test_a_generated_backend_loses_its_tags_without_losing_its_code(self):
        import glob
        import re
        files = sorted(glob.glob(
            str(ROOT.parent / "generated" / "*" / "app" / "backend" / "main.py")))
        if not files:
            self.skipTest("no generated environments on this machine")
        tag = re.compile(r"#\d{3,4}[a-z]{0,2}\b")
        checked = removed = 0
        for f in files[:40]:
            src = Path(f).read_text(encoding="utf-8", errors="replace")
            try:
                before = _code_without_docstrings(src)
            except SyntaxError:
                continue
            out = scrub(src, "main.py")
            self.assertEqual(before, _code_without_docstrings(out), f)
            removed += len(tag.findall(src)) - len(tag.findall(out))
            checked += 1
        self.assertGreater(checked, 0)
        self.assertGreater(removed, 0, "nothing was removed from any real app")


if __name__ == "__main__":
    unittest.main()


class AFileThatCouldNotBeScrubbedIsRecorded(unittest.TestCase):
    """#947: 'this environment shipped with its framework tags intact' is the
    fact a later reader of a released artifact needs, and a log line is gone by
    then."""

    def test_an_unparseable_file_leaves_a_row(self):
        import json
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "app" / "backend" / "main.py"
            target.parent.mkdir(parents=True)
            out = scrub("# FIX #93 owner scoping\ndef broken(:\n", str(target))
            self.assertIn("FIX #93", out, "an unparseable file is left alone")
            rec = Path(d) / "logs" / "provenance_scrub_1202mi.jsonl"
            self.assertTrue(rec.is_file(), "no record of the unscrubbed file")
            rows = [json.loads(l) for l in
                    rec.read_text(encoding="utf-8").splitlines() if l.strip()]
            self.assertEqual(rows[-1]["outcome"], "unparsed_provenance_kept")
            self.assertIn("main.py", rows[-1]["file"])

    def test_a_file_that_scrubs_cleanly_leaves_no_row(self):
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "app" / "backend" / "main.py"
            target.parent.mkdir(parents=True)
            scrub("# FIX #93 owner scoping\nX = 1\n", str(target))
            self.assertFalse((Path(d) / "logs" /
                              "provenance_scrub_1202mi.jsonl").exists())
