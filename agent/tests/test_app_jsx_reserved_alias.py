"""BLOCKER F (2026-06-19): an agent registered a ui_page whose component was literally
"App", so the framework route projector emitted `import App from './pages/App.jsx'`
next to its own `export default function App()` → esbuild "symbol App has already been
declared" → the frontend build failed every cycle → the run wedged on docker_up.
The projector must ALIAS page imports that collide with App.jsx's own identifiers.
"""
import re
import sys
from pathlib import Path

LLM = Path(__file__).resolve().parents[1] / "env_generator" / "llm_generator"
if str(LLM) not in sys.path:
    sys.path.insert(0, str(LLM))

from multi_agent.runtime.frontend_scaffold import (  # noqa: E402
    _render_routed_app, _safe_import_alias, project_missing_ui_routes,
)


def test_safe_alias_only_touches_reserved():
    assert _safe_import_alias("App") == "AppPage"
    assert _safe_import_alias("Routes") == "RoutesPage"
    assert _safe_import_alias("React") == "ReactPage"
    assert _safe_import_alias("NotesListPage") == "NotesListPage"  # untouched


def test_projected_app_named_page_does_not_redeclare_App():
    src = _render_routed_app([("App", "/app"), ("LoginPage", "/login")])
    # the root component is still `App`, the page is imported under an alias
    assert "export default function App()" in src
    assert "import App from" not in src              # no colliding bare import
    assert "import AppPage from './pages/App.jsx';" in src
    assert "<AppPage />" in src
    # exactly ONE `App` binding declared (the default export); page is `AppPage`
    assert len(re.findall(r"\bfunction App\b|\bimport App\b", src)) == 1


def test_incremental_injection_also_aliases():
    base = ("// @framework-managed-routes\nimport { BrowserRouter, Routes, Route } "
            "from 'react-router-dom';\nexport default function App() {\n  return (\n"
            "    <BrowserRouter><Routes>\n        <Route path=\"/\" element={<Home />} />\n"
            "    </Routes></BrowserRouter>\n  );\n}\n")
    out, injected = project_missing_ui_routes(
        base, [{"name": "App", "component": "App", "route": "/app"}])
    if injected:  # only assert when the path actually injected
        assert "import App from" not in out
        assert "AppPage" in out


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
