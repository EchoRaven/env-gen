"""#490 — post-heal package.json dependency sync (netflix r63, 2026-08-04).

A bare import added to src AFTER scaffold-time pin_frontend_build_tooling — most importantly the
`import { X } from 'lucide-react'` that repair_frontend_unimported_icons injects during the
per-tick HEAL — is never added to package.json, so the vite build fails at docker_up with
"missing npm dependency". r63 wedged EXACTLY here (one blocker from the first-ever delivery): the
icon heal injected `import { LoginPageRoute } from 'lucide-react'` into App.jsx, lucide-react was
undeclared, and the safe-icon plugin's `import * as _real from 'lucide-react'` (virtualizes bad
NAMES but still imports the real PACKAGE) failed the build. sync_frontend_package_json_deps
re-syncs package.json deps against the final src tree, post-heal."""
import json
import tempfile
from pathlib import Path

from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    sync_frontend_package_json_deps)


def _mk(pkg: dict, files: dict):
    tmp = Path(tempfile.mkdtemp())
    fe = tmp / "app" / "frontend"
    (fe / "src").mkdir(parents=True)
    (fe / "package.json").write_text(json.dumps(pkg), encoding="utf-8")
    for rel, txt in files.items():
        p = fe / "src" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(txt, encoding="utf-8")
    return fe


_BASE_PKG = {
    "dependencies": {"react": "^18.3.1", "react-dom": "^18.3.1",
                     "react-router-dom": "^6.26.0"},
    "devDependencies": {"vite": "^5.3.1"},
}


def _deps(fe):
    return json.loads((fe / "package.json").read_text())["dependencies"]


def test_adds_lucide_react_when_imported_but_undeclared():
    # exactly the r63 case: App.jsx imports lucide-react, package.json lacks it
    fe = _mk(_BASE_PKG, {
        "App.jsx": "import { LoginPageRoute } from 'lucide-react';\n"
                   "export default function App(){ return null; }\n"})
    out = sync_frontend_package_json_deps(fe)
    assert any("lucide-react" in a for a in out.get("added", [])), out
    assert "lucide-react" in _deps(fe), "lucide-react must be declared so the build resolves it"


def test_idempotent_when_already_declared():
    pkg = {"dependencies": {**_BASE_PKG["dependencies"], "lucide-react": "^0.408.0"}}
    fe = _mk(pkg, {"App.jsx": "import { Home } from 'lucide-react';\n"})
    out = sync_frontend_package_json_deps(fe)
    assert out.get("added") == [], "already-declared dep must not be re-added"
    assert _deps(fe)["lucide-react"] == "^0.408.0", "existing version must be preserved"


def test_framework_roots_never_added():
    # react / react-dom / react-router-dom are framework-provided roots
    fe = _mk({"dependencies": {}}, {
        "App.jsx": "import React from 'react';\nimport { Routes } from 'react-router-dom';\n"})
    out = sync_frontend_package_json_deps(fe)
    assert out.get("added") == [], out


def test_relative_and_noninstallable_skipped():
    fe = _mk(_BASE_PKG, {
        "App.jsx": ("import x from './local';\nimport y from '../svc/api';\n"
                    "import fs from 'node:fs';\nimport v from 'virtual:foo';\n")})
    out = sync_frontend_package_json_deps(fe)
    assert out.get("added") == [], f"relative/node:/virtual: must never be added: {out}"


def test_scoped_package_added_as_scope_pkg():
    fe = _mk(_BASE_PKG, {
        "Icon.jsx": "import { Cog } from '@heroicons/react/24/solid';\n"})
    out = sync_frontend_package_json_deps(fe)
    assert "@heroicons/react" in _deps(fe), out
    # sub-path must NOT leak into the dep key
    assert not any(k.count("/") > 1 for k in _deps(fe)), _deps(fe)


def test_common_lib_gets_pinned_version_not_latest():
    fe = _mk(_BASE_PKG, {"App.jsx": "import { Home } from 'lucide-react';\n"})
    sync_frontend_package_json_deps(fe)
    # lucide-react is in _COMMON_FRONTEND_LIBS → a pinned version, not bare "latest"
    assert _deps(fe)["lucide-react"] != "latest", "known-common libs must be pinned"


def test_best_effort_no_package_json():
    tmp = Path(tempfile.mkdtemp())
    fe = tmp / "app" / "frontend"
    (fe / "src").mkdir(parents=True)
    (fe / "src" / "App.jsx").write_text("import { X } from 'lucide-react';\n")
    assert sync_frontend_package_json_deps(fe) == {"added": []}


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
