"""Frontend build-integrity generality (youtube 2026-06-20):

1. AUTO-ADD must pull in EVERY imported third-party lib, not just a curated set
   (lane imported lucide-react → not in the allowlist → Rollup "failed to resolve"
   → docker_up FAILED → no delivery). Pinned version if known, "latest" otherwise.
   A name guard keeps node:/virtual: specifiers out of package.json.
2. The forced vite.config carries the safe-icon plugin so a HALLUCINATED named icon
   (import { ClosedCaption } from 'lucide-react') degrades to a fallback instead of
   hard-failing the build.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from multi_agent.runtime import frontend_scaffold as fs  # noqa: E402


def _frontend(imports_src: str):
    d = Path(tempfile.mkdtemp())
    fe = d / "frontend"
    (fe / "src").mkdir(parents=True)
    (fe / "package.json").write_text(json.dumps({
        "name": "app-frontend", "version": "0.1.0",
        "dependencies": {"react": "^18.3.1", "react-dom": "^18.3.1"},
        "devDependencies": {"vite": "^5.4.0"},
    }), encoding="utf-8")
    (fe / "src" / "App.jsx").write_text(imports_src, encoding="utf-8")
    (fe / "src" / "main.jsx").write_text("import './index.css';\n", encoding="utf-8")
    return fe


def _deps(fe):
    return json.loads((fe / "package.json").read_text())["dependencies"]


class DepAutoAddGeneralTests(unittest.TestCase):
    def test_installable_pkg_guard(self):
        ok = ["lucide-react", "@heroicons/react", "date-fns", "react-icons"]
        bad = ["", "node:fs", "virtual:uno.css", "Foo/Bar", "http://x"]
        for r in ok:
            self.assertTrue(fs._is_installable_pkg(r), r)
        for r in bad:
            self.assertFalse(fs._is_installable_pkg(r), r)

    def test_uncurated_lib_added_as_latest(self):
        fe = _frontend("import Thing from 'some-rare-lib';\n")
        fs.pin_frontend_build_tooling(fe)
        deps = _deps(fe)
        self.assertEqual(deps.get("some-rare-lib"), "latest")

    def test_curated_lib_added_pinned(self):
        fe = _frontend("import { Play } from 'lucide-react';\n")
        fs.pin_frontend_build_tooling(fe)
        self.assertEqual(_deps(fe).get("lucide-react"), fs._COMMON_FRONTEND_LIBS["lucide-react"])

    def test_subpath_import_normalized(self):
        fe = _frontend("import { FaPlay } from 'react-icons/fa';\n")
        fs.pin_frontend_build_tooling(fe)
        deps = _deps(fe)
        self.assertIn("react-icons", deps)
        self.assertNotIn("react-icons/fa", deps)

    def test_virtual_and_node_specifiers_never_added(self):
        fe = _frontend("import 'virtual:uno.css';\nimport fs2 from 'node:fs';\n")
        fs.pin_frontend_build_tooling(fe)
        deps = _deps(fe)
        self.assertNotIn("virtual:uno.css", deps)
        self.assertNotIn("node:fs", deps)
        self.assertNotIn("virtual", deps)

    def test_framework_roots_not_duplicated(self):
        fe = _frontend("import ReactDOM from 'react-dom/client';\n")
        fs.pin_frontend_build_tooling(fe)
        deps = _deps(fe)
        # react-dom already declared; not re-pinned to latest
        self.assertEqual(deps.get("react-dom"), "^18.3.1")

    def test_vite_config_has_safe_icon_plugin(self):
        self.assertIn("safeIconImports", fs._BASELINE_VITE)
        self.assertIn("plugins:", fs._BASELINE_VITE)
        # the fallback path: real export OR generic icon
        self.assertIn("_real[", fs._BASELINE_VITE)


if __name__ == "__main__":
    unittest.main()
