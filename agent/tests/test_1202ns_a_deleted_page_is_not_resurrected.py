"""#1202ns: the #566b page reconcile does not resurrect a page integration deleted.

`reconcile_integration_frontend_pages` treated a MISSING integration page as a stub and copied a
lane worktree's "real" copy over it. tiktok-r125 M3: the frontend deleted `MessagesPage.jsx` (a
dead file) at 10:12; its own worktree still held the file; the reconcile — run with no logger on
every delivery-gate evaluation — wrote it back, framework delivery committed it at 10:18 and
10:33, the coverage audit flagged the dead file again, and the lane was re-dispatched four times
between 10:23 and 10:56 while `App.jsx` flipped between wiring it and not.
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "env_generator" / "llm_generator"))

from multi_agent.runtime.heal_pipeline import reconcile_integration_frontend_pages  # noqa: E402

REAL = ("import { getMessageConversations } from '../services/api';\\n"
        "export default function MessagesPage() {\\n"
        "  return <button onClick={() => getMessageConversations()}>Load</button>;\\n}\\n")


def _repo(tmp, app_imports_page):
    repo = Path(tmp)
    pages = repo / "app" / "frontend" / "src" / "pages"
    pages.mkdir(parents=True)
    app = "import FeedPage from './pages/FeedPage';\\n"
    if app_imports_page:
        app += "import MessagesPage from './pages/MessagesPage';\\n"
    (repo / "app" / "frontend" / "src" / "App.jsx").write_text(app, encoding="utf-8")
    wt = repo / "worktrees" / "frontend" / "app" / "frontend" / "src" / "pages"
    wt.mkdir(parents=True)
    (wt / "MessagesPage.jsx").write_text(REAL, encoding="utf-8")
    return repo, pages / "MessagesPage.jsx"


def test_r125_a_page_deleted_from_integration_stays_deleted():
    with tempfile.TemporaryDirectory() as tmp:
        repo, integ = _repo(tmp, app_imports_page=False)
        out = reconcile_integration_frontend_pages(repo)
        assert not integ.exists(), "the deleted page was written back"
        assert out == {}


def test_a_wired_page_whose_component_has_not_merged_is_still_restored():
    """#566b's own case (netflix r113): App.jsx imports the page, integration lacks it."""
    with tempfile.TemporaryDirectory() as tmp:
        repo, integ = _repo(tmp, app_imports_page=True)
        out = reconcile_integration_frontend_pages(repo)
        assert integ.exists() and out.get("reconciled") == ["MessagesPage.jsx"]


def test_a_stub_in_integration_is_still_replaced():
    with tempfile.TemporaryDirectory() as tmp:
        repo, integ = _repo(tmp, app_imports_page=False)
        integ.write_text("export default function MessagesPage(){return <div>Coming soon</div>}",
                         encoding="utf-8")
        reconcile_integration_frontend_pages(repo)
        assert "getMessageConversations" in integ.read_text(encoding="utf-8")
