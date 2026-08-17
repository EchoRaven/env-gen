r"""#584: several screens routinely share one route — a detail modal, its rating dialog and its
episode list are all classified `/title/:id`. The exact-route pass returned the FIRST screen with
`kind == 'page'`, so the winner depended on how the LLM happened to classify `kind`.

Measured on the real designs:

    r137  /title/:id -> rate_dialog(page,17)  beat  title_detail(overlay,13)   WRONG
    r142  /title/:id -> rate_dialog(page,16)  beat  title_detail(overlay,17)   WRONG
    r139  /title/:id -> title_detail                                           right, by luck
                        (all three candidates were overlays, so the first won)
    r137/r142  /browse -> card_hover_preview(page)  beat  browse_home(overlay) WRONG

So the title-detail PAGE was rendered from a RATING DIALOG's regions in two of three runs. That
is the standing explanation for `title_detail` 0.50 in r142: the page is not lane-authored (it
imports no `../components/`), so the wrong-screen projection is what ships. `browse_home` lost
the same way but scored 0.85 anyway — the lane rewrote that page, which masked the mismatch.

Fix: rank exact-route candidates the way #571 already ranks fuzzy ones — name coverage first,
then the documented page-over-overlay preference, then richness.
"""
import pytest

from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    _design_screen_for_route as match,
)


def _s(name, kind, n=5, route="/title/:id"):
    return {"name": name, "kind": kind, "route": route,
            "components": [{"role": f"r{i}"} for i in range(n)]}


_HINTS = ("title_detail_page", "page:ui:title_detail_page", "TitleDetailPage",
          "title_detail_page")


def test_r142_the_detail_page_no_longer_resolves_to_the_rating_dialog():
    design = {"screens": [_s("rate_dialog", "page", 16), _s("title_detail", "overlay", 17)]}
    assert match(design, "/title/:id", hints=_HINTS)["name"] == "title_detail"


def test_r137_same_shape_with_the_component_counts_reversed():
    """The old rule lost regardless of richness; the new one must not depend on it either."""
    design = {"screens": [_s("rate_dialog", "page", 17), _s("title_detail", "overlay", 13)]}
    assert match(design, "/title/:id", hints=_HINTS)["name"] == "title_detail"


def test_browse_home_beats_an_overlay_that_happens_to_be_typed_page():
    design = {"screens": [_s("account_menu", "overlay", 14, "/browse"),
                          _s("browse_home", "overlay", 19, "/browse"),
                          _s("card_hover_preview", "page", 12, "/browse")]}
    got = match(design, "/browse", hints=("browse_home_page", "id", "BrowseHomePage",
                                          "browse_home_page"))
    assert got["name"] == "browse_home"


def test_declaration_order_no_longer_decides():
    """r139 was right only because its candidates happened to be ordered favourably."""
    a = [_s("rate_dialog", "overlay", 9), _s("title_detail", "overlay", 13)]
    assert match({"screens": a}, "/title/:id", hints=_HINTS)["name"] == "title_detail"
    assert match({"screens": list(reversed(a))}, "/title/:id",
                 hints=_HINTS)["name"] == "title_detail"


def test_with_no_name_signal_the_page_preference_still_applies():
    """Degrades to the documented behaviour when nothing in the hints names a screen."""
    design = {"screens": [_s("alpha", "overlay", 9), _s("beta", "page", 3)]}
    assert match(design, "/title/:id", hints=("zzz",))["name"] == "beta"


def test_a_single_exact_match_is_returned_unchanged():
    design = {"screens": [_s("title_detail", "overlay", 17)]}
    assert match(design, "/title/:id", hints=_HINTS)["name"] == "title_detail"


def test_component_less_screens_are_still_ignored():
    design = {"screens": [{"name": "title_detail", "kind": "overlay",
                           "route": "/title/:id", "components": []},
                          _s("rate_dialog", "page", 16)]}
    assert match(design, "/title/:id", hints=_HINTS)["name"] == "rate_dialog"


def test_no_exact_match_still_falls_through_to_fuzzy():
    design = {"screens": [_s("title_detail", "overlay", 17, "/completely/other")]}
    got = match(design, "/title/:id", hints=_HINTS)
    assert got is None or got["name"] == "title_detail"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
