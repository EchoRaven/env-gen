"""Frontend dangling-import stub scaffolder.

Root fix for the frontend half of the hollow-release bug (instagram MM,
2026-06-08): the frontend lane imports a page it never creates
(``import MessagesInboxPage from './pages/MessagesInboxPage'``) → ``npm run build``
fails → the frontend container can't boot. The framework scaffolds a valid
default-exported stub at the expected path so the app always builds.
"""

import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.frontend_scaffold import (  # noqa: E402
    scaffold_missing_local_pages,
)

_APP = """
import HomeFeedPage from './pages/HomeFeedPage';
import MessagesInboxPage from './pages/MessagesInboxPage';
import MessageThreadPage from './pages/MessageThreadPage';
import { getFeed } from './services/api';
import useAuth from './hooks/useAuth';

export default function App() { return null; }
"""


def _frontend(tmp_path):
    src = tmp_path / "src"
    (src / "pages").mkdir(parents=True)
    (src / "services").mkdir()
    (src / "App.jsx").write_text(_APP, encoding="utf-8")
    # HomeFeedPage exists; the two Messages pages do NOT
    (src / "pages" / "HomeFeedPage.jsx").write_text("export default function H(){return null;}", encoding="utf-8")
    (src / "services" / "api.js").write_text("export const getFeed = async () => [];", encoding="utf-8")
    return tmp_path


def test_scaffolds_only_missing_page_imports(tmp_path):
    fe = _frontend(tmp_path)
    res = scaffold_missing_local_pages(fe)
    scaffolded = res["scaffolded"]
    # the two missing Messages pages get stubs; the existing HomeFeedPage does not
    assert any("MessagesInboxPage.jsx" in s for s in scaffolded)
    assert any("MessageThreadPage.jsx" in s for s in scaffolded)
    assert not any("HomeFeedPage" in s for s in scaffolded)
    assert (fe / "src" / "pages" / "MessagesInboxPage.jsx").exists()


def test_stub_has_default_export_so_import_resolves(tmp_path):
    fe = _frontend(tmp_path)
    scaffold_missing_local_pages(fe)
    stub = (fe / "src" / "pages" / "MessageThreadPage.jsx").read_text(encoding="utf-8")
    assert "export default function MessageThreadPage()" in stub


def test_does_not_stub_hooks_or_services(tmp_path):
    """./hooks/useAuth and ./services/api are NOT component dirs — never stubbed
    (stubbing a hook as a component would be wrong)."""
    fe = _frontend(tmp_path)
    scaffold_missing_local_pages(fe)
    assert not (fe / "src" / "hooks" / "useAuth.jsx").exists()


def test_idempotent(tmp_path):
    fe = _frontend(tmp_path)
    assert len(scaffold_missing_local_pages(fe)["scaffolded"]) == 2
    assert scaffold_missing_local_pages(fe)["scaffolded"] == []  # 2nd run: nothing
