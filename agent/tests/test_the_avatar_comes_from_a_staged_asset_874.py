r"""#874: item 184's deferral rested on a false dichotomy.

Item 184 measured the profile-avatar class (597 deviation entries / 115 runs) and deferred it:

> fetch a profile → the hook-free TopNav becomes stateful; or use the reference image pool → it
> paints *a* picture rather than *the user's*.

Both premises are true. **The dichotomy is not** — the framework already has a third path and
uses it for the logo: `_brand_logo_url` renders a **design-staged asset**, hook-free, out of
`design["assets"]`.

★ Measured: **139 of 151 corpus runs stage an avatar-ish asset** —
`account_menu__profile-switcher.png` (44), `account_menu__profile-menu-trigger.png` (36), and
others. They are crops of the reference's own profile tile, so this is neither a random picture
nor a state fetch: it is what the reference shows, which is what the visual gate scores.

Same selection shape as `_brand_logo_url`, same failure mode — `""` when nothing is staged, so
the accent square survives untouched on the 12 runs without one.

★ **Still a placeholder semantically.** A multi-profile app's real avatar comes from the signed-in
profile row and this cannot know it; item 184's trade-off is unchanged and unclaimed. What changed
is that the cheap option was never actually "a random picture".

### the probe error behind the delay

The first search for staged avatars looked at the **filesystem** (`app/frontend/public/assets`)
and reported zero across 151 runs — the dirs exist and are empty. `_brand_logo_url` reads
`design["assets"]`, a data structure. **Eighth field-location error this session**, and the same
rule caught it: 151 runs with a directory and zero files is a claim about the probe.
"""
import inspect

import pytest

from env_generator.llm_generator.multi_agent.runtime import frontend_scaffold as fs


def _a(*ids):
    return {"assets": [{"id": i, "file": f"/assets/{i}.png", "type": "png"} for i in ids]}


def test_the_helper_exists():
    """Non-vacuity."""
    assert fs._avatar_asset_url_874(_a("account_menu__profile-switcher"))


@pytest.mark.parametrize("aid", ["account_menu__profile-switcher",
                                 "account_menu__profile-menu-trigger",
                                 "nav__user-avatar", "profile"])
def test_a_staged_avatar_is_found(aid):
    """The four shapes the corpus actually stages."""
    assert fs._avatar_asset_url_874(_a(aid)) == f"/assets/{aid}.png"


def test_an_unrelated_asset_is_not_mistaken_for_one():
    """★ It must not grab the wordmark or a poster. A wrong image is worse than the square."""
    assert fs._avatar_asset_url_874(_a("brand__wordmark", "hero__poster", "search")) == ""


def test_no_assets_yields_the_empty_string():
    for d in (None, {}, {"assets": []}, {"assets": [{"nope": 1}]}):
        assert fs._avatar_asset_url_874(d) == ""


def test_an_explicit_avatar_beats_a_generic_profile_crop():
    """Ordered preference, mirroring `_brand_logo_url`'s wordmark-over-icon rule."""
    got = fs._avatar_asset_url_874(_a("profile", "nav__user-avatar"))
    assert got == "/assets/nav__user-avatar.png"


def test_the_nav_renders_it():
    out = fs._ref_nav_jsx([("Home", "/browse")], "#e50914", vertical=False,
                          design=_a("account_menu__profile-switcher"))
    assert 'src="/assets/account_menu__profile-switcher.png"' in out
    assert "object-cover" in out


def test_the_accent_square_survives_when_nothing_is_staged():
    """★ Additive: the 12 corpus runs with no avatar asset must be byte-identical."""
    out = fs._ref_nav_jsx([("Home", "/browse")], "#e50914", vertical=False, design={})
    chip = out.split('aria-label="Profile"')[1][:300]
    assert "backgroundColor" in chip and "<img" not in chip


def test_the_chip_keeps_its_menu_and_caret():
    """The avatar swap must not disturb #653's disclosure or #859's drawn caret."""
    out = fs._ref_nav_jsx([("Home", "/browse")], "#e50914", vertical=False,
                          design=_a("nav__user-avatar"))
    assert 'role="menu"' in out and "Sign out" in out
    assert 'd="M6 9l6 6 6-6"' in out


def test_the_logo_path_it_mirrors_still_exists():
    """Non-vacuity for the premise: the third path is only real while `_brand_logo_url` takes it."""
    src = inspect.getsource(fs._brand_logo_url)
    assert 'get("assets")' in src and "staged_path" in src


def test_the_seam_that_broke_it_compiles():
    """★ Swapping one implicitly-concatenated literal for a parenthesised conditional needs an
    explicit `+`. Third time this seam has bitten in one session (#858, #874); `compile()` is what
    catches it (#814)."""
    import pathlib
    src = pathlib.Path(fs.__file__).read_text(encoding="utf-8")
    compile(src, fs.__file__, "exec")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
