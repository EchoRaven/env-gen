"""PROPOSAL #7 / FIX #48: normalize wrong-module imports of get_current_user.

The framework scaffolds the canonical auth dependency at app/backend/auth_dependency.py
(its docstring: "handlers import get_current_user from here so auth is enforced by
construction"). But lane-authored route modules guess the wrong module —
`from oauth_routes import get_current_user` (oauth_routes only exposes build_router) —
so the backend crashes on startup with ImportError and backend_health fails forever
(run #12 / run #18). repair_backend_auth_dependency only rewrote placeholder DEFINITIONS,
not wrong-module IMPORTS, so the guess survived.

This guards the AST-precise import-normalization repair: repoint every
`from <X> import ... get_current_user ...` (X != auth_dependency) at auth_dependency,
preserving co-imported names and aliases; idempotent; AST-validated; best-effort.
"""

import ast
import sys
import tempfile
import unittest
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.backend_scaffold import (  # noqa: E402
    _normalize_auth_imports_in_src,
    repair_auth_import_paths,
)


class NormalizeAuthImportSrcTests(unittest.TestCase):
    """The pure string→string AST transform."""

    def test_single_wrong_module_repointed(self):
        src = "from oauth_routes import get_current_user\n"
        out = _normalize_auth_imports_in_src(src)
        self.assertIn("from auth_dependency import get_current_user", out)
        self.assertNotIn("from oauth_routes import get_current_user", out)
        ast.parse(out)  # still valid

    def test_co_imported_names_preserved_on_original_module(self):
        src = "from oauth_routes import get_current_user, build_router\n"
        out = _normalize_auth_imports_in_src(src)
        ast.parse(out)
        # build_router stays sourced from oauth_routes; get_current_user from auth_dependency
        self.assertIn("from auth_dependency import get_current_user", out)
        self.assertRegex(out, r"from oauth_routes import .*build_router")
        self.assertNotRegex(out, r"from oauth_routes import[^\n]*get_current_user")

    def test_alias_preserved(self):
        src = "from oauth_routes import get_current_user as gcu\n"
        out = _normalize_auth_imports_in_src(src)
        ast.parse(out)
        self.assertIn("from auth_dependency import get_current_user as gcu", out)

    def test_already_canonical_is_noop(self):
        src = "from auth_dependency import get_current_user\nx = 1\n"
        self.assertEqual(_normalize_auth_imports_in_src(src), src)

    def test_idempotent(self):
        src = "from oauth_routes import get_current_user\n"
        once = _normalize_auth_imports_in_src(src)
        twice = _normalize_auth_imports_in_src(once)
        self.assertEqual(once, twice)

    def test_unrelated_imports_untouched(self):
        src = "from fastapi import APIRouter, Depends\nfrom models import Video\n"
        self.assertEqual(_normalize_auth_imports_in_src(src), src)

    def test_local_real_def_untouched(self):
        # A module that DEFINES get_current_user locally (no wrong import) is unchanged —
        # this repair only touches IMPORT statements, never definitions.
        src = "def get_current_user(authorization=None):\n    return decode(authorization)\n"
        self.assertEqual(_normalize_auth_imports_in_src(src), src)

    def test_syntax_error_is_noop(self):
        src = "from oauth_routes import (\n"  # unbalanced
        self.assertEqual(_normalize_auth_imports_in_src(src), src)

    def test_surrounding_code_preserved(self):
        src = (
            "from fastapi import APIRouter\n"
            "from oauth_routes import get_current_user\n"
            "router = APIRouter()\n"
        )
        out = _normalize_auth_imports_in_src(src)
        ast.parse(out)
        self.assertIn("from fastapi import APIRouter", out)
        self.assertIn("router = APIRouter()", out)
        self.assertIn("from auth_dependency import get_current_user", out)


class RepairAuthImportPathsTests(unittest.TestCase):
    """The dir-level repair (best-effort, idempotent)."""

    def _mk(self, files: dict) -> Path:
        d = Path(tempfile.mkdtemp(prefix="authimp_"))
        for name, content in files.items():
            (d / name).write_text(content, encoding="utf-8")
        return d

    def test_rewrites_route_files_when_auth_dependency_exists(self):
        be = self._mk({
            "auth_dependency.py": "def get_current_user():\n    ...\n",
            "channel_routes.py": "from oauth_routes import get_current_user\n",
            "video_routes.py": "from oauth_routes import get_current_user, build_router\n",
        })
        rep = repair_auth_import_paths(be)
        self.assertTrue(rep["repaired"], rep)
        self.assertIn("channel_routes.py", rep["rewritten"])
        self.assertIn("video_routes.py", rep["rewritten"])
        self.assertIn("from auth_dependency import get_current_user",
                      (be / "channel_routes.py").read_text())

    def test_runs_with_no_placeholder_def_present(self):
        # The run #18 case: route files only IMPORT (wrong); no placeholder DEF anywhere.
        # The OLD repair early-returned "no placeholder"; this one must still fix imports.
        be = self._mk({
            "auth_dependency.py": "def get_current_user():\n    ...\n",
            "other_routes.py": "from oauth_routes import get_current_user\n",
        })
        rep = repair_auth_import_paths(be)
        self.assertTrue(rep["repaired"], rep)

    def test_excludes_runtime_owned_auth_infra(self):
        # oauth_routes.py itself (and the other AS modules) must NOT be rewritten.
        be = self._mk({
            "auth_dependency.py": "def get_current_user():\n    ...\n",
            # contrived: even if an infra file mentions the symbol, leave it alone
            "oauth_routes.py": "from somewhere import get_current_user\n",
        })
        rep = repair_auth_import_paths(be)
        self.assertEqual(rep.get("rewritten", []), [])
        self.assertIn("from somewhere import get_current_user",
                      (be / "oauth_routes.py").read_text())

    def test_guarded_when_no_auth_dependency(self):
        be = self._mk({"channel_routes.py": "from oauth_routes import get_current_user\n"})
        rep = repair_auth_import_paths(be)
        self.assertFalse(rep["repaired"])

    def test_idempotent_second_run_noop(self):
        be = self._mk({
            "auth_dependency.py": "def get_current_user():\n    ...\n",
            "channel_routes.py": "from oauth_routes import get_current_user\n",
        })
        repair_auth_import_paths(be)
        rep2 = repair_auth_import_paths(be)
        self.assertEqual(rep2.get("rewritten", []), [])


if __name__ == "__main__":
    unittest.main()
