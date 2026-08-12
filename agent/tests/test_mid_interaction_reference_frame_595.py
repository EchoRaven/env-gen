r"""#595: two open dropdowns is not a state any app can be in.

#128/#542a demote a transient capture by the screen's NAME (`*_menu`, `*_dropdown`, `hover`,
`preview`, `ad`). §5.0t recorded the hole that leaves: on `player.jpg` the transient-ness was in
the IMAGE. `browse_by_languages` is the second independent instance and a worse one — mean
**0.424**, the worst screen in the arc, a blocker in **27 of 40** scored runs. Its reference was
captured with the Original-Language dropdown open, the language list open (Arabic→Vietnamese,
occluding the entire right column) AND a hover preview card over row 2. Three at once.

The measurement already says so, per region:

    original-language-dropdown   state "open, showing options"
    language-options-menu        state "expanded, long list visible"
    title-preview-popover        role "hover/preview popover…"   state "open over row 2"

The rule is physical, not aesthetic: opening a second dropdown CLOSES the first. Count
INDEPENDENT overlay clusters and demote at two. A dropdown and the list it opens are ADJACENT
(their intersection area is exactly zero), so they are linked by PROXIMITY and merged
transitively — otherwise every single dropdown would score 2. Over 45 design systems:

    browse_by_languages  1.78 mean, >=2 in 36/45   <- the target
    account_menu 1.78 (36/45) / shows_genres_menu 1.16 (8/45)  <- already advisory by NAME
    my_list 1.44 (21/45)  <- genuinely the same disease: r100's frame carries "third tile
        hovered -> expanded preview overlay", "like button hovered with 'I like this' tooltip
        visible", and a `status-url-tooltip` that is the BROWSER's own link-hover status bar.
    title_episodes 0.89 (3/45)
    login, games, player, browse_home, movies, shows, landing, genre_category, title_detail,
    card_preview, card_hover_preview, rate_dialog, player_controls          -> 0/45

`title_detail` is what a naive AREA threshold gets wrong: its modal occludes 0.504 of the frame,
more than any other screen, but it is ONE overlay and it IS the subject. Counting clusters keeps
it blocking (where #584 belongs); area would have excused it.
"""
import json

import pytest

from env_generator.llm_generator.multi_agent.runtime.visual_fidelity import (
    open_overlay_clusters as clusters,
    screens_captured_mid_interaction,
)


def _reg(id_, role, state, box):
    return {"id": id_, "role": role, "state": state, "region": list(box)}


# the real r142 browse_by_languages measurement
_BBL = [
    _reg("top-nav-bar", "global navigation bar", "Browse by Languages tab active", [0, 0, 1, .08]),
    _reg("original-language-dropdown", "dropdown selector for language type",
         "open, showing options", [.69, .10, .82, .13]),
    _reg("original-language-menu", "dropdown options list", "expanded", [.69, .13, .82, .22]),
    _reg("language-dropdown", "dropdown selector for specific language",
         "open, English selected", [.82, .10, .96, .13]),
    _reg("language-options-menu", "scrollable list of language options",
         "expanded, long list visible", [.82, .13, .96, .88]),
    _reg("row1-carousel", "first horizontal row of title cards", "5 tiles visible", [0, .26, 1, .43]),
    _reg("title-preview-popover", "hover/preview popover for a title",
         "open over row 2, showing THE CRASH", [.31, .37, .54, .76]),
]


def test_the_real_browse_by_languages_frame_reports_two_independent_interactions():
    """The two dropdowns (each merged with its own list) are one interaction each; the
    hover popover sits over row 2 and touches the language list, so the frame reports 2 —
    still >= 2, still unreproducible."""
    assert clusters({"regions": _BBL}) >= 2


def test_a_dropdown_and_its_own_list_count_once():
    """They overlap, so they are one interaction — otherwise every single dropdown scores 2."""
    one = [_reg("d", "dropdown selector", "open", [.7, .10, .82, .13]),
           _reg("m", "dropdown options list", "expanded", [.7, .13, .82, .22])]
    assert clusters({"regions": one}) == 1      # they SHARE an edge: intersection area is 0


def test_the_title_detail_modal_is_ONE_overlay_and_stays_blocking():
    """The case an area threshold gets wrong: biggest occlusion in the arc, but it IS
    the subject of the screen."""
    modal = [_reg("detail-modal", "title detail modal over the browse grid", "open",
                  [.15, .05, .85, .95])]
    assert clusters({"regions": modal}) == 1


def test_a_static_page_reports_zero():
    static = [_reg("nav", "global navigation bar", "default", [0, 0, 1, .08]),
              _reg("row", "horizontal row of title cards", "5 tiles visible", [0, .2, 1, .4])]
    assert clusters({"regions": static}) == 0


def test_a_closed_dropdown_is_not_an_open_overlay():
    assert clusters({"regions": [_reg("d", "dropdown selector", "collapsed", [.7, .1, .8, .14]),
                                 _reg("e", "dropdown selector", "default", [.8, .1, .9, .14])]}) == 0


def test_a_non_overlay_role_is_never_counted_however_it_is_described():
    assert clusters({"regions": [_reg("r", "carousel row", "expanded", [0, .2, 1, .4]),
                                 _reg("s", "sidebar", "open", [0, 0, .2, 1])]}) == 0


def test_the_components_key_is_accepted_too():
    assert clusters({"components": _BBL}) == clusters({"regions": _BBL}) >= 2


def test_junk_is_inert():
    assert clusters(None) == 0
    assert clusters({}) == 0
    assert clusters({"regions": [None, "x", {}, {"role": "dropdown", "state": "open"}]}) == 0
    assert clusters({"regions": [_reg("d", "dropdown", "open", [1, 1, 0, 0])]}) == 0   # bad box


# --- reading it off a real project tree ---------------------------------------------------------

def _project(tmp_path, screens):
    d = tmp_path / "design"
    d.mkdir(parents=True, exist_ok=True)
    (d / "design_system.json").write_text(json.dumps({"screens": screens}), encoding="utf-8")
    return tmp_path


def test_only_screens_at_two_or_more_are_reported(tmp_path):
    p = _project(tmp_path, [
        {"name": "browse_by_languages", "regions": _BBL},
        {"name": "title_detail", "regions": [_reg("m", "detail modal", "open", [.1, .1, .9, .9])]},
        {"name": "browse_home", "regions": [_reg("nav", "nav bar", "default", [0, 0, 1, .1])]},
    ])
    got = screens_captured_mid_interaction(p)
    assert list(got) == ["browse_by_languages"] and got["browse_by_languages"] >= 2, got


def test_no_design_system_means_no_opinion(tmp_path):
    assert screens_captured_mid_interaction(tmp_path) == {}


def test_a_malformed_design_system_is_inert(tmp_path):
    d = tmp_path / "design"
    d.mkdir(parents=True)
    (d / "design_system.json").write_text("{not json", encoding="utf-8")
    assert screens_captured_mid_interaction(tmp_path) == {}


# --- the demotion wiring --------------------------------------------------------------------------

def _persist_src():
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf
    return inspect.getsource(vf._persist_verdict)


def test_the_demotion_runs_before_the_chrome_checks():
    """A screen excused here must not then be re-examined by #588/#589."""
    src = _persist_src()
    assert src.index("screens_captured_mid_interaction") < src.index("_screen_is_player_449")


def test_an_already_advisory_screen_is_left_alone():
    src = _persist_src()
    i = src.index("screens_captured_mid_interaction")
    assert 'if _s.get("advisory"):' in src[i:i + 400]


def test_the_reason_states_the_physical_argument():
    src = _persist_src()
    i = src.index("#595 reference frame was captured")
    window = src[i:i + 400]
    assert "independent overlays open" in window
    assert "opening one closes another" in window


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
