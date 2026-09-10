"""#1202js: why `audit_asset_usage` tests globally while reporting per screen.

The mismatch looks like #1202fn's shape — one base feeding two consumers that need different
ones — and it is not. A React page composes SHARED components, so an asset rendered in
`TikTokChrome.jsx` is rendered on every screen that mounts the chrome, and a page-file-scoped
test would not see it.

What settles it is the error direction, not the accounting: `_screen_asset_fix_lines` MANDATES
rendering ("do NOT draw an approximation"), so a false "you never used this" would tell a lane
to render something it already renders. Under-reporting is the safe failure; over-mandating is
not.

Nothing changes here. The rationale is recorded at the site because the next reader — me, an
hour before writing this — read the per-screen claim over a global test as a defect and went
measuring. This test keeps that reading from costing the same hour twice.
"""
import sys
import pathlib

_AGENT = pathlib.Path(__file__).resolve().parents[1]
if str(_AGENT) not in sys.path:
    sys.path.insert(0, str(_AGENT))

import inspect                                                          # noqa: E402

from env_generator.llm_generator.multi_agent.runtime import frontend_audit as FA  # noqa: E402


def _rationale():
    return " ".join(inspect.getsource(FA.audit_asset_usage).split())


def test_a_shared_component_counts_for_every_screen_that_mounts_it(tmp_path):
    """The behaviour the rationale defends, asserted rather than described."""
    fe = tmp_path / "frontend"
    (fe / "src" / "components").mkdir(parents=True)
    (fe / "src" / "components" / "Chrome.jsx").write_text(
        "export const Chrome = () => <img src='/assets/icons/nav_rail.svg'/>;",
        encoding="utf-8")
    (fe / "src" / "pages").mkdir()
    (fe / "src" / "pages" / "ProfilePage.jsx").write_text(
        "import {Chrome} from '../components/Chrome';\nexport default () => <Chrome/>;",
        encoding="utf-8")
    ds = {"assets": [{"id": "a1", "file": "icons/nav_rail.svg"}],
          "screens": [{"name": "profile_own",
                       "components": [{"id": "left-rail", "assets": ["a1"]}]}]}
    out = FA.audit_asset_usage(fe, ds)
    assert out["unused_mapped"] == [], (
        "the page file never names the asset; the shared component does, and the screen "
        "renders it — reporting it would mandate a duplicate render")
    assert out["unused_by_screen"] == {}


def test_an_asset_no_file_mentions_is_still_reported(tmp_path):
    """Non-vacuity: the global test must still catch a genuinely unrendered asset."""
    fe = tmp_path / "frontend"
    (fe / "src").mkdir(parents=True)
    (fe / "src" / "ProfilePage.jsx").write_text("export default () => <div/>;",
                                                encoding="utf-8")
    ds = {"assets": [{"id": "a1", "file": "icons/nav_rail.svg"}],
          "screens": [{"name": "profile_own",
                       "components": [{"id": "left-rail", "assets": ["a1"]}]}]}
    out = FA.audit_asset_usage(fe, ds)
    assert out["unused_mapped"] == [{"component": "left-rail", "asset": "a1",
                                     "file": "icons/nav_rail.svg"}]
    assert list(out["unused_by_screen"]) == ["profile_own"]


def test_the_reason_is_recorded_where_the_global_test_is():
    """★ A per-screen claim over a global test reads as a defect until the reason is beside it."""
    src = _rationale()
    assert "#1202js" in src
    assert "SHARED components" in src, "the mechanism that makes the global test correct"
    assert "MANDATES rendering" in src, (
        "and the error-direction argument, which is what actually settles it")
    assert "81-96%" in src, "with the measurement that looked alarming, so nobody re-runs it"
