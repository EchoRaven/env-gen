"""#1202pj: the scaffolder keeps a lane page with real behaviour, not only one importing ../components/.

#914 deferred to a lane page only when it contained `'../components/'`. A self-contained page, a
page delegating to a sibling, and a re-export all read as unrefined and were replaced by the
structured-floor projection: 694 clobbers across 30 recent runs. Same run, same judge (r120):
friends_suggested_creators 0.48/0.70 on the lane page vs 0.08 on the projection; live_discover
0.43 vs 0.08. Drives the real `scaffold_pages_from_contract`.
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from env_generator.llm_generator.multi_agent.runtime import frontend_scaffold as fs  # noqa: E402

_DESIGN = {"screens": [
    {"name": "browse_home", "route": "/browse", "kind": "page",
     "components": [{"id": "row1-carousel", "role": "first content row of 5 title cards"},
                    {"id": "row2-carousel", "role": "second content row of 5 title cards"}]},
]}
_PAGE = {"name": "browse_home", "route": "/browse", "component": "BrowseHomePage",
         "apis_used": ["GET /api/titles"],
         "path": "app/frontend/src/pages/BrowseHomePage.jsx"}


def _scaffold(existing, monkeypatch):
    monkeypatch.setenv("ENVGEN_DEFER_TO_LANE_PAGE", "1")
    fe = Path(tempfile.mkdtemp()) / "app" / "frontend"
    (fe / "src" / "pages").mkdir(parents=True)
    (fe / "src" / "components").mkdir(parents=True)
    target = fe / "src" / "pages" / "BrowseHomePage.jsx"
    target.write_text(existing, encoding="utf-8")
    monkeypatch.setattr(fs, "_load_design_for_projection", lambda _fd: _DESIGN)
    fs.scaffold_pages_from_contract(fe, [_PAGE])
    return target.read_text(encoding="utf-8")


SELF_CONTAINED = """import { useEffect, useState } from 'react';
import { api } from '../services/api';

export default function BrowseHomePage() {
  const [rows, setRows] = useState([]);
  useEffect(() => { api.get('/api/titles').then((d) => setRows(d.items || [])); }, []);
  return (
    <main className="browse">
      {rows.map((t) => <article key={t.id}>{t.name}</article>)}
    </main>
  );
}
"""


def test_r126_a_self_contained_lane_page_is_kept(monkeypatch):
    assert _scaffold(SELF_CONTAINED, monkeypatch) == SELF_CONTAINED


def test_a_page_delegating_to_a_sibling_is_kept(monkeypatch):
    page = ("import FriendsPage from './FriendsPage.jsx';\n"
            "export default function BrowseHomePage() { return <FriendsPage tab=\"browse\" />; }\n")
    assert _scaffold(page, monkeypatch) == page


def test_a_re_export_is_kept(monkeypatch):
    page = "export { default } from './ExploreGridPage.jsx';\n"
    assert _scaffold(page, monkeypatch) == page


def test_a_behaviourless_lane_page_is_still_projected(monkeypatch):
    """#914's own counter-case: no components, no behaviour — the projector's actual purpose."""
    body = "\n".join(f"  {{/* lane {i} */}}" for i in range(300))
    page = f"export default function BrowseHomePage(){{ return (<div><div/>\n{body}\n</div>); }}"
    assert "lane 0" not in _scaffold(page, monkeypatch)
