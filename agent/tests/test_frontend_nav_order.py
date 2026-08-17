"""#458 (r40 judge docked EVERY content page for 'nav order' not matching the
reference — including the two screens that crossed 0.65: games 0.72 & my_list 0.70,
where nav order is the remaining gap). The nav rendered links in contract/route
order; the design's measured nav enumeration specifies the ORDER (Home, Shows,
Movies, Games, New & Popular, My List, …). FIX: reorder the (already ref-relabeled)
links to match the enumeration; unmatched labels stay at the end (stable); href +
active-state unchanged. Generalizable, no product literals. Locks it in."""
from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    _order_nav_by_ref, _ref_nav_jsx)


def _design(nav_role):
    return {"screens": [{"name": "s", "components": [
        {"id": "primary-nav-links", "role": nav_role}]}]}


_D = _design("primary nav links: Home, Shows, Movies, Games, New & Popular, My List")


def test_reorders_to_ref_enumeration():
    # routes arrive in a SCRAMBLED (contract) order; must come out in ref order
    routes = [("Movies", "/movies"), ("Home", "/browse"), ("My List", "/my-list"),
              ("Shows", "/shows"), ("Games", "/games"), ("New & Popular", "/new")]
    out = _order_nav_by_ref(routes, _D)
    assert [l for l, _ in out] == ["Home", "Shows", "Movies", "Games",
                                   "New & Popular", "My List"]
    # href preserved for each label
    assert dict(out)["Games"] == "/games" and dict(out)["Home"] == "/browse"


def test_unmatched_labels_kept_stable_at_end():
    routes = [("Games", "/games"), ("Account", "/account"), ("Home", "/browse"),
              ("Settings", "/settings")]
    out = _order_nav_by_ref(routes, _D)
    labels = [l for l, _ in out]
    assert labels[:2] == ["Home", "Games"], "ref-matched first, in ref order"
    assert labels[2:] == ["Account", "Settings"], "unmatched keep original relative order at end"


def test_noop_without_nav_enumeration():
    routes = [("B", "/b"), ("A", "/a")]
    assert _order_nav_by_ref(routes, {}) == routes, "no enumeration → unchanged"


def test_integration_nav_renders_in_ref_order():
    routes = [("Movies", "/movies"), ("Home", "/browse"), ("Shows", "/shows")]
    out = _ref_nav_jsx(routes, "#e50914", vertical=False, design=_D)
    # the rendered <a> for Home must appear before Movies in the markup
    iHome, iShows, iMovies = out.find(">Home<"), out.find(">Shows<"), out.find(">Movies<")
    assert -1 < iHome < iShows < iMovies, "links rendered in ref enumeration order"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
