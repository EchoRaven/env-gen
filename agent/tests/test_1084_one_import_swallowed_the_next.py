r"""#1084 — one `from ... import a, b, c` swallowed every import line after it.

`_PY_IMPORT_RE`'s name class is `[\w\.,\s\*]+`, and `\s` matches NEWLINES. So in the backend
main.py every generated app ships:

    from fastapi import Depends, FastAPI, HTTPException, Query
    from fastapi.middleware.cors import CORSMiddleware
    from sqlalchemy import or_
    from sqlalchemy.orm import Session
    from database import Base, engine, get_db
    from auth_dependency import get_current_user
    import models

the FIRST statement matches through all of them — the scanner reports one import of `fastapi`
whose "names" are `['Depends', 'FastAPI', 'HTTPException', 'Query\nfrom
fastapi.middleware.cors import CORSMiddleware\n…from database import Base', 'engine',
'get_db\nfrom auth_dependency import get_current_user\nimport models']`. `database`,
`auth_dependency` and `models` are never seen as imported at all, so the consumer graph is
missing them and `scan_dead_files` calls them DEAD — modules the app cannot start without.

Measured over the 83 generated backends, parsing the same files with `ast` instead removes
**212 of 1010** dead-file findings, and every path it removes was false in 100% of the runs
it appeared in:

    backend/oauth_routes.py     83 of 83 runs
    backend/auth_dependency.py  58
    backend/database.py         53
    backend/jwt_manager.py      17
    backend/tenant_routes.py     1

It removes nothing else: `backend/schemas.py` (66 runs) stays flagged, and is genuinely
unimported — grep for `schemas` across run63's backend returns no import at all.

This feeds `deliverability_dead_artifacts` (660 occurrences across 201 run logs). The gate is
already softened to fire only when the app is NOT functionally validated — i.e. exactly the
struggling runs — and the deliverability comment records the symptom without the cause
("smoke #14: 17 'dead' artifacts, all real+used"). A Python parser is the right tool for
Python imports; the regex stays as the fallback for a file that does not parse.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from tempfile import mkdtemp

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime.coverage_audit import scan_dead_files  # noqa: E402

_MAIN = """import os
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from database import Base, engine, get_db
from auth_dependency import get_current_user
import models
from custom_routes import router as custom_router

app = FastAPI()
app.include_router(custom_router)
"""


def _app(files: dict) -> Path:
    root = Path(mkdtemp())
    be = root / "backend"
    be.mkdir()
    for name, text in files.items():
        (be / name).write_text(text, encoding="utf-8")
    return root


def _dead(files: dict):
    return {d["path"] for d in scan_dead_files(_app(files))}


class TheSwallowedImportsAreSeen(unittest.TestCase):

    def test_the_real_main_py_shape(self):
        dead = _dead({"main.py": _MAIN,
                      "database.py": "Base = object()\nengine = None\ndef get_db(): pass\n",
                      "auth_dependency.py": "def get_current_user(): pass\n",
                      "models.py": "class User: pass\n",
                      "custom_routes.py": "router = None\n"})
        for mod in ("backend/database.py", "backend/auth_dependency.py",
                    "backend/models.py", "backend/custom_routes.py"):
            self.assertNotIn(mod, dead, f"{mod} read dead; app cannot start without it")

    def test_a_parenthesised_multiline_import_resolves(self):
        main = ("from database import (\n    Base,\n    engine,\n    get_db,\n)\n"
                "app = None\n")
        dead = _dead({"main.py": main,
                      "database.py": "Base = object()\nengine = None\ndef get_db(): pass\n"})
        self.assertNotIn("backend/database.py", dead)

    def test_an_aliased_import_resolves(self):
        dead = _dead({"main.py": "import jwt_manager as jm\napp = None\n",
                      "jwt_manager.py": "def encode(): pass\n"})
        self.assertNotIn("backend/jwt_manager.py", dead)

    def test_a_relative_import_still_resolves(self):
        dead = _dead({"main.py": "from .oauth_store import STORE\napp = None\n",
                      "oauth_store.py": "STORE = {}\n"})
        self.assertNotIn("backend/oauth_store.py", dead)


class TrueDeadCodeStillReads(unittest.TestCase):
    """Narrower graph gaps, not a weaker gate — run63's schemas.py is imported by nobody."""

    def test_an_unimported_module_is_still_dead(self):
        dead = _dead({"main.py": "import models\napp = None\n",
                      "models.py": "class User: pass\n",
                      "schemas.py": "class UserOut: pass\n"})
        self.assertIn("backend/schemas.py", dead)
        self.assertNotIn("backend/models.py", dead)


class AnUnparseableFileNeverRaises(unittest.TestCase):

    def test_a_syntax_error_falls_back_instead_of_exploding(self):
        dead = _dead({"main.py": "from database import Base\nthis is not python(((\n",
                      "database.py": "Base = object()\n"})
        self.assertIsInstance(dead, set)
        self.assertNotIn("backend/database.py", dead)


if __name__ == "__main__":
    unittest.main()
