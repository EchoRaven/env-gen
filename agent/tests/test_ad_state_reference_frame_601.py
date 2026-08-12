r"""#601: the other unreproducible frame — an ad was playing when the reference was captured.

#595 handles a frame caught mid-INTERACTION. This handles one caught mid-INTERSTITIAL: the case
§5.0t found on `player.jpg` ("Ad 12", "All American begins after ads"), where the only answers
available at the time were #588's bespoke chrome checklist and a recommendation that a HUMAN swap
the asset. Swapping an image does not generalize — the next product's capture lands on its own ad
— so the rule has to come from the measurement, exactly as #595's does.

An advertisement is a GENERIC UI concept, like a dropdown or a popover, and no generation task
asks the app to build an ad system. A reference whose measured STATE says an ad is playing is
scoring the implementation against something nobody asked for.

Every refinement below was forced by a real false positive over the corpus's 2880 screens:

    role/id keyword match     -> flagged `player_controls`, whose role says "No 'Ad NN' chip"
    state match, negations on -> still flagged it
    no live-playback context  -> flagged `landing` x60, whose state carries the marketing copy
                                 "…with subtitle about ad-supported plan" — copy the app SHOULD
                                 reproduce, not an ad on screen

With all three: 142 hits, every one `player`; 2738 of 2880 screens untouched.
"""
import json

import pytest

from env_generator.llm_generator.multi_agent.runtime.visual_fidelity import (
    reference_shows_an_ad as shows_ad,
    screens_captured_showing_an_ad,
)


def _reg(id_, role, state):
    return {"id": id_, "role": role, "state": state}


# the real r142 `player` measurement
_PLAYER_AD = [
    _reg("back-button", "top-left back arrow navigation control", "idle icon over dark video"),
    _reg("flag-button", "top-right report/flag ad icon button", "idle"),
    _reg("ad-counter-badge", "top-right ad countdown indicator showing 'Ad 12'",
         "'Ad 12' — ad playing"),
    _reg("video-playback-surface", "full-screen video player background showing ad content",
         "playing ad, dim cinematic scene"),
    _reg("subtitle-caption", "centered bottom caption text overlay",
         "shows 'All American begins after ads'"),
]


def test_the_real_player_frame_is_recognised():
    assert shows_ad({"regions": _PLAYER_AD}) is True


def test_the_landing_marketing_copy_is_NOT_an_ad():
    """x60 in the corpus. `ad-supported plan` is copy the app must reproduce."""
    landing = [_reg("hero-headline", "two-line promo copy",
                    "'The Netflix you love for just $8.99.' with subtitle about "
                    "ad-supported plan")]
    assert shows_ad({"regions": landing}) is False


def test_a_NEGATED_mention_is_not_an_ad():
    """`player_controls` says "No 'Ad NN' chip — content is playing"."""
    pc = [_reg("chrome", "player_chrome top_bar",
               "No 'Ad NN' chip — content is playing")]
    assert shows_ad({"regions": pc}) is False


def test_the_role_field_alone_never_flags():
    """The flag button's ROLE says "report/flag ad icon button" on a normal player too."""
    assert shows_ad({"regions": [_reg("flag", "report/flag ad icon button", "idle")]}) is False


def test_the_generic_family_is_covered_not_just_the_word_ad():
    for st in ("interstitial playing", "commercial break remaining 0:12",
               "pre-roll playing", "mid-roll countdown active", "advertisement showing"):
        assert shows_ad({"regions": [_reg("x", "surface", st)]}) is True, st


def test_a_word_that_merely_contains_ad_is_not_a_match():
    for st in ("add to list active", "already loaded and showing", "read receipts showing",
               "download running", "thread playing"):
        assert shows_ad({"regions": [_reg("x", "surface", st)]}) is False, st


def test_an_ad_word_with_no_live_context_is_not_an_ad_on_screen():
    assert shows_ad({"regions": [_reg("x", "plan card", "mentions the ad tier")]}) is False


def test_an_ordinary_screen_is_untouched():
    ok = [_reg("nav", "global navigation bar", "default"),
          _reg("row", "horizontal row of title cards", "5 tiles visible")]
    assert shows_ad({"regions": ok}) is False


def test_junk_is_inert():
    assert shows_ad(None) is False
    assert shows_ad({}) is False
    assert shows_ad({"regions": [None, "x", {}]}) is False


def test_the_components_key_is_accepted_too():
    assert shows_ad({"components": _PLAYER_AD}) is True


# --- reading it off a project tree ----------------------------------------------------------

def test_only_the_ad_screen_is_reported(tmp_path):
    d = tmp_path / "design"
    d.mkdir(parents=True)
    (d / "design_system.json").write_text(json.dumps({"screens": [
        {"name": "player", "regions": _PLAYER_AD},
        {"name": "landing", "regions": [_reg("h", "promo copy",
                                             "subtitle about ad-supported plan")]},
        {"name": "browse_home", "regions": [_reg("nav", "nav bar", "default")]},
    ]}), encoding="utf-8")
    assert screens_captured_showing_an_ad(tmp_path) == {"player"}


def test_no_design_system_means_no_opinion(tmp_path):
    assert screens_captured_showing_an_ad(tmp_path) == set()


# --- the wiring -------------------------------------------------------------------------------

def test_it_demotes_on_the_same_path_as_595_and_short_circuits():
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf
    src = inspect.getsource(vf._persist_verdict)
    assert "screens_captured_showing_an_ad(project_dir)" in src
    i = src.index("#601 reference frame was captured")
    window = src[i:i + 400]
    assert "no generation task asks the app to build an ad system" in window
    assert "continue" in window          # one reason per screen, ad wins over the #595 text


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
