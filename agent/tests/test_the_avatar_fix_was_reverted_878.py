r"""#878: #874 is reverted — I audited a deferral, called its reason wrong, and was wrong myself.

#874 claimed a "third path" for the profile avatar: render a design-staged asset hook-free, as
`_brand_logo_url` does. It cited **"139 of 151 runs stage an avatar-ish asset."**

★ **That number was wrong, and re-deriving it independently is what caught it — the second probe
returned 0 of 151.** The first regex-scanned the *whole* design_system document for avatar-ish
filenames; the helper read `design["assets"]`. Different places:

    design["assets"]               170 entries, every one a backdrop/poster
                                   ("backdrops/movie_1003596.jpg") plus the brand wordmark
    screens[].components[].crop    "design/crops/account_menu__profile-menu-flyout.png"
    screens[].components[].assets  []

The avatar imagery exists **only as a `crop`** — a design-time reference cutout under
`design/crops/`, never staged into `public/assets/`, never served. So `_avatar_asset_url_874`
returned `""` on every corpus run (a writer with no reader), and pointing it at the crops would
have shipped a broken `<img>` instead of the square.

★ **So item 184's dichotomy was not false.** For the logo the third path is real, because the
wordmark genuinely is staged. For the avatar it is not. #874 audited a deferral, found its reason
"wrong", and was itself wrong — **by committing the same field-location error the audit had just
finished naming twice.** Knowing a failure mode by name is not the same as being immune to it.

The accent square stands and item 184's trade-off is unchanged.
"""
import inspect
import json
import pathlib
import re

import pytest

from env_generator.llm_generator.multi_agent.runtime import frontend_scaffold as fs


_GENERATED = pathlib.Path(__file__).resolve().parents[1] / "generated"


def test_the_helper_is_gone():
    """Dead code with a false rationale is what this session has been removing."""
    assert not hasattr(fs, "_avatar_asset_url_874")


def test_the_chip_renders_the_accent_square_again():
    out = fs._ref_nav_jsx([("Home", "/browse")], "#e50914", vertical=False,
                          design={"assets": [{"id": "x", "file": "/assets/x.png", "type": "png"}]})
    chip = out.split('aria-label="Profile"')[1][:240]
    assert "backgroundColor" in chip and "<img" not in chip


def test_the_menu_and_caret_survived_both_edits():
    """#653's disclosure and #859's drawn caret must be untouched by the round trip."""
    out = fs._ref_nav_jsx([("Home", "/browse")], "#e50914", vertical=False, design={})
    assert 'role="menu"' in out and "Sign out" in out
    assert 'd="M6 9l6 6 6-6"' in out


def test_the_correction_is_recorded_at_the_site():
    """A revert with no note invites the same fix again in three weeks."""
    src = inspect.getsource(fs)
    assert "#878: #874 IS REVERTED" in src
    assert "design/crops/" in src and "never served" in src or "not served" in src


@pytest.mark.skipif(not _GENERATED.is_dir(), reason="corpus not present")
def test_the_corpus_really_stages_no_avatar():
    """★ The measurement #874 got wrong, done in the place the code reads.

    `design["assets"]` is what `_brand_logo_url` and the reverted helper both consult. It carries
    backdrops, posters and the wordmark — and no avatar. Scanning the whole document instead finds
    `crop` paths and reads as 139 runs, which is the error this test exists to prevent."""
    runs = with_assets = with_avatar = with_wordmark = 0
    for d in sorted(_GENERATED.glob("netflix-web-r*")):
        for p in d.rglob("design_system*.json"):
            try:
                ds = json.loads(p.read_text())
            except Exception:
                break
            runs += 1
            assets = [a for a in (ds.get("assets") or []) if isinstance(a, dict)]
            if assets:
                with_assets += 1
            hay = " ".join(f"{a.get('id','')} {a.get('file','')}" for a in assets).lower()
            if re.search(r"avatar|profile", hay):
                with_avatar += 1
            if "wordmark" in hay:
                with_wordmark += 1
            break
    if runs == 0:
        pytest.skip("the run corpus this analysis reads is not in this checkout — "
                    "`generated/` exists but holds none of the matching runs, so the "
                    "population assertion below would fail on absence, not on a defect")
    assert runs >= 100, runs
    assert with_assets >= 100, f"non-vacuity: only {with_assets} runs have a top-level assets list"
    assert with_wordmark >= 100, f"the logo's third path must still be real: {with_wordmark}"
    assert with_avatar == 0, f"an avatar IS staged now ({with_avatar}) — #874 may be revivable"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
