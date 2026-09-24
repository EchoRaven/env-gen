"""Build-integrity: repair_frontend_missing_local_exports must re-export a local
binding that EXISTS but isn't exported, instead of skipping it. A component doing
`import { AuthContext } from '../App'` when App.jsx has `const AuthContext =
createContext()` (no export) HARD-fails the vite build ("AuthContext is not exported
by src/App.jsx") → frontend image won't build → docker_up FAIL → STUCK-ABORT, no
delivery (outlook run-7, 2026-06-30). The old guard skipped any name that appeared in
the target (to avoid a duplicate-declaration build break) — but that left the named
import unresolved. The fix appends `export { AuthContext };` (re-export the real
binding); a genuinely-missing name is still stubbed; this generalizes the api.js
duplicate-decl fix to ANY local module.
"""

from __future__ import annotations

import re
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
    repair_frontend_missing_local_exports)


def _fe(files):
    d = Path(tempfile.mkdtemp())
    for rel, txt in files.items():
        p = d / "src" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(txt, encoding="utf-8")
    return d


class LocalExportReexportDriftTests(unittest.TestCase):
    def test_declared_but_unexported_binding_is_reexported_not_duplicated(self):
        fe = _fe({
            "App.jsx": "import { createContext } from 'react';\n"
                       "const AuthContext = createContext();\n"
                       "function App(){ return null; }\nexport default App;\n",
            "components/TopBar.jsx": "import { AuthContext } from '../App';\n"
                                     "export default function TopBar(){ return null; }\n",
        })
        r = repair_frontend_missing_local_exports(fe)
        app = (fe / "src/App.jsx").read_text()
        self.assertIn("export { AuthContext };", app)            # re-exported the real binding
        self.assertEqual(len(re.findall(r"\bconst AuthContext\b", app)), 1)  # no duplicate decl
        self.assertNotIn("AuthContext = (props) => null", app)   # not a stub
        self.assertTrue(any("AuthContext" in str(x) for x in r.get("reexported", [])))

    def test_genuinely_missing_name_still_stubbed(self):
        fe = _fe({
            "icons.jsx": "export const Home = () => null;\n",
            "components/Nav.jsx": "import { TotallyMissingIcon } from '../icons';\n"
                                  "export default function Nav(){ return null; }\n",
        })
        repair_frontend_missing_local_exports(fe)
        icons = (fe / "src/icons.jsx").read_text()
        self.assertIn("export const TotallyMissingIcon", icons)  # appears nowhere → stubbed

    def test_correctly_exported_is_noop(self):
        fe = _fe({
            "ctx.jsx": "import { createContext } from 'react';\n"
                       "export const Ctx = createContext();\n",
            "components/X.jsx": "import { Ctx } from '../ctx';\n"
                                "export default function X(){ return null; }\n",
        })
        r = repair_frontend_missing_local_exports(fe)
        self.assertFalse(r.get("reexported"))
        self.assertFalse(r.get("repaired"))


if __name__ == "__main__":
    unittest.main()
