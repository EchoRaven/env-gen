"""A dangling PAGE import wired at a known route must project a REAL data page
(light-list + nav, matched to the route's contract endpoint), not a dead heading.

outlook run #8: the lane routed App.jsx /inbox -> <OutlookInbox/> (not a registered
ui_page), so the good projection landed on the unrouted registered name (InboxPage)
while OutlookInbox fell to scaffold_missing_local_pages and got a 7-line <h2> stub.
Match by ROUTE (component names differ) so the ROUTED page is the real one.
LOCAL-ONLY (agent/tests/ gitignored)."""
import sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.frontend_scaffold import scaffold_missing_local_pages  # noqa: E402

_APP = '''
import OutlookInbox from "./pages/OutlookInbox";
import OutlookCalendar from "./pages/OutlookCalendar";
import LoginPage from "./pages/LoginPage";
<Route path="/login" element={<LoginPage/>} />
<Route path="/inbox" element={<OutlookInbox/>} />
<Route path="/calendar" element={<OutlookCalendar/>} />
'''
_UIP = [{"route": "/inbox", "component": "InboxPage", "apis_used": ["GET /api/messages"]},
        {"route": "/calendar", "component": "CalendarPage", "apis_used": ["GET /api/events"]}]


def _setup():
    d = Path(tempfile.mkdtemp())
    (d / "src" / "pages").mkdir(parents=True)
    (d / "src" / "App.jsx").write_text(_APP)
    (d / "src" / "pages" / "LoginPage.jsx").write_text("export default function LoginPage(){return null}")
    return d


def test_routed_missing_page_projects_real_navigable_list():
    d = _setup()
    scaffold_missing_local_pages(d, ui_pages=_UIP)
    inbox = (d / "src" / "pages" / "OutlookInbox.jsx").read_text()
    assert "divide-y" in inbox                  # real light-list, not a dead <h2>
    assert "/api/messages" in inbox             # matched to the route's contract endpoint by ROUTE
    assert "<nav" in inbox and 'href="/calendar"' in inbox  # shared nav -> navigable


def test_without_registry_falls_back_to_stub_safely():
    # backward-compat: no ui_pages -> minimal stub (build-integrity), never crashes
    d = _setup()
    out = scaffold_missing_local_pages(d)  # ui_pages=None
    assert any("OutlookInbox" in p for p in out["scaffolded"])
    assert (d / "src" / "pages" / "OutlookInbox.jsx").exists()


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
