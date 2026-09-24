"""Guard: FIX #189 — strip HALLUCINATED local-module deps from pyproject.toml.

tiktok-r5 (2026-07-18 05:26 STUCK-ABORT): the generated backend's pyproject
listed ``custom-routes`` as a [project] dependency — that's the app's OWN
``custom_routes.py`` hallucinated into a pip package. uv resolution failed
("Because custom-routes was not found in the package registry") → docker_up
never came up → 7 post-cap cycles → abort, while the backend lane thrashed in
finish-gate bureaucracy without ever landing the one-line fix.

Deterministic heal (by-construction principle): a dependency whose PEP-503
normalized name matches a LOCAL module/package of the backend can never need
installing (the local file shadows any site-packages copy at runtime) — strip
it at heal time. Conservative: names on the known-real-dists allowlist are
never stripped (a lane that shadowed ``fastapi`` with fastapi.py has a
different bug; removing the real install would break transitive imports).
"""

import sys
import tempfile
import unittest
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.backend_scaffold import (  # noqa: E402
    sanitize_pyproject_local_deps, _SKELETON_LOCAL_MODULES,
)
from multi_agent.runtime.backend_skeleton import (  # noqa: E402
    _lane_third_party_imports,
)

PYPROJECT = """\
[project]
name = "tiktok-backend"
version = "0.1.0"
dependencies = [
    "fastapi>=0.110",
    "uvicorn[standard]>=0.29",
    "custom-routes",
    "psycopg[binary]>=3.1",
    "seed_data>=1.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
"""


class SanitizePyprojectDepsTests(unittest.TestCase):
    def _mk_backend(self, pyproject=PYPROJECT, files=("custom_routes.py",
                                                      "seed_data.py",
                                                      "main.py")):
        d = Path(tempfile.mkdtemp())
        for f in files:
            (d / f).write_text("# local\n")
        (d / "pyproject.toml").write_text(pyproject)
        return d

    def test_strips_local_module_deps_keeps_real_ones(self):
        be = self._mk_backend()
        rep = sanitize_pyproject_local_deps(be)
        self.assertTrue(rep["repaired"])
        self.assertEqual(sorted(rep["dropped"]), ["custom-routes", "seed_data>=1.0"])
        out = (be / "pyproject.toml").read_text()
        self.assertNotIn("custom-routes", out)
        self.assertNotIn("seed_data", out)
        self.assertIn("fastapi>=0.110", out)
        self.assertIn("uvicorn[standard]>=0.29", out)
        self.assertIn("psycopg[binary]>=3.1", out)

    def test_idempotent_second_run_noop(self):
        be = self._mk_backend()
        sanitize_pyproject_local_deps(be)
        rep2 = sanitize_pyproject_local_deps(be)
        self.assertFalse(rep2["repaired"])

    def test_allowlisted_real_dist_never_stripped_even_if_shadowed(self):
        # a lane wrote fastapi.py locally — stripping the REAL fastapi dep would
        # break the install; leave it and let the shadow surface elsewhere.
        # (custom-routes/seed_data still get stripped — they're skeleton-reserved.)
        be = self._mk_backend(files=("fastapi.py", "main.py"))
        rep = sanitize_pyproject_local_deps(be)
        self.assertNotIn("fastapi>=0.110", rep.get("dropped") or [])
        self.assertIn("fastapi>=0.110", (be / "pyproject.toml").read_text())

    def test_package_dir_counts_as_local_module(self):
        be = self._mk_backend(files=("main.py",))
        (be / "custom_routes").mkdir()
        (be / "custom_routes" / "__init__.py").write_text("")
        rep = sanitize_pyproject_local_deps(be)
        self.assertTrue(rep["repaired"])
        self.assertIn("custom-routes", rep["dropped"])

    def test_no_pyproject_is_graceful(self):
        d = Path(tempfile.mkdtemp())
        rep = sanitize_pyproject_local_deps(d)
        self.assertFalse(rep.get("repaired"))

    def test_underscore_dash_dot_normalization(self):
        py = PYPROJECT.replace('"custom-routes",', '"Custom_Routes.v2",')
        be = self._mk_backend(pyproject=py, files=("custom_routes_v2.py", "main.py"))
        rep = sanitize_pyproject_local_deps(be)
        # PEP503: Custom_Routes.v2 → custom-routes-v2; local custom_routes_v2 →
        # custom-routes-v2 — match, strip.
        self.assertTrue(rep["repaired"])


class SkeletonReservedModuleTests(unittest.TestCase):
    """tiktok-r5's ACTUAL root: custom_routes.py was ABSENT, so the skeleton's
    own ``import custom_routes`` hook in main.py looked third-party to
    _lane_third_party_imports and the FRAMEWORK ITSELF wrote 'custom_routes'
    into pyproject dependencies → uv failed → docker_up wedged → STUCK-ABORT.
    Skeleton-owned module names must never become pip deps, file present or
    not — and the sanitizer must clean r5-style corpses the same way."""

    def test_skeleton_import_never_becomes_dep_even_when_file_absent(self):
        d = Path(tempfile.mkdtemp())
        (d / "main.py").write_text(
            "import custom_routes as _custom_mod\nimport asyncpg\n")
        deps = _lane_third_party_imports(d)
        self.assertNotIn("custom_routes", deps)
        self.assertIn("asyncpg", deps)  # real third-party still unioned

    def test_sanitize_strips_reserved_name_when_file_absent(self):
        d = Path(tempfile.mkdtemp())
        (d / "main.py").write_text("# no custom_routes.py on disk\n")
        (d / "pyproject.toml").write_text(
            '[project]\nname = "x"\ndependencies = [\n'
            '  "fastapi>=0.115",\n  "custom_routes",\n  "psycopg2-binary",\n]\n')
        rep = sanitize_pyproject_local_deps(d)
        self.assertTrue(rep["repaired"])
        self.assertIn("custom_routes", rep["dropped"])
        out = (d / "pyproject.toml").read_text()
        self.assertIn("psycopg2-binary", out)  # allowlisted real dist kept

    def test_reserved_set_covers_the_skeleton_writes(self):
        for name in ("custom_routes", "database", "models", "seed_data",
                     "main", "schemas", "auth_dependency"):
            self.assertIn(name, _SKELETON_LOCAL_MODULES)


if __name__ == "__main__":
    unittest.main()


class Test242InvalidPep508Name(unittest.TestCase):
    """#242 (tiktok r32 STUCK-ABORT): a hallucinated dep with an INVALID PEP-508
    name (not a local module — '_framework' → normalized '-framework') can never
    resolve on PyPI → pip install fails → docker build fails → abort. #189 only
    caught local-module deps; this catches the invalid-name class."""

    def _write(self, deps):
        d = Path(tempfile.mkdtemp())
        body = "\n".join(f'    "{x}",' for x in deps)
        (d / "pyproject.toml").write_text(
            f'[project]\nname = "backend"\ndependencies = [\n{body}\n]\n')
        return d

    def test_framework_placeholder_dropped(self):
        d = self._write(["fastapi>=0.115", "_framework", "psycopg2-binary"])
        r = sanitize_pyproject_local_deps(d)
        self.assertTrue(r.get("repaired"))
        self.assertIn("_framework", r.get("dropped"))
        txt = (d / "pyproject.toml").read_text()
        self.assertNotIn("_framework", txt)
        self.assertIn("fastapi", txt)
        self.assertIn("psycopg2-binary", txt)  # valid name with digits+hyphen kept

    def test_valid_names_all_kept(self):
        deps = ["fastapi>=0.115", "uvicorn[standard]>=0.30", "psycopg[binary]>=3.1",
                "python-multipart>=0.0.9", "pyjwt[crypto]>=2.8", "psycopg2-binary"]
        d = self._write(deps)
        r = sanitize_pyproject_local_deps(d)
        self.assertFalse(r.get("repaired"), f"valid deps wrongly dropped: {r.get('dropped')}")

    def test_leading_and_trailing_separator_dropped(self):
        d = self._write(["fastapi", "-badname", "trailing-", "_underscore"])
        r = sanitize_pyproject_local_deps(d)
        dropped = r.get("dropped") or []
        self.assertEqual(sorted(dropped), ["-badname", "_underscore", "trailing-"])


if __name__ == "__main__":
    unittest.main()
