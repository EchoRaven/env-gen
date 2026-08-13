r"""#654: the Kids chip hardcoded `/browse`, so it duplicated the nav item beside it.

`_nav_chrome_454`'s docstring promises "generalizable, no product literals" — and then emits
`<a href="/browse" aria-label="Kids">`. A route literal, for a destination the chip does not own.

Measured over the 28 delivered navs: **17** contain two nav items pointing at ONE page, and
**16 of those 17** are this chip colliding:

    x8  /browse <- ['Home', 'Kids']        x7  /browse <- ['Browse by Languages', 'Kids']

So "Kids" lands on exactly the page the item next to it already goes to. A user-agent asked to
open Kids cannot tell it apart from Browse, and the page it gets is the unfiltered catalog.

Same class as #653 — an affordance that says one thing and does another. Found by auditing every
`<button>`/`<a>` the framework emits for label-vs-destination agreement (80 controls; the other
flags were synonyms like 'Sign in' -> /login, plus two that matched the #651 docstring's own
example literal — the probe photographing itself).

The target now resolves from the app's OWN registered nav routes. With no kids/family route the
chip renders as what the design actually enumerates — a "kids profile chip"/"badge" — instead of
a link to somewhere else. A badge under-delivers a component; a mislabelled link is a broken one.
"""
import pytest

from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    _nav_chrome_454 as chrome,
)

_DESIGN = {"screens": [{"components": [{"id": "nav", "role": "top nav with Kids link"}]}]}


def _kids(routes):
    out = chrome(_DESIGN, routes=routes)
    return next((l.strip() for l in out.splitlines() if 'aria-label="Kids"' in l), "")


# --- the collision is gone -------------------------------------------------------------------

def test_it_no_longer_hardcodes_browse():
    """The literal that caused every collision."""
    assert 'href="/browse"' not in _kids([("Home", "/"), ("Browse", "/browse")])


def test_with_no_kids_route_it_is_a_badge_not_a_link():
    chip = _kids([("Home", "/"), ("Browse", "/browse")])
    assert chip.startswith("<span")
    assert "href" not in chip


def test_the_badge_still_says_Kids():
    chip = _kids([("Home", "/"), ("Browse", "/browse")])
    assert ">Kids<" in chip and 'aria-label="Kids"' in chip


def test_it_never_duplicates_an_existing_nav_destination():
    """The defect, stated as the property: 16 of 17 duplicate navs were this chip."""
    routes = [("Home", "/"), ("Browse", "/browse"), ("Shows", "/shows")]
    chip = _kids(routes)
    for _lbl, rt in routes:
        assert f'href="{rt}"' not in chip


# --- it links when a real target exists ----------------------------------------------------------

@pytest.mark.parametrize("route", ["/kids", "/kid", "/children", "/family", "/junior"])
def test_a_registered_kids_route_is_used(route):
    assert f'href="{route}"' in _kids([("Home", "/"), ("X", route)])


def test_a_nested_kids_route_is_matched_on_its_last_segment():
    assert 'href="/browse/kids"' in _kids([("Home", "/"), ("X", "/browse/kids")])


def test_an_unrelated_route_is_not_mistaken_for_one():
    for route in ("/kidney", "/familiar", "/shows"):
        chip = _kids([("Home", "/"), ("X", route)])
        assert chip.startswith("<span"), route


def test_the_first_matching_route_wins_and_it_is_deterministic():
    routes = [("A", "/kids"), ("B", "/family")]
    assert _kids(routes) == _kids(routes)
    assert 'href="/kids"' in _kids(routes)


# --- the gate and the rest of the cluster are untouched -------------------------------------------

def test_a_design_that_does_not_enumerate_kids_gets_no_chip():
    """Kids stays enumeration-gated (product-specific) exactly as #469 left it."""
    d = {"screens": [{"components": [{"id": "nav", "role": "top nav with search"}]}]}
    assert 'aria-label="Kids"' not in chrome(d, routes=[("Kids", "/kids")])


def test_skip_still_suppresses_it():
    assert _kids([("X", "/kids")]) != ""
    assert 'aria-label="Kids"' not in chrome(_DESIGN, skip={"kids"}, routes=[("X", "/kids")])


def test_calling_without_routes_is_safe():
    """Older call sites pass no routes; that must degrade to the badge, not crash."""
    chip = next((l for l in chrome(_DESIGN).splitlines() if 'aria-label="Kids"' in l), "")
    assert chip.strip().startswith("<span")


def test_the_styling_is_unchanged_between_both_forms():
    styled = 'className="rounded border px-2 py-0.5 text-xs font-semibold opacity-90"'
    assert styled in _kids([("Home", "/")])
    assert styled in _kids([("X", "/kids")])


def test_the_nav_passes_its_own_routes_through():
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import frontend_scaffold as fs
    assert "routes=nav_routes" in inspect.getsource(fs._ref_nav_jsx)


def test_the_measurement_is_recorded():
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import frontend_scaffold as fs
    flat = " ".join(inspect.getsource(fs._nav_chrome_454).replace("#", " ").split())
    assert "17 contain two nav items pointing at ONE page" in flat
    assert "16 of those 17" in flat


def test_the_reason_a_badge_beats_a_wrong_link_is_recorded():
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import frontend_scaffold as fs
    flat = " ".join(inspect.getsource(fs._nav_chrome_454).split())
    assert "a mislabelled link is a broken one" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
