"""#566e (netflix r117 — 75-min M1 timeout via ui-page churn): the App.jsx ROUTE analogue of #566b.
The delivery gate audits integration's App.jsx and hard-blocks on `route `/x` not wired in App.jsx`.
A frontend lane's committed App.jsx route edit reaches integration only via a conflict-abort/supersede
merge, so it can sit unmerged across every gate poll → deliverability_ui_page_unwired stays red →
re-dispatch churn (96 finishes in ~9 min) → no-deliver timeout.

reconcile_integration_frontend_app_jsx wires every declared ui_page route into the integration App.jsx
before the audit reads, reusing frontend_scaffold.project_missing_ui_routes (additive, idempotent, uses
the gate's exact _route_is_wired predicate; never removes/rewrites a lane route). Best-effort; byte-
identical once all routes are wired. Generalizable; no product literals.
"""
from pathlib import Path

from env_generator.llm_generator.multi_agent.runtime.heal_pipeline import (
    reconcile_integration_frontend_app_jsx,
)

_APP_JSX = """import { BrowserRouter, Routes, Route } from 'react-router-dom';
import LandingPage from './pages/LandingPage.jsx';

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<LandingPage />} />
      </Routes>
    </BrowserRouter>
  );
}
"""


def _write_app(repo: Path, text: str) -> Path:
    p = repo / "app" / "frontend" / "src" / "App.jsx"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def test_unwired_declared_route_gets_injected(tmp_path):
    app = _write_app(tmp_path, _APP_JSX)
    pages = [{"route": "/", "component": "LandingPage"},
             {"route": "/games", "component": "GamesPage"}]
    res = reconcile_integration_frontend_app_jsx(tmp_path, pages)
    assert res.get("count") == 1, res
    assert res.get("injected") == ["/games"], res
    txt = app.read_text()
    assert 'path="/games"' in txt, txt
    assert "GamesPage" in txt  # <Route element> + import both reference it


def test_idempotent_second_call_is_noop(tmp_path):
    app = _write_app(tmp_path, _APP_JSX)
    pages = [{"route": "/games", "component": "GamesPage"}]
    reconcile_integration_frontend_app_jsx(tmp_path, pages)
    after_first = app.read_text()
    res2 = reconcile_integration_frontend_app_jsx(tmp_path, pages)
    assert res2 == {}, res2  # route now wired → no-op
    assert app.read_text() == after_first  # byte-identical


def test_already_wired_route_is_noop(tmp_path):
    app = _write_app(tmp_path, _APP_JSX)
    pages = [{"route": "/", "component": "LandingPage"}]  # already wired
    res = reconcile_integration_frontend_app_jsx(tmp_path, pages)
    assert res == {}, res
    assert app.read_text() == _APP_JSX  # untouched


def test_missing_app_jsx_returns_empty(tmp_path):
    # no App.jsx on disk → nothing to reconcile, no raise
    assert reconcile_integration_frontend_app_jsx(tmp_path, [{"route": "/x", "component": "X"}]) == {}


def test_garbage_input_never_raises():
    assert reconcile_integration_frontend_app_jsx("/nonexistent/xyz", None) == {}
    assert reconcile_integration_frontend_app_jsx("/nonexistent/xyz",
                                                  [{"bogus": 1}]) == {}


def test_no_pages_is_noop(tmp_path):
    app = _write_app(tmp_path, _APP_JSX)
    assert reconcile_integration_frontend_app_jsx(tmp_path, []) == {}
    assert app.read_text() == _APP_JSX


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
