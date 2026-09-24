"""#1202hc — both path conventions exist, and #1202fn had to pick one.

`scan_pages_without_files` resolves a ui_page's declared `path` against a single base.
#1202fn chose the OUTPUT ROOT, which is right for most of the corpus — but not all of it.
Measured over every registered page on this machine:

    resolve under the output root only : 1757
    resolve under the app tree only    :  101
    resolve under both                 :    8
    resolve under neither              :   80   <- genuinely missing

r102 is entirely in the 101: every page is registered as `frontend/src/pages/X.jsx` and every
file sits at `app/frontend/src/pages/X.jsx`. All eleven read as missing, and the framework
told the frontend lane to MOVE files that were already correct — a false blocker that induces
harmful work.

Accepting either base is not a guess: both conventions are present in the data, and a page is
only reported when it resolves under NEITHER, which leaves the 80 real cases untouched.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.coverage_audit import (  # noqa: E402
    _page_file_exists_1202hc, scan_pages_without_files)


class _RH:
    """Shaped like the real consumer: `hub_registry.registryhub.list_ui_pages()`."""
    def __init__(self, pages):
        self.registryhub = self
        self._p = pages

    def list_ui_pages(self):
        return self._p


def _tree(tmp_path, rel):
    f = tmp_path / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("export default function P(){return null}\n", encoding="utf-8")
    return f


def test_a_path_under_the_app_tree_counts(tmp_path):
    _tree(tmp_path, "app/frontend/src/pages/ExploreGridPage.jsx")
    assert _page_file_exists_1202hc(tmp_path, "frontend/src/pages/ExploreGridPage.jsx") is True


def test_a_path_under_the_output_root_still_counts(tmp_path):
    """#1202fn's majority case — 1757 of the corpus — must not regress."""
    _tree(tmp_path, "frontend/src/pages/ExploreGridPage.jsx")
    assert _page_file_exists_1202hc(tmp_path, "frontend/src/pages/ExploreGridPage.jsx") is True


def test_a_genuinely_absent_file_is_still_reported(tmp_path):
    assert _page_file_exists_1202hc(tmp_path, "frontend/src/pages/Nope.jsx") is False


def test_the_scan_uses_it(tmp_path):
    _tree(tmp_path, "app/frontend/src/pages/ExploreGridPage.jsx")
    hub = _RH({"explore_grid_page": {"path": "frontend/src/pages/ExploreGridPage.jsx"},
                  "ghost_page": {"path": "frontend/src/pages/Ghost.jsx"}})
    out = scan_pages_without_files(hub, tmp_path)
    names = {d.get("page") or d.get("name") or str(d) for d in out}
    assert not any("explore" in str(n) for n in names), (
        "a page whose file is under the app tree is still reported missing: %s" % out)
    assert any("ghost" in str(n) for n in names), (
        "the genuinely missing page stopped being reported: %s" % out)


def test_hostile_inputs_never_raise(tmp_path):
    for rel in (None, "", 3, "../../etc/passwd"):
        assert isinstance(_page_file_exists_1202hc(tmp_path, rel), bool)
