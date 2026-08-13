r"""#652: the rail position indicator — the corpus's most persistent missing component.

Ranking the judge's `missing` items by raw count ranks by how often a screen was JUDGED, so a
defect the lane repairs by round 3 outranks one that ships. `search icon` (192) and
`notifications bell` (184) top that list, but 19 of the 25 delivered navs that could carry them
do — they are convergence noise. Re-ranked by "reported missing AND still absent from the
DELIVERED frontend", the top of the list is a different component entirely, under five wordings:

    carousel pagination dots        45/45      row pagination indicator dots   25/26
    carousel pagination indicator   24/24      row pagination indicator        23/23
    row pagination dots             23/24      -> ~140 reports, ~100% persistent

Confirmed by SHAPE rather than wording, so it is not an artifact of my probe's vocabulary: only
**7 of 144** delivered frontends contain any dot-shaped element at all. 141 of 144 designs
enumerate one. No channel emitted it — #432b's control projector explicitly excludes
`pagination` so it never eats a nav utility, and nothing else picked it up.

Built like #454/#443/#445: gated on the design's own enumeration, deterministic markup, no data
dependency, `currentColor` so it themes with the rail rather than painting invisibly (#551).
"""
import re

import pytest

from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    _rail_pagination_652 as pag,
)


def _design(*roles):
    return {"screens": [{"components": [{"id": f"c{i}", "role": r}
                                        for i, r in enumerate(roles)]}]}


def _seg_class(out):
    return re.search(r'className="([^"]+)" style', out).group(1)


# --- the gate ---------------------------------------------------------------------------------

@pytest.mark.parametrize("role", [
    "hero carousel page indicator dots",
    "hero carousel page indicator dashes",
    "thin progress/pagination bar for hero carousel",
    "pagination bar for top 10 movies rail",
    "section title 'top searches' with pagination indicator",
    "rail-progress-indicator-3",
])
def test_it_fires_on_the_wordings_the_designs_actually_use(role):
    """Every one of these is a verbatim role string from the measured corpus."""
    assert pag(_design(role)) != ""


@pytest.mark.parametrize("role", [
    "a plain grid of cards", "primary nav", "hero banner with CTA buttons",
    "footer with legal links", "search input",
])
def test_a_design_that_enumerates_no_indicator_gets_nothing(role):
    """Generalizable: an app whose design has no indicator must render none."""
    assert pag(_design(role)) == ""


def test_an_empty_or_malformed_design_is_safe():
    for d in ({}, None, {"screens": []}, {"screens": [{}]}, {"screens": [{"components": None}]}):
        assert pag(d) == ""


def test_the_id_counts_as_enumeration_too():
    """The corpus carries the signal on the id ('carousel-pagination') as often as the role."""
    assert pag({"screens": [{"components": [{"id": "carousel-pagination", "role": "row"}]}]}) != ""


# --- the measured shape -------------------------------------------------------------------------

def test_dots_render_as_dots():
    assert _seg_class(pag(_design("hero carousel page indicator dots"))) == "h-1 w-1 rounded-full"


@pytest.mark.parametrize("role", [
    "hero carousel page indicator dashes",
    "thin progress/pagination bar for hero carousel",
    "pagination bar for top 10 movies rail",
])
def test_bars_and_dashes_render_as_bars(role):
    assert _seg_class(pag(_design(role))) == "h-0.5 w-4"


def test_an_unqualified_indicator_defaults_to_dots():
    assert _seg_class(pag(_design("carousel pagination"))) == "h-1 w-1 rounded-full"


def test_the_shape_word_must_be_NEAR_the_match():
    """'progress' 200 chars away in an unrelated component must not turn the dots into bars."""
    d = _design("upload progress bar", "carousel page indicator dots")
    assert _seg_class(pag(d)) == "h-1 w-1 rounded-full"


# --- the markup itself ----------------------------------------------------------------------

def test_it_themes_with_the_rail_instead_of_hardcoding_a_colour():
    """#551's lesson: an icon that does not inherit the nav/rail colour paints invisibly."""
    out = pag(_design("carousel pagination dots"))
    assert "currentColor" in out
    assert not re.search(r"#[0-9a-fA-F]{3,6}", out), "no hardcoded hex"


def test_the_first_segment_is_the_active_one():
    out = pag(_design("carousel pagination dots"))
    assert "_d === 0 ? 0.9 : 0.3" in out


def test_it_is_hidden_from_assistive_tech():
    """Decorative chrome — it carries no information a screen reader can act on."""
    assert 'aria-hidden="true"' in pag(_design("carousel pagination dots"))


def test_it_has_no_data_dependency():
    """It must render identically whether or not the rail has rows."""
    out = pag(_design("carousel pagination dots"))
    for token in ("rows", "_railSlice", "_padN", "fetch", "useState"):
        assert token not in out


def test_the_segment_count_matches_the_rails_existing_page_size():
    """Six — the same number `_padN(_railSlice(...), 6)` already pads to, not a new constant."""
    out = pag(_design("carousel pagination dots"))
    assert "[0, 1, 2, 3, 4, 5]" in out


def test_the_markup_is_balanced_jsx():
    out = pag(_design("carousel pagination dots"))
    assert out.count("<div") == out.count("</div>") == 1
    assert out.rstrip().endswith("</div>")


def test_it_is_deterministic():
    d = _design("carousel pagination dots")
    assert pag(d) == pag(d)


# --- wiring ---------------------------------------------------------------------------------

def test_the_rail_emits_it_between_the_card_row_and_the_block_close():
    """Position is the whole wiring: inside the rail block, after the scrolling card row."""
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import frontend_scaffold as fs
    src = inspect.getsource(fs)
    call = src.index("_rail_pagination_652(design)      # #652")
    cards = src.index("_padN(_railSlice")
    flex_close = src.index('+ "          </div>', cards)
    block_close = src.index('+ "        </div>', call)
    assert cards < flex_close < call < block_close


def test_the_measurement_is_recorded():
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import frontend_scaffold as fs
    flat = " ".join(inspect.getsource(fs._rail_pagination_652).replace("#", " ").split())
    assert "7 of 144" in flat and "141 of 144" in flat
    assert "800 of 1254" in flat


def test_why_the_raw_ranking_was_wrong_is_recorded():
    """The next reader will re-derive the naive ranking; the docstring must pre-empt it."""
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import frontend_scaffold as fs
    flat = " ".join(inspect.getsource(fs._rail_pagination_652).split())
    assert "still absent from the DELIVERED frontend" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
