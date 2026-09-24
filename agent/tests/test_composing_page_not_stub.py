"""FIX #126 — a page that COMPOSES real child components is not a placeholder stub
(instagram-core-di run-44 M1 STUCK, 2026-07-10 01:19, live-diagnosed).

run-44 wedged M1 on deliverability_ui_page_unwired for 7 cycles. Live audit: the
only flagged page was home_feed -> HomeFeedPage 'placeholder stub — renders no
real UI'. But HomeFeedPage.jsx is NOT a stub: it composes 5 real child components
(SideNavigation / MainFeed / RightSidebar / MessagesDock / TenantPicker) that carry
all the fetching + handlers — the user's own model ("pages compose COMPONENTS").
The _declared_but_inert flag fired because the check looked ONLY at the page file:
apis_used declared + no api call + no handler token IN THE PAGE. But when the page
renders custom child components imported from ../components/, the behavior is
delegated to them (exactly as the api-reference check already tolerates delegation
to a service module). Suppress the inert-stub flag for a page that composes >=1
real child component. ENV-AGNOSTIC + LOCAL-ONLY (agent/tests/ gitignored).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.frontend_audit import audit_ui_page  # noqa: E402


_HOMEFEED = '''\
import React from 'react';
import SideNavigation from '../components/SideNavigation';
import MainFeed from '../components/MainFeed';
import RightSidebar from '../components/RightSidebar';

function HomeFeedPage() {
  return (
    <div className="min-h-screen flex">
      <SideNavigation />
      <MainFeed />
      <RightSidebar />
    </div>
  );
}
export default HomeFeedPage;
'''

# a component that DOES the fetching the page delegated
_MAINFEED = '''\
import React, { useEffect, useState } from 'react';
import api from '../services/api';
export default function MainFeed() {
  const [posts, setPosts] = useState([]);
  useEffect(() => { api.get('/api/feed').then(r => setPosts(r.items)); }, []);
  return <div>{posts.map(p => <article key={p.id}>{p.caption}</article>)}</div>;
}
'''

_REAL_STUB = '''\
import React from 'react';
function ExplorePage() {
  return <div>This section is being set up. Coming soon.</div>;
}
export default ExplorePage;
'''

_DECLARED_INERT_NO_CHILDREN = '''\
import React from 'react';
function ProfilePage() {
  return <div className="p-4"><h1>Profile</h1><p>static text only</p></div>;
}
export default ProfilePage;
'''


def _mk(tmp_path, files):
    src = tmp_path / "src"
    (src / "pages").mkdir(parents=True)
    (src / "components").mkdir(parents=True)
    (src / "services").mkdir(parents=True)
    (src / "services" / "api.js").write_text("export default { get: () => {} };", encoding="utf-8")
    for rel, txt in files.items():
        (src / rel).write_text(txt, encoding="utf-8")
    return src


def test_composing_page_with_declared_apis_is_not_stub(tmp_path):
    src = _mk(tmp_path, {"pages/HomeFeedPage.jsx": _HOMEFEED,
                         "components/SideNavigation.jsx": "export default () => <nav/>;",
                         "components/MainFeed.jsx": _MAINFEED,
                         "components/RightSidebar.jsx": "export default () => <aside/>;",
                         "App.jsx": ("import HomeFeedPage from './pages/HomeFeedPage';\n"
                                     "export default () => <Route path=\"/\" "
                                     "element={<HomeFeedPage />} />;\n")})
    ok, missing = audit_ui_page(
        src, {"component": "HomeFeedPage", "route": "/",
              "apis_used": ["GET /api/feed"]})
    # the run-44 false block was the STUB flag specifically; assert it is gone.
    assert not any("placeholder stub" in m for m in missing), missing
    assert ok, missing


def test_real_placeholder_phrase_still_flagged(tmp_path):
    src = _mk(tmp_path, {"pages/ExplorePage.jsx": _REAL_STUB})
    ok, missing = audit_ui_page(
        src, {"component": "ExplorePage", "route": "/explore", "apis_used": []})
    assert not ok and any("placeholder stub" in m for m in missing)


def test_declared_apis_no_children_no_calls_still_flagged(tmp_path):
    # a page that declares apis but neither calls them NOR composes children is
    # still inert — the delegation escape must not become a blanket bypass.
    src = _mk(tmp_path, {"pages/ProfilePage.jsx": _DECLARED_INERT_NO_CHILDREN})
    ok, missing = audit_ui_page(
        src, {"component": "ProfilePage", "route": "/profile",
              "apis_used": ["GET /api/users/me"]})
    assert not ok and any("placeholder stub" in m for m in missing)
