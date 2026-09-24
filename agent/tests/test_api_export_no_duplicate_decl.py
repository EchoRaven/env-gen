"""Build-integrity: repair_frontend_api_exports must NOT create a duplicate `api`
declaration. A component doing `import { api }` (named) when api.js has
`const api = {...}; export default api;` (default only) used to get an appended
`export const api = <stub>` → vite "Identifier 'api' has already been declared"
→ frontend build fail → docker_up FAIL → delivery-gate cascade (outlook run-5 M2,
2026-06-30, only M1 shipped). The fix re-exports the EXISTING binding
(`export { api };`) so the named import resolves to the REAL value, no duplicate.
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

from multi_agent.runtime.frontend_scaffold import repair_frontend_api_exports  # noqa: E402

_API_JS = (
    "function authHeaders(){return {}}\n"
    "export const get = (p) => fetch(p);\n"
    "const register = (b) => get('/auth/register');\n"
    "const api = { register, get };\n"
    "export default api;\n"
)


def _fe(files):
    d = Path(tempfile.mkdtemp())
    for rel, txt in files.items():
        p = d / "src" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(txt, encoding="utf-8")
    return d


class ApiExportNoDuplicateDeclTests(unittest.TestCase):
    def test_named_import_of_already_declared_api_is_reexported_not_duplicated(self):
        fe = _fe({
            "services/api.js": _API_JS,
            "pages/InboxPage.jsx": "import { api } from '../services/api';\n"
                                   "export default function P(){ api.get('/x'); return null; }\n",
        })
        r = repair_frontend_api_exports(fe)
        self.assertTrue(r.get("repaired"), r)
        self.assertIn("api", r.get("reexported", []))
        txt = (fe / "src/services/api.js").read_text()
        # re-exported the existing binding …
        self.assertIn("export { api };", txt)
        # … and did NOT append a SECOND `const api` / `export const api`
        self.assertEqual(len(re.findall(r"\bconst api\b", txt)), 1)
        self.assertNotIn("export const api =", txt)
        self.assertNotIn("api not implemented (auto-stub)", txt)

    def test_genuinely_missing_name_still_stubbed_or_aliased(self):
        fe = _fe({
            "services/api.js": _API_JS,
            "pages/WidgetsPage.jsx": "import { getWidgets } from '../services/api';\n"
                                     "export default function P(){ getWidgets(); return null; }\n",
        })
        r = repair_frontend_api_exports(fe)
        self.assertTrue(r.get("repaired"), r)
        txt = (fe / "src/services/api.js").read_text()
        self.assertIn("export const getWidgets", txt)   # not a pre-declared name → stub/alias as before

    def test_no_drift_is_a_noop(self):
        fe = _fe({
            "services/api.js": _API_JS,
            "pages/OkPage.jsx": "import api from '../services/api';\n"  # default import — fine
                                "export default function P(){ api.get('/x'); return null; }\n",
        })
        r = repair_frontend_api_exports(fe)
        self.assertFalse(r.get("repaired"), r)


if __name__ == "__main__":
    unittest.main()
