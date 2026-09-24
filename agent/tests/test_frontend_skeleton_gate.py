"""FRONTEND SKELETON + FRONTEND GATE — the frontend gets the same two guarantees
the backend already has:

1. By-construction generation that does NOT depend on the lane: when the frontend
   lane declares zero ui_pages (it stalled/authored nothing — instagram 1.0.0
   shipped a blank shell). Projection itself was REMOVED 2026-06-11 (user
   decision: no framework-authored UI) — kept here: the gate + infra repairs from
   the API contract itself, and the page projector builds them.
2. A delivery gate: `frontend_navigable` fails api_smoke when the UI has no page
   components or no routes — a blank shell can no longer release.
"""

import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.validation_runner import _frontend_navigable  # noqa: E402

_EPS = [
    {"method": "GET", "path": "/api/feed"},
    {"method": "GET", "path": "/api/explore"},
    {"method": "POST", "path": "/api/posts"},
    {"method": "GET", "path": "/api/messages/conversations"},
]


def test_gate_fails_blank_shell(tmp_path):
    """The instagram 1.0.0 case: App.jsx exists but 0 pages / 0 routes → gate FAILS."""
    fe = tmp_path / "app" / "frontend" / "src"
    fe.mkdir(parents=True)
    (fe / "App.jsx").write_text("export default function App(){return <div/>;}\n",
                                encoding="utf-8")
    ok, detail = _frontend_navigable(tmp_path)
    assert not ok
    assert "blank shell" in detail


def test_gate_fails_missing_frontend_entirely(tmp_path):
    ok, _ = _frontend_navigable(tmp_path)
    assert not ok


def test_gate_passes_real_pages_and_routes(tmp_path):
    fe = tmp_path / "app" / "frontend" / "src"
    (fe / "pages").mkdir(parents=True)
    (fe / "pages" / "FeedPage.jsx").write_text("export default ()=>null;\n", encoding="utf-8")
    (fe / "App.jsx").write_text(
        '<Routes><Route path="/feed" element={<FeedPage/>}/></Routes>\n', encoding="utf-8")
    ok, detail = _frontend_navigable(tmp_path)
    assert ok, detail


def _fe_with_placeholder_root(tmp_path):
    fe = tmp_path / "app" / "frontend"
    (fe / "src" / "pages").mkdir(parents=True)
    (fe / "src" / "pages" / "FeedPage.jsx").write_text(
        "export default function FeedPage() { return <div>feed</div>; }\n",
        encoding="utf-8")
    (fe / "src" / "App.jsx").write_text(
        "import { BrowserRouter, Routes, Route } from 'react-router-dom';\n"
        "import FeedPage from './pages/FeedPage';\n"
        "export default function App() {\n  return (\n    <BrowserRouter>\n"
        "      <Routes>\n"
        '          <Route path="/" element={<div>This section is being set up.</div>} />\n'
        '          <Route path="/feed" element={<FeedPage />} />\n'
        "      </Routes>\n    </BrowserRouter>\n  );\n}\n",
        encoding="utf-8")
    (fe / "src" / "services").mkdir(parents=True)
    (fe / "src" / "services" / "api.js").write_text(
        "async function request(path, opts) { return fetch(path, opts); }\n"
        "export { request };\n", encoding="utf-8")
    return fe


def test_pin_writes_global_401_guard(tmp_path):
    """pin_frontend_build_tooling ships the 401→/login fetch guard wired into
    main.jsx — unauthenticated visits must land on /login, not a dead page."""
    from multi_agent.runtime.frontend_scaffold import pin_frontend_build_tooling
    fe = tmp_path / "frontend"
    (fe / "src").mkdir(parents=True)
    (fe / "src" / "main.jsx").write_text(
        "import './index.css';\nimport React from 'react';\n", encoding="utf-8")
    pin_frontend_build_tooling(fe)
    guard = fe / "src" / "bc_auth.js"
    gtxt = guard.read_text(encoding="utf-8")
    # both transports: lanes write api layers with fetch OR axios (XHR)
    assert "401" in gtxt and "XMLHttpRequest" in gtxt and "window.fetch" in gtxt
    assert "import './bc_auth.js';" in (fe / "src" / "main.jsx").read_text(encoding="utf-8")


def test_api_helpers_upgrade_old_by_construction_block(tmp_path):
    """An older appended helpers block (no 401 redirect) is upgraded in place;
    a lane's OWN apiGet is never rewritten."""
    from multi_agent.runtime.frontend_page_projector import _ensure_api_helpers
    api = tmp_path / "api.js"
    api.write_text(
        "async function request(path, opts) { return fetch(path, opts); }\n"
        "\n\n// === BY-CONSTRUCTION: generic helpers for projected pages.\n"
        "export async function apiGet(path) {\n  return request(path);\n}\n",
        encoding="utf-8")
    assert _ensure_api_helpers(api) is True
    txt = api.read_text(encoding="utf-8")
    assert "_bcAuthRedirect" in txt and txt.count("export async function apiGet") == 1
    # lane-authored helpers (no marker) stay untouched
    lane = tmp_path / "lane_api.js"
    lane.write_text("export const apiGet = async (u) => fetch(u);\n", encoding="utf-8")
    assert _ensure_api_helpers(lane) is False




def test_navigable_accepts_any_src_layout(tmp_path):
    """GENERALITY (round 34): the lane owns the layout — page components in
    components/ (or anywhere under src/) count; only entry files don't."""
    from multi_agent.runtime.validation_runner import _frontend_navigable
    src = tmp_path / "app" / "frontend" / "src" / "components"
    src.mkdir(parents=True)
    (src / "LoginPage.jsx").write_text("export default () => null;")
    (src.parent / "App.jsx").write_text('<Routes><Route path="/login" /></Routes>')
    ok, detail = _frontend_navigable(tmp_path)
    assert ok, detail
