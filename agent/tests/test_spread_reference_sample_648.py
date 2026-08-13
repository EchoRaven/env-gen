r"""#648: the design-system compile saw the same six screens in all 45 runs — chosen by filename.

The spec compile takes `reference_images[:_MAX_IMAGES_IN_COMPILE]`, and the list arrives in
`Path.glob` order, which on every kept run equals alphabetical order — verified directly: the real
first six match the sorted first six in **45 of 45**. Every run ships **20** references, so the cap
binds every time and always cuts in the same place:

    reaching the compile, in all 45 runs:
        account_menu, browse_by_languages, browse_home, browse_home_rows,
        card_hover_preview, card_preview
    never reaching it, in any run:
        login, player, title_detail, games, genre_category, movies, shows,
        my_list, new_and_popular, landing

An alphabetical cut is not a neutral one. Classified against the corpus:

    all references            532 page / 328 overlay     -> overlay 36%
    the six the compile saw   111 page / 147 overlay     -> overlay 54%

More than half the global design-token budget went on modals and hover cards. A strided sample
inverts it — 180 page / 90 overlay, i.e. 33% overlay, matching the corpus — and reaches `player`
and `games`, two of the screens the visual gate keeps failing.

Striding rather than classifying, because `load_screen_classifications` reads design_system.json,
which is this compile's OUTPUT: it does not exist yet at this point.

Found while testing six constants I had called "unmeasurable" the turn before. `_MAX_IMAGES_IN_COMPILE`
was measurable in one query: 20 references against a cap of 6, in 45 of 45 runs.
"""
import pytest

from env_generator.llm_generator.multi_agent.runtime.reference_materials import (
    _MAX_IMAGES_IN_COMPILE as CAP,
    _spread_sample_648 as spread,
)


# --- the spread -----------------------------------------------------------------------------

def test_it_draws_from_across_the_whole_set():
    """The real shape: 20 references, a budget of 6."""
    got = spread(list(range(20)), 6)
    assert got == [0, 3, 6, 10, 13, 16]
    assert max(got) >= 16, "a prefix would have stopped at 5"


def test_it_returns_exactly_the_budget():
    for n in (7, 20, 100):
        assert len(spread(list(range(n)), 6)) == 6


def test_a_short_list_is_returned_whole():
    assert spread([1, 2, 3], 6) == [1, 2, 3]
    assert spread(list(range(6)), 6) == list(range(6))


def test_it_preserves_order():
    got = spread(list("abcdefghijklmnopqrst"), 6)
    assert got == sorted(got, key="abcdefghijklmnopqrst".index)


def test_it_never_repeats_or_overruns():
    for n in range(1, 60):
        got = spread(list(range(n)), 6)
        assert len(set(got)) == len(got)
        assert all(0 <= g < n for g in got)


def test_it_is_deterministic():
    seq = [f"s{i}" for i in range(20)]
    assert spread(seq, 6) == spread(seq, 6)


def test_degenerate_budgets_are_safe():
    assert spread(list(range(10)), 0) == []
    assert spread(list(range(10)), -1) == []
    assert spread([], 6) == []


def test_it_does_not_mutate_the_caller_list():
    seq = list(range(20))
    spread(seq, 6)
    assert seq == list(range(20))


# --- what it fixes, on the real screen names --------------------------------------------------

_REFS = sorted([
    "account_menu", "browse_by_languages", "browse_home", "browse_home_rows",
    "card_hover_preview", "card_preview", "games", "genre_category", "landing", "login",
    "movies", "my_list", "new_and_popular", "player", "player_controls", "rate_dialog",
    "shows", "shows_genres_menu", "title_detail", "title_episodes",
])


def test_the_prefix_missed_every_failing_screen():
    """login 29/40, player 20/40, title_detail 20/40, genre_category 9/40, games 8/40 — the
    gate's worst screens, and the alphabetical head contains none of them."""
    head = _REFS[:CAP]
    for screen in ("login", "player", "title_detail", "genre_category", "games"):
        assert screen not in head


def test_the_spread_reaches_screens_the_prefix_never_did():
    got = spread(_REFS, CAP)
    assert set(got) - set(_REFS[:CAP]), "the sample must not be the prefix again"
    assert any(s in got for s in ("player", "games", "movies", "shows"))


def test_the_budget_is_unchanged():
    """#648 changes WHICH images, never HOW MANY — the multimodal call's budget is untouched."""
    assert CAP == 6
    assert len(spread(_REFS, CAP)) == CAP


# --- wiring ---------------------------------------------------------------------------------

def test_the_compile_uses_the_spread_not_a_slice():
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import reference_materials as rm
    src = inspect.getsource(rm)
    assert "_spread_sample_648(reference_images or [], _MAX_IMAGES_IN_COMPILE)" in src
    assert "[:_MAX_IMAGES_IN_COMPILE]" not in src


def test_the_measurement_is_recorded():
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import reference_materials as rm
    flat = " ".join(inspect.getsource(rm._spread_sample_648).split())
    assert "45 of 45" in flat
    assert "532 page / 328 overlay" in flat and "111 page / 147 overlay" in flat


def test_why_classification_is_not_used_is_recorded():
    """It would be the obvious approach; the next reader must see why it cannot work here."""
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import reference_materials as rm
    flat = " ".join(inspect.getsource(rm._spread_sample_648).split())
    assert "does not exist yet" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
