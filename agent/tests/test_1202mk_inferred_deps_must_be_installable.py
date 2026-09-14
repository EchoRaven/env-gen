"""#1202mk: what the framework writes into pyproject.toml must be installable.

`app/backend/pyproject.toml` is framework-owned, and its `dependencies` list is
inferred from the backend's imports. Two things were wrong with that inference,
both found in tiktok-r123:

WEDGE. A lane wrote `import __main__ as main_mod` in custom_routes.py — legal
Python, and not the lane's mistake. `__main__` is not a distribution name, so
`uv pip install -r pyproject.toml` refused the WHOLE file
(`project.dependencies[7] must be pep508`), the backend image never built, and
the app never booted. The run spent 26 ticks / 121 min / $396 and delivered
nothing. No lane could fix it: the file is framework-owned.

LEAK. The inference used `_TOP_IMPORT_RE` over raw source with `re.M`, so any
line that merely BEGINS with "from " counted. The framework's own projected
main.py contains the sentence `... this is "the difference\\n from the earlier
attempt at this ..."`, whose second line begins "from the" — so `the`, an
unrelated PyPI package, has been a dependency of every generated backend since
at least tiktok-r120 (verified present in r120, r121, r122, r123).

The fix is both halves of the same lesson: read imports from the AST rather than
from line starts, and VALIDATE the value rather than enumerating bad names.
"""
import json
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime.backend_skeleton import (  # noqa: E402
    _imported_top_modules_1202mk, _lane_third_party_imports, render_pyproject)


def _pep508_ok(spec):
    """Reject exactly what uv rejects."""
    try:
        from packaging.requirements import Requirement, InvalidRequirement
    except ImportError:                       # pragma: no cover
        return True
    try:
        Requirement(spec)
        return True
    except InvalidRequirement:
        return False


class _Backend:
    """A backend directory, built the way the projector lays one out."""

    def __enter__(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.be = self.root / "app" / "backend"
        self.be.mkdir(parents=True)
        return self

    def __exit__(self, *a):
        self._tmp.cleanup()

    def write(self, name, src):
        (self.be / name).write_text(src, encoding="utf-8")
        return self


class TheImportsAreReadFromTheAstNotTheLineStarts(unittest.TestCase):

    def test_prose_beginning_with_from_is_not_an_import(self):
        """The r120–r123 leak, in the framework's own words."""
        src = ('def f():\n'
               '    """this is "the difference\n'
               '    from the earlier attempt at this, which fail-opened" — but it\n'
               '    delegates elsewhere.\n'
               '    """\n'
               '    return 1\n')
        self.assertEqual(_imported_top_modules_1202mk(src), [])

    def test_a_comment_beginning_with_import_is_not_an_import(self):
        self.assertEqual(
            _imported_top_modules_1202mk("# import requests one day\nX = 1\n"), [])

    def test_a_real_import_inside_a_function_is_still_found(self):
        """database.py imports psycopg2 inside a function; losing that would
        mean a backend that cannot connect."""
        src = ("def g():\n"
               "    from psycopg2.extras import RealDictCursor\n"
               "    return RealDictCursor\n")
        self.assertEqual(_imported_top_modules_1202mk(src), ["psycopg2"])

    def test_a_relative_import_is_local_and_skipped(self):
        self.assertEqual(
            _imported_top_modules_1202mk("from . import models\n"), [])
        self.assertEqual(
            _imported_top_modules_1202mk("from .models import User\n"), [])

    def test_an_unparseable_file_falls_back_rather_than_losing_imports(self):
        """A lane's file mid-edit must not silently drop its real dependencies."""
        self.assertIsNone(_imported_top_modules_1202mk("def broken(:\n"))
        with _Backend() as b:
            b.write("custom_routes.py", "import httpx\ndef broken(:\n")
            self.assertIn("httpx", _lane_third_party_imports(b.be))


class AnUninstallableNameNeverReachesPyproject(unittest.TestCase):

    def test_the_lane_line_that_wedged_r123(self):
        with _Backend() as b:
            b.write("custom_routes.py",
                    "import __main__ as main_mod\n"
                    "def route():\n    return main_mod\n")
            deps = _lane_third_party_imports(b.be)
            self.assertNotIn("__main__", deps)

    def test_the_rendered_pyproject_is_valid_toml_and_valid_pep508(self):
        with _Backend() as b:
            b.write("custom_routes.py", "import __main__ as main_mod\n")
            b.write("database.py",
                    "def c():\n    from psycopg2.extras import RealDictCursor\n")
            parsed = tomllib.loads(render_pyproject(b.be))
            deps = parsed["project"]["dependencies"]
            bad = [d for d in deps if not _pep508_ok(d)]
            self.assertEqual(bad, [], deps)
            self.assertIn("psycopg2-binary", deps, "a real import was lost")

    def test_the_refusal_is_recorded_not_silent(self):
        """#947: a dropped dependency must be answerable for afterwards — a
        backend missing a package it imports is a hard failure to diagnose."""
        with _Backend() as b:
            b.write("custom_routes.py", "import __main__ as main_mod\n")
            _lane_third_party_imports(b.be)
            rec = b.root / "logs" / "inferred_deps_refused_1202mk.jsonl"
            self.assertTrue(rec.is_file(), "nothing recorded the refusal")
            rows = [json.loads(l) for l in
                    rec.read_text(encoding="utf-8").splitlines() if l.strip()]
            self.assertIn("__main__", rows[-1]["dropped"])

    def test_a_clean_backend_records_nothing(self):
        with _Backend() as b:
            b.write("custom_routes.py", "import httpx\n")
            self.assertEqual(_lane_third_party_imports(b.be), ["httpx"])
            self.assertFalse((b.root / "logs" /
                              "inferred_deps_refused_1202mk.jsonl").exists())


class WhatMustKeepWorking(unittest.TestCase):

    def test_sibling_modules_and_stdlib_are_still_skipped(self):
        with _Backend() as b:
            b.write("models.py", "X = 1\n")
            b.write("main.py", "import models\nimport json\nimport asyncio\n")
            self.assertEqual(_lane_third_party_imports(b.be), [])

    def test_the_import_to_pip_mapping_still_applies(self):
        with _Backend() as b:
            b.write("main.py", "import yaml\nimport dateutil\n")
            self.assertEqual(sorted(_lane_third_party_imports(b.be)),
                             ["python-dateutil", "pyyaml"])

    def test_an_extra_marked_requirement_survives_validation(self):
        """`passlib[bcrypt]` is a mapped value with an extra; the validator reads
        the name before the bracket, not the whole string."""
        with _Backend() as b:
            b.write("main.py", "import passlib\n")
            self.assertEqual(_lane_third_party_imports(b.be), ["passlib[bcrypt]"])


class TheRealArtifactWouldHaveBuilt(unittest.TestCase):

    def test_r123s_own_backend_now_yields_an_installable_pyproject(self):
        import shutil
        src = ROOT.parent / "generated" / "tiktok-web-r123" / "app" / "backend"
        if not src.is_dir():
            self.skipTest("tiktok-r123 is not on this machine")
        with tempfile.TemporaryDirectory() as d:
            be = Path(d) / "app" / "backend"
            be.parent.mkdir(parents=True)
            shutil.copytree(src, be)
            deps = tomllib.loads(render_pyproject(be))["project"]["dependencies"]
            self.assertEqual([x for x in deps if not _pep508_ok(x)], [], deps)
            self.assertNotIn("the", deps, "the prose-derived package is back")
            self.assertNotIn("__main__", deps)


if __name__ == "__main__":
    unittest.main()
