"""#1202mi: the scrub is a POLICY ON WRITES, so every write path must apply it.

I shipped the first version wired to two of six paths and called it done. That
is the same defect `#1202mg` had just been about — a guard installed on one of
several entry points — and a full check of my own change is what found it. The
uncovered ones, measured on real renders:

    oauth_scaffold.write_oauth_as        11 tags per run, 9 scrubbable
    safe_code_write.write_py_if_...      serves 4 callers (handler_fk_repair,
                                         backend_scaffold, route_projector,
                                         heal_pipeline)
    mcp_scaffold (MCP server main.py)    0 today
    scaffolder   (_BASE_MAIN_PY)         0 today

The last two are wired anyway: a policy that holds on five of six paths is
exactly the shape that let this happen. This file is the inventory, so a seventh
path cannot appear without someone answering for it.
"""
import ast
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

RUNTIME = LLM_DIR / "multi_agent" / "runtime"

#: Every module that writes framework-authored Python into the generated app,
#: and the function in it that must apply the scrub.
PYTHON_WRITE_PATHS = {
    "path_routed_workspace.py": "framework_write_1202cw",
    "backend_skeleton.py": None,          # two direct writes, checked by call
    "safe_code_write.py": "write_py_if_still_parses",
    "oauth_scaffold.py": "write_oauth_as",
    "mcp_scaffold.py": None,
    "scaffolder.py": None,
}

_TAG = re.compile(r"\b(?:FIX|PROPOSAL|Round)[- ]?#?\d{1,4}[a-z]{0,2}\b", re.I)
_BARE = re.compile(r"(?<!\w)#\d{3,4}[a-z]{0,2}\b")


def _scrub_calls_in(module_name):
    """Names of scrub helpers called anywhere in the module."""
    tree = ast.parse((RUNTIME / module_name).read_text(encoding="utf-8"))
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Call):
            name = getattr(n.func, "id", None) or getattr(n.func, "attr", None)
            if name and "1202mi" in name:
                out.add(name)
    return out


class EveryWritePathAppliesIt(unittest.TestCase):

    def test_each_declared_module_calls_the_scrub(self):
        for mod in PYTHON_WRITE_PATHS:
            with self.subTest(module=mod):
                self.assertTrue(
                    _scrub_calls_in(mod),
                    "%s writes Python into the generated app and never scrubs it"
                    % mod)

    def test_no_write_text_of_python_escapes_in_those_modules(self):
        """Inside the declared modules, a `.write_text(` whose argument is not
        scrub-wrapped is how a seventh path would appear."""
        offenders = []
        for mod in PYTHON_WRITE_PATHS:
            src = (RUNTIME / mod).read_text(encoding="utf-8")
            tree = ast.parse(src)
            for n in ast.walk(tree):
                if not (isinstance(n, ast.Call)
                        and isinstance(n.func, ast.Attribute)
                        and n.func.attr == "write_text" and n.args):
                    continue
                arg = n.args[0]
                wrapped = (isinstance(arg, ast.Call)
                           and "1202mi" in (getattr(arg.func, "id", "")
                                            or getattr(arg.func, "attr", "")))
                # a JSON/text artifact is not Python; those are named in the call
                line = src.split("\n")[n.lineno - 1]
                looks_py = ("main_py" in line or "_BASE_MAIN_PY" in line
                            or "dest" in line or "(be / name)" in line
                            or "p.write_text(text" in line)
                if looks_py and not wrapped:
                    offenders.append("%s:%d" % (mod, n.lineno))
        self.assertEqual(offenders, [],
                         "unscrubbed Python writes: " + ", ".join(offenders))


class TheOauthModulesComeOutClean(unittest.TestCase):
    """End to end against the real entry point, because that is the only way to
    know the wiring runs rather than merely exists."""

    def test_rendered_oauth_modules_carry_no_framework_tags(self):
        from multi_agent.runtime import oauth_scaffold
        with tempfile.TemporaryDirectory() as d:
            res = oauth_scaffold.write_oauth_as(Path(d))
            self.assertTrue(res["written"])
            for p in res["written"]:
                src = Path(p).read_text(encoding="utf-8")
                with self.subTest(module=Path(p).name):
                    # comments and docstrings must be clean; runtime strings are
                    # deliberately out of scope and are checked separately below
                    tree = ast.parse(src)          # it still parses
                    self.assertTrue(tree.body)
                    self.assertEqual(
                        _TAG.findall(_comments_and_docstrings(src)), [])
                    self.assertEqual(
                        _BARE.findall(_comments_and_docstrings(src)), [])


def _comments_and_docstrings(src):
    from multi_agent.runtime.provenance_scrub import (
        _comment_and_docstring_spans_1202mi)
    return "\n".join(src[a:b] for a, b in
                     _comment_and_docstring_spans_1202mi(src))


class TheSafeWriterScrubsWhatItWrites(unittest.TestCase):
    """It serves four callers, so wiring it covers all four at once."""

    def test_a_repair_written_through_it_loses_its_tags(self):
        from multi_agent.runtime.safe_code_write import write_py_if_still_parses
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "main.py"
            target.write_text("X = 0\n", encoding="utf-8")
            ok = write_py_if_still_parses(
                target, '# FIX #93 on netflix-r42\nX = 1\n', what="test")
            self.assertTrue(ok)
            got = target.read_text(encoding="utf-8")
            self.assertNotIn("FIX #93", got)
            self.assertNotIn("netflix-r42", got)
            self.assertIn("X = 1", got)

    def test_a_non_python_file_is_still_written_untouched(self):
        from multi_agent.runtime.safe_code_write import write_py_if_still_parses
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "styles.css"
            css = ".a{color:#333}.b{border:1px solid #471}"
            self.assertTrue(write_py_if_still_parses(target, css))
            self.assertEqual(target.read_text(encoding="utf-8"), css)

    def test_it_still_refuses_a_write_that_would_break_the_file(self):
        """The scrub must not weaken the guard this function exists for."""
        from multi_agent.runtime.safe_code_write import write_py_if_still_parses
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "main.py"
            target.write_text("X = 0\n", encoding="utf-8")
            ok = write_py_if_still_parses(target, "# FIX #93\ndef broken(:\n")
            self.assertFalse(ok)
            self.assertEqual(target.read_text(encoding="utf-8"), "X = 0\n")


if __name__ == "__main__":
    unittest.main()
