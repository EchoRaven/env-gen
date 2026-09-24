"""Build-integrity: a page importing { X } (named) from a default-only component
HARD-fails the Rollup build ("X is not exported") -> frontend image won't build ->
docker_up FAIL -> no delivery (live smoke-notes 2026-06-20: NotesListPage imported
{ NavBar } from a default-export NavBar.jsx). repair_frontend_named_default_imports
rewrites the single-name named import to a default import.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from multi_agent.runtime.frontend_scaffold import (  # noqa: E402
    repair_frontend_named_default_imports)


def _fe(files):
    d = Path(tempfile.mkdtemp())
    for rel, txt in files.items():
        p = d / "src" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(txt, encoding="utf-8")
    return d


class NamedDefaultImportRepairTests(unittest.TestCase):
    def test_named_import_of_default_is_rewritten(self):
        fe = _fe({
            "components/NavBar.jsx": "function NavBar(){return null}\nexport default NavBar;\n",
            "pages/NotesListPage.jsx": "import { NavBar } from '../components/NavBar';\nexport default function P(){return <NavBar/>;}\n",
        })
        r = repair_frontend_named_default_imports(fe)
        self.assertTrue(r["repaired"])
        txt = (fe / "src/pages/NotesListPage.jsx").read_text()
        self.assertIn("import NavBar from '../components/NavBar'", txt)
        self.assertNotIn("{ NavBar }", txt)

    def test_genuine_named_export_left_alone(self):
        # NavBar IS a named export → don't touch it.
        fe = _fe({
            "components/NavBar.jsx": "export const NavBar = () => null;\n",
            "pages/P.jsx": "import { NavBar } from '../components/NavBar';\n",
        })
        r = repair_frontend_named_default_imports(fe)
        self.assertFalse(r["repaired"])
        self.assertIn("{ NavBar }", (fe / "src/pages/P.jsx").read_text())

    def test_multi_name_import_not_touched(self):
        # ambiguous (which one is the default?) → leave it.
        fe = _fe({
            "components/Bits.jsx": "export const A=1;\nexport default function(){};\n",
            "pages/P.jsx": "import { A, B } from '../components/Bits';\n",
        })
        r = repair_frontend_named_default_imports(fe)
        self.assertFalse(r["repaired"])

    def test_non_local_import_untouched(self):
        # react/library named imports must never be rewritten.
        fe = _fe({"pages/P.jsx": "import { useState } from 'react';\n"})
        r = repair_frontend_named_default_imports(fe)
        self.assertFalse(r["repaired"])
        self.assertIn("{ useState }", (fe / "src/pages/P.jsx").read_text())

    def test_no_default_export_target_untouched(self):
        # target has neither the named export nor a default → can't safely rewrite.
        fe = _fe({
            "components/X.jsx": "export const Other = 1;\n",
            "pages/P.jsx": "import { Missing } from '../components/X';\n",
        })
        r = repair_frontend_named_default_imports(fe)
        self.assertFalse(r["repaired"])


if __name__ == "__main__":
    unittest.main()
