r"""#905: the ui_flow gate exempted 644 REAL pages and swallowed 24 recorded failures.

#243 exempts a ui_page with a blank route from the required flow set, on the premise that such an
entry is *a component mis-registered as a page* and that **"a ui_flow record for a routeless entry
can NEVER be produced"** — requiring one would be an unwinnable gate.

Measured over the 153-run corpus, both halves of that premise are wrong for most of what it hits:

    ui_page records                                 2543
      carrying route=''                              826   32%, in 100% of runs
        exempted, path under /components/             26   #243's real class
        exempted, path under /pages/                 644   REAL pages, route never recorded
    ★ of those 644, a ui_flow record EXISTS for      403   63% — "can never exist" is false
    ★ ...and is FAILING, but the gate never saw it    24

r116 alone hid seven failing flows — landing, login, profiles, browse_home, shows, movies,
title_detail. The records exist because the browser walk visits **App.jsx's** real routes and keys
records by page NAME; the registry's empty `route` field never enters that path.

It matters more than it looks: `_extract_required_flows` falls back to *"every declared ui_page is
a flow to validate"*, and this filter runs **before** that fallback. In r153 it cut the required set
from 12 pages to 4.

★ The discriminator was in the record all along. `path` is overloaded — a route in the kickoff spec
shape, a SOURCE FILE in the registry shape — and `app/frontend/src/pages/X.jsx` never starts with
`/`, so every registry record reaching that branch was exempted outright. A file under `src/pages/`
is the framework's own page convention (the scaffolder writes there; `_project_page_component` tests
`"/pages/" in rel`).

Safe in both directions, which is why the fix is not a revert of #243: a newly-required flow with no
record reads MISSING, and `deliverability` already drops *"ui flow(s) missing"* on a functionally
validated app (#489/#240 also author the records from a real pre-gate walk); a FAILED record always
blocked — it just never reached the gate.
"""
import inspect

import pytest

from env_generator.llm_generator.multi_agent.runtime import flow_coverage as fc
from env_generator.llm_generator.multi_agent.runtime.flow_coverage import _is_navigable_page


def _page(**kw):
    base = {"name": "x", "route": "", "path": "app/frontend/src/pages/XPage.jsx"}
    base.update(kw)
    return base


def test_a_component_with_no_route_is_still_exempt():
    """★ #243 must keep working — this is the class it was written for (tiktok r33 M2)."""
    assert _is_navigable_page(
        _page(name="top_action_bar", path="app/frontend/src/components/TopActionBar.jsx")) is False


def test_a_real_page_with_no_route_is_required():
    """The defect: 644 of these, of which 403 already had a record and 24 were failing."""
    assert _is_navigable_page(_page(name="languages_page")) is True


def test_a_routed_page_is_unchanged():
    assert _is_navigable_page(_page(name="games_page", route="/games")) is True


def test_an_entry_with_no_route_and_no_path_is_unchanged():
    """Non-regression on #243's documented conservative branch: we cannot prove it is a
    component, so it stays required."""
    assert _is_navigable_page({"name": "legacy_shape"}) is True


def test_a_non_mapping_is_unchanged():
    assert _is_navigable_page("not a page") is True


def test_a_route_shaped_path_still_wins():
    """`path` doubles as the ROUTE in the kickoff spec shape — a `/`-rooted value must keep
    meaning navigable, whatever the file test would say."""
    p = {"name": "explore", "path": "/explore"}
    assert _is_navigable_page(p) is True


def test_a_windows_style_page_path_is_recognised():
    assert _is_navigable_page(_page(path=r"app\frontend\src\pages\XPage.jsx")) is True


def test_the_filter_runs_before_the_all_pages_fallback():
    """★ The severity claim, pinned to the code. This exemption would be minor if the required set
    came only from `critical:true` pages — it is major because the fallback requires EVERY declared
    page and the filter is applied first. If that order ever changes, this ticket's numbers stop
    meaning what they say."""
    src = inspect.getsource(fc._extract_required_flows)
    assert "_is_navigable_page(p)" in src
    assert src.index("_is_navigable_page(p)") < src.index("CONTRACT-DERIVED FALLBACK")


def test_the_required_set_actually_grows_for_a_routeless_page_set():
    """End to end through the real extractor, not just the predicate."""
    spec = {"critical_flows": [], "pages": [
        _page(name="languages_page", path="app/frontend/src/pages/LanguagesPage.jsx"),
        _page(name="games_page", route="/games", path="app/frontend/src/pages/GamesPage.jsx"),
        _page(name="top_action_bar", path="app/frontend/src/components/TopActionBar.jsx"),
    ]}
    required, source = fc._extract_required_flows(spec)
    assert "languages_page" in required, required
    assert "games_page" in required, required
    assert "top_action_bar" not in required, required


def test_the_frontend_audit_shares_the_predicate_rather_than_copying_it():
    """★ #906. The same test was open-coded a third time in `frontend_audit`, carrying the claim
    *"A genuinely-declared page always carries a '/'-anchored route"* — which the 644 refute. Two
    copies of one concept drift; this asserts there is one.

    Measured before the change: including those pages in the audit yields ONE hard blocker across
    153 runs, and it is true (r112, `NotFoundPage` genuinely absent). No false positives."""
    from env_generator.llm_generator.multi_agent.runtime import frontend_audit as fa
    assert fa._is_navigable_page is _is_navigable_page
    src = inspect.getsource(fa.ui_page_delivery_blockers)
    assert src.count("_is_navigable_page(") == 2, "both the audit loop and the map check"
    assert 'str(page.get("route") or "").strip().startswith("/")' not in src


def test_the_shared_import_is_module_level():
    """★ A function-local import here would raise inside the `except Exception: pass` that wraps
    the ui_page audit and silently disable every blocker it produces — #827's exact shape, which
    cost r152. Module level fails loudly at import instead.

    ★ Asserted through the AST. The first version compared source offsets against `"def "`, which
    the module DOCSTRING contains — anchoring on a bare substring that prose can quote, for the
    nth time this session."""
    import ast
    from env_generator.llm_generator.multi_agent.runtime import frontend_audit as fa
    tree = ast.parse(inspect.getsource(fa))
    top = [n for n in tree.body if isinstance(n, ast.ImportFrom) and n.module == "flow_coverage"]
    assert top, "the import must be a MODULE-LEVEL statement, not nested in a function"
    assert any(a.name == "_is_navigable_page" for n in top for a in n.names)


def test_missing_is_suppressed_on_a_validated_app():
    """★ The safety argument, asserted rather than claimed. Widening the required set is only
    responsible because a MISSING record is already waived on a functionally-validated app — if
    that waiver is ever removed, this widening becomes a source of false blocks and this test is
    where that gets noticed."""
    from env_generator.llm_generator.multi_agent.runtime import deliverability as dv
    src = inspect.getsource(dv)
    assert 'if ui_validated:' in src
    assert '"ui flow(s) missing" not in b.lower()' in src


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
