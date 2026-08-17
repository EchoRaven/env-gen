r"""#909: the contract describes a page that was not shipped, and nothing says so.

r153's registry records `browse_home_page` as built from
``["NetflixHeader","HeroBillboard","PosterRail","PosterCard","TitleDetailModal"]``. The delivered
`BrowseHomePage.jsx` imports React and react-router and renders **none of them** — it is the #221
projector's generic inline markup. `player_page` declares `VideoSurface`, `PlayerControls`,
`PlayerTitleOverlay`, `PlayerBackButton`; all four are orphaned; it scored **0.35** on the visual
gate, the lowest non-advisory screen in the run.

Measured across the corpus:

    components authored across 131 runs        1761
    ★ never reachable from ANY page            1239   70%
    declared component references in ui_pages  1431
    ★ reachable from the page the record names  479   33%
    ★ pages rendering ZERO of their own          246   45%

r153: 28 of 34 components orphaned, 11 of 12 pages render none of what they declare. The one
compliant page — `profiles_page`, 5 of 5 — is also the only page no framework writer overwrote.

★ The existing rollup asks the *other* question. `sync_ui_page_statuses` already loops over
`page["components"]` and checks each is **implemented**; it never asks whether the page **uses**
it. So a lane can build a component library, a framework page writer can replace the page with
markup that ignores it, and every check stays green while 70% of the UI work is dead code.

★ Reported, never enforced, and deliberately kept out of `ok`. Feeding it into `missing` would flip
the page to `defined` on the next tick and churn the lane over a description mismatch (#891's rule:
the run is not wrong here, the record is). Re-projecting from the lane's components is a separate
decision with its own risk; this only ends the silence.
"""
import inspect
import re
import tempfile
from pathlib import Path

import pytest

from env_generator.llm_generator.multi_agent.runtime import frontend_audit as fa


def _tree(pages: dict, components: dict) -> Path:
    root = Path(tempfile.mkdtemp())
    src = root / "app" / "frontend" / "src"
    (src / "pages").mkdir(parents=True)
    (src / "components").mkdir(parents=True)
    for name, body in pages.items():
        (src / "pages" / f"{name}.jsx").write_text(body, encoding="utf-8")
    for name, body in components.items():
        (src / "components" / f"{name}.jsx").write_text(body, encoding="utf-8")
    return root


def _cache(root: Path) -> dict:
    src = root / "app" / "frontend" / "src"
    return {str(f): f.read_text(encoding="utf-8")
            for f in list(src.rglob("*.jsx")) + list(src.rglob("*.js"))}


# --------------------------------------------------------------------------- the helper

def test_direct_children_are_found():
    root = _tree({"HomePage": "export default () => <div><PosterRail/></div>"},
                 {"PosterRail": "export default () => <div/>"})
    used = fa._rendered_components_909(root, {"path": "app/frontend/src/pages/HomePage.jsx"},
                                       _cache(root))
    assert used == {"PosterRail"}


def test_the_walk_is_transitive():
    """★ A page that renders `<PosterRail/>` uses `PosterCard` too. A direct-tag comparison would
    report drift that is not there — the false-positive this helper exists to avoid."""
    root = _tree({"HomePage": "export default () => <PosterRail/>"},
                 {"PosterRail": "export default () => <PosterCard/>",
                  "PosterCard": "export default () => <img/>"})
    used = fa._rendered_components_909(root, {"path": "app/frontend/src/pages/HomePage.jsx"},
                                       _cache(root))
    assert used == {"PosterRail", "PosterCard"}


def test_a_cycle_terminates():
    root = _tree({"HomePage": "export default () => <A/>"},
                 {"A": "export default () => <B/>", "B": "export default () => <A/>"})
    assert fa._rendered_components_909(
        root, {"path": "app/frontend/src/pages/HomePage.jsx"}, _cache(root)) == {"A", "B"}


def test_an_unknown_page_returns_empty_rather_than_guessing():
    root = _tree({"HomePage": "export default () => <A/>"}, {"A": "export default () => <i/>"})
    assert fa._rendered_components_909(
        root, {"path": "app/frontend/src/pages/NotThere.jsx"}, _cache(root)) == set()


def test_it_never_raises():
    """★ It runs inside the loop that maintains every ui_page's status. An observability call that
    throws there takes the status sync down with it — #827's shape, which wedged r152."""
    for bad in ({}, {"path": None}, {"path": 123}, None):
        try:
            assert fa._rendered_components_909(Path("/nonexistent"), bad or {}, None) == set()
        except Exception as exc:                                   # pragma: no cover
            pytest.fail(f"raised on {bad!r}: {exc}")


def test_it_reads_only_the_cache():
    """The cache is already populated by the caller; re-walking disk here would double the IO of
    an audit that runs every delivery tick."""
    root = _tree({"HomePage": "export default () => <A/>"}, {"A": "export default () => <i/>"})
    assert fa._rendered_components_909(
        root, {"path": "app/frontend/src/pages/HomePage.jsx"}, {}) == set()


# --------------------------------------------------------------------------- the report

def _block():
    src = inspect.getsource(fa.sync_ui_page_statuses)
    start = src.index("_decl_909")
    return src[start:src.index("if ok and status", start)]


def test_the_report_is_findable():
    b = _block()
    assert "component_drift" in b and "_rendered_components_909(" in b


def test_it_reports_only_when_the_page_renders_NONE_of_them():
    """A page using 3 of its 5 declared components is a partial refactor, not a page that was
    never shipped. Only the total miss is unambiguous enough to report without noise."""
    b = _block()
    assert "len(_orphaned) == len(_decl_909)" in b


def test_the_report_does_not_touch_ok_or_the_page_status():
    """★ The churn guard, and the reason this is a report. Assigning to `ok` here would flip every
    drifted page to `defined` on the next tick — 45% of pages, every tick."""
    b = _block()
    assert not re.search(r"^\s*ok\s*=", b, re.M), b
    assert "update_ui_page" not in b
    assert "missing" not in b


def test_the_report_cannot_break_the_sync():
    b = _block()
    assert "except Exception:" in b


def test_the_existing_implemented_rollup_still_runs():
    """Non-regression: #909 adds a question, it does not replace the one already asked."""
    src = inspect.getsource(fa.sync_ui_page_statuses)
    assert "not implemented yet" in src
    assert src.index("not implemented yet") < src.index("_decl_909")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
