r"""#918: the API exists, the component exists, the call exists — and this page cannot make it.

r153 registers `title_detail` with five APIs including `GET /api/titles/{id}/episodes`. The endpoint
is implemented, `services/api.js` calls it, `EpisodeList` renders it, and #912 finds the call in
src. Every existing check passes. The page the record points at is the #910 projection: a 166-line
file importing nothing but React, so a user on that page can reach **none of the five**.

That is the category this session kept running into from different sides — #908 (a leak the gates do
not look for), #909 (components built and orphaned), #913 (a feature shipped unreachable). The gates
measure things that stay true while the app is not what was asked for. #918 adds the one axis that
names it directly: *can a user on this page do the thing the contract says this page does?*

    corpus: 1534 pages declare an API
    ★ 735 of 2472 declared references (30%) unreachable from the page's own closure
    ★ 696 pages (45%) are ISLANDS — closure is the file itself, importing nothing
      (the same 45% #909 measures from the component side; one population, two readings)

Reported only, total-miss only, out of `ok` — a page reaching 2 of 3 is a partial refactor, and
folding this into `ok` would flip half the pages to `defined` every tick.

★ Two instrument failures were needed to get here, both recorded in `_page_closure_918`: following
only JSX tags (so `services/api.js`, which pages IMPORT, was invisible and every page read as
unreachable), then comparing a relative cache key against a resolved import path (so no import ever
matched and the noise still looked like signal). `profiles` — which does call `/api/profiles`
through `api.js` — is the fixture that catches both.
"""
import tempfile
from pathlib import Path

import pytest

from env_generator.llm_generator.multi_agent.runtime import frontend_audit as fa


def _tree(**files):
    src = Path(tempfile.mkdtemp()) / "src"
    for rel, body in files.items():
        p = src / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    return src, {str(f): f.read_text(encoding="utf-8") for f in src.rglob("*") if f.is_file()}


_PAGE = {"name": "p", "component": "PPage", "path": "app/frontend/src/pages/PPage.jsx"}


def test_an_api_reached_through_an_imported_service_counts():
    """★ The `profiles` shape, and the case the first version got wrong: the call lives in a module
    the page IMPORTS, not one it renders."""
    _src, cache = _tree(**{
        "pages/PPage.jsx": "import { list } from '../services/api.js';\nexport default () => <div/>;",
        "services/api.js": "export const list = () => fetch('/api/profiles');",
    })
    closure = fa._page_closure_918(_PAGE, cache)
    assert len(closure) == 2
    assert any("/api/profiles" in v for v in closure.values())


def test_an_api_reached_through_a_rendered_component_counts():
    _src, cache = _tree(**{
        "pages/PPage.jsx": "export default () => <Rail/>;",
        "components/Rail.jsx": "export default () => fetch('/api/titles');",
    })
    assert any("/api/titles" in v for v in fa._page_closure_918(_PAGE, cache).values())


def test_the_closure_is_transitive():
    _src, cache = _tree(**{
        "pages/PPage.jsx": "import A from '../components/A.jsx';\nexport default () => <A/>;",
        "components/A.jsx": "import B from './B.jsx';\nexport default () => <B/>;",
        "components/B.jsx": "export default () => fetch('/api/deep');",
    })
    assert any("/api/deep" in v for v in fa._page_closure_918(_PAGE, cache).values())


def test_an_island_page_reaches_nothing():
    """r153's projection: imports React, renders no component of its own."""
    _src, cache = _tree(**{
        "pages/PPage.jsx": "import { useState } from 'react';\nexport default () => <div/>;",
        "services/api.js": "export const list = () => fetch('/api/profiles');",
    })
    closure = fa._page_closure_918(_PAGE, cache)
    assert len(closure) == 1
    assert not any("/api/profiles" in v for v in closure.values())


def test_a_cycle_terminates():
    _src, cache = _tree(**{
        "pages/PPage.jsx": "import A from '../components/A.jsx';\nexport default () => <A/>;",
        "components/A.jsx": "import P from '../pages/PPage.jsx';\nexport default () => <P/>;",
    })
    assert len(fa._page_closure_918(_PAGE, cache)) == 2


def test_an_unknown_page_returns_empty():
    _src, cache = _tree(**{"pages/Other.jsx": "export default () => <div/>;"})
    assert fa._page_closure_918(_PAGE, cache) == {}


def test_it_never_raises():
    """It runs inside the loop that maintains every ui_page's status — #827's shape wedged r152
    from exactly there."""
    for bad in ({}, {"path": None}, {"path": 123}, {"component": None}):
        assert fa._page_closure_918(bad, None) == {}
    assert fa._page_closure_918({"path": "x/pages/A.jsx"}, {"nonsense": None}) == {}


def test_the_cache_key_shape_does_not_matter():
    """★ The second instrument failure, pinned: the cache is keyed on the caller's walk while an
    import resolves to an absolute path. Both must normalise, or no import ever matches and every
    page reads as an island."""
    src, cache = _tree(**{
        "pages/PPage.jsx": "import { list } from '../services/api.js';\nexport default () => <div/>;",
        "services/api.js": "export const list = () => fetch('/api/profiles');",
    })
    relative = {str(Path(k).relative_to(Path.cwd())) if str(k).startswith(str(Path.cwd()))
                else k: v for k, v in cache.items()}
    assert len(fa._page_closure_918(_PAGE, relative)) == 2


# --------------------------------------------------------------------------- the report

def _block():
    import inspect
    s = inspect.getsource(fa.sync_ui_page_statuses)
    return s[s.index("_apis_918"):s.index("_decl_909")]


def test_it_reports_only_a_total_miss():
    b = _block()
    assert "len(_unreachable) == len(_apis_918)" in b


def test_it_does_not_touch_ok_or_the_status():
    import re as _re
    b = _block()
    assert not _re.search(r"^\s*ok\s*=", b, _re.M), b
    assert "update_ui_page" not in b


def test_the_report_cannot_break_the_sync():
    assert "except Exception:" in _block()


def test_it_is_a_separate_channel_from_909():
    b = _block()
    assert 'out.setdefault("api_unreachable"' in b
    assert "component_drift" not in b

# --------------------------------------------------------------------------- DRIVEN (#920)

class _StubWorkHub:
    """The minimum `sync_ui_page_statuses` touches. Records status writes so a test can assert
    the report did NOT cause one."""

    def __init__(self, pages, components):
        self._pages, self._components = pages, components
        self.page_updates = []

    def get_ui_pages(self):
        return self._pages

    def get_ui_components(self):
        return self._components

    def update_ui_page(self, name, patch, **kw):
        self.page_updates.append((name, patch))

    def update_ui_component(self, *a, **kw):
        pass


def _sync(page_body: str, *, declares_components=("Rail",), declares_apis=("GET /api/things",),
          component_body="export default () => <div/>"):
    """Drive the REAL `sync_ui_page_statuses` over a real tree.

    ★ Added because the report these files exist for was checked only by reading its source: with
    the report disabled, 10 of #909's 11 tests still passed, and the one that failed was
    `assert 'len(_orphaned) == len(_decl_909)' in src`. The helper was well driven; the thing the
    ticket delivers was not."""
    import tempfile
    from pathlib import Path as _P
    from env_generator.llm_generator.multi_agent.runtime import frontend_audit as _fa

    root = _P(tempfile.mkdtemp())
    src = root / "app" / "frontend" / "src"
    (src / "pages").mkdir(parents=True)
    (src / "components").mkdir(parents=True)
    (src / "App.jsx").write_text(
        '<Routes><Route path="/x" element={<XPage />} /></Routes>', encoding="utf-8")
    (src / "pages" / "XPage.jsx").write_text(page_body, encoding="utf-8")
    for c in declares_components:
        (src / "components" / f"{c}.jsx").write_text(component_body, encoding="utf-8")
    wh = _StubWorkHub(
        {"x_page": {"name": "x_page", "route": "/x", "component": "XPage",
                    "path": "app/frontend/src/pages/XPage.jsx",
                    "components": list(declares_components),
                    "apis_used": list(declares_apis), "status": "implemented"}},
        {c: {"name": c, "path": f"app/frontend/src/components/{c}.jsx",
             "status": "implemented"} for c in declares_components})
    return _fa.sync_ui_page_statuses(root, wh, None), wh


_ISLAND = "import {useState} from 'react';\nexport default function XPage(){return <div onClick={()=>{}}>x</div>}"


def test_the_unreachable_api_is_actually_reported():
    """★ Driven end to end through `sync_ui_page_statuses`, not read out of its source."""
    out, _ = _sync(_ISLAND)
    assert out.get("api_unreachable") == {"x_page": ["/api/things"]}, out.get("api_unreachable")


def test_no_report_when_the_page_can_reach_it():
    out, _ = _sync("import { go } from '../components/Rail.jsx';\n"
                   "export default function XPage(){return <div onClick={()=>go()}>x</div>}",
                   component_body="export const go = () => fetch('/api/things');")
    assert not out.get("api_unreachable"), out.get("api_unreachable")


def test_the_two_reports_are_independent_channels():
    """A page can reach its API through a service while rendering none of its declared
    components — #909 fires, #918 must not."""
    out, _ = _sync("import { go } from '../services/api.js';\n"
                   "export default function XPage(){return <div onClick={()=>go()}>x</div>}")
    assert out.get("component_drift"), "the declared component is still unrendered"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
