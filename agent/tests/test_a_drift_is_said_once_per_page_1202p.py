r"""#1202p: a declaration drift is stated once per page per distinct finding.

`reconcile_ui_page_apis_1199` runs on every scaffold pass, and a drift does not change until
someone acts on it, so the same finding was restated every pass. r30's first hour: 28 drift
lines = 4 pages x 8 repetitions.

That is the noise #1202n had just removed from the heal declines, reintroduced two commits
later by me. Same rule here: a finding that CHANGES is said again, the same finding on a
different page is said, and standing still is quiet.

The reported LIST is untouched — `out["reconciled"]` still carries every drifting page on
every call, because callers read it to decide what to do. Only the log line is deduped.
"""

import logging
import sys
import tempfile
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

from multi_agent.runtime import frontend_scaffold as fs  # noqa: E402

_API = """
export async function getTitles() { return (await request('/api/titles')).items; }
export async function getMyList() { return (await request('/api/my-list')).items; }
"""


def _tree(call="getMyList"):
    fe = Path(tempfile.mkdtemp()) / "app" / "frontend"
    (fe / "src" / "pages").mkdir(parents=True)
    (fe / "src" / "services").mkdir(parents=True)
    (fe / "src" / "services" / "api.js").write_text(_API, encoding="utf-8")
    (fe / "src" / "pages" / "MyListPage.jsx").write_text(
        "import { %s } from '../services/api';\n"
        "export default function MyListPage(){ %s(); return null; }\n" % (call, call),
        encoding="utf-8")
    return fe


def _page():
    return {"name": "my_list_page", "route": "/browse/my-list",
            "path": "app/frontend/src/pages/MyListPage.jsx",
            "apis_used": ["GET /api/titles"]}


class _Hub:
    def register_ui_page(self, **kw):
        raise AssertionError("#1199 reports; it must not write")


def test_the_same_drift_is_logged_once(caplog):
    fs._DRIFT_SAID_1202P.clear()
    fe = _tree()
    with caplog.at_level(logging.WARNING, logger=fs.__name__):
        for _ in range(8):
            rep = fs.reconcile_ui_page_apis_1199(fe, [_page()], _Hub())
    assert caplog.text.count("#1199 DECLARATION DRIFT") == 1
    # the LIST is not deduped — callers read it every pass
    assert [r["page"] for r in rep["reconciled"]] == ["my_list_page"]


def test_a_changed_drift_is_logged_again(caplog):
    fs._DRIFT_SAID_1202P.clear()
    fe = _tree("getMyList")
    with caplog.at_level(logging.WARNING, logger=fs.__name__):
        fs.reconcile_ui_page_apis_1199(fe, [_page()], _Hub())
        # the page now reaches a different endpoint: that is news
        (fe / "src" / "pages" / "MyListPage.jsx").write_text(
            "export default function MyListPage(){ fetch('/api/genres'); return null; }\n",
            encoding="utf-8")
        fs.reconcile_ui_page_apis_1199(fe, [_page()], _Hub())
    assert caplog.text.count("#1199 DECLARATION DRIFT") == 2


def test_a_different_page_is_still_reported(caplog):
    fs._DRIFT_SAID_1202P.clear()
    fe = _tree()
    other = dict(_page(), name="other_page")
    with caplog.at_level(logging.WARNING, logger=fs.__name__):
        fs.reconcile_ui_page_apis_1199(fe, [_page(), other], _Hub())
    assert caplog.text.count("#1199 DECLARATION DRIFT") == 2


def test_two_frontends_do_not_silence_each_other(caplog):
    """The memo is keyed per frontend dir — a second run must not inherit the first's silence."""
    fs._DRIFT_SAID_1202P.clear()
    a, b = _tree(), _tree()
    with caplog.at_level(logging.WARNING, logger=fs.__name__):
        fs.reconcile_ui_page_apis_1199(a, [_page()], _Hub())
        fs.reconcile_ui_page_apis_1199(b, [_page()], _Hub())
    assert caplog.text.count("#1199 DECLARATION DRIFT") == 2
