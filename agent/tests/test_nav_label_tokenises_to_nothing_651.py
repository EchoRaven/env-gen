r"""#651: the projected nav shipped `<a href="/my-list">Home</a>` in 7 of 28 delivered navs.

Found by mining the judge's structured `components.missing` lists — an axis never opened. Over
the 112 verdict files / 1325 judged screen records:

    `components` is the FLOOR dimension on 800 of 1254 scored records (63.8%), 4.6x the next one
    `my list nav item` is the 3rd most-reported missing component (125), after search icon and
    the notifications bell — but unlike those two it is a MISROUTED link, not an absent one

Following it: the label IS measured (`_ref_nav_labels` returns it in 44 of 45 runs) and the route
IS registered (`/my-list` as a ui_page), yet 7 of the 28 delivered `TopNav.jsx` files carry
`Home -> /my-list` and NONE carry a correct My List link — byte-identical across independent runs,
because this is the framework's OWN projected nav (#520), not lane authorship.

The cause is a tokenizer that erases exactly the pairing that matters:

    _semantic_tokens_226("My List")        -> set()
    _semantic_tokens_226("", "/my-list")   -> set()

Both sides empty, so they can never score against each other. "My List" stays in `leftover`,
`/my-list` stays unassigned, and the Home-type fallback then picks it as the shortest unassigned
route — producing a link labelled "Home" that navigates to My List, with the real label gone.

#474 hit this same trap in the sibling `_filter_nav_to_ref` and switched to raw content words,
documenting it verbatim: *"NOT _semantic_tokens_226, which strips 'list'/'my' as layout words →
'My List' would tokenize to {}"*. `_assign_ref_labels` never got the same treatment. Raw tokens are
used ONLY when the semantic set is empty, so every pairing that works today is untouched.
"""
import pytest

from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    _assign_ref_labels as assign,
    _semantic_tokens_226 as sem,
)

_NAV = ("horizontal primary nav: Home, Shows, Movies, Games, New & Popular, "
        "My List, Browse by Languages")


def _design(role=_NAV):
    return {"screens": [{"components": [{"id": "primary-nav", "role": role}]}]}


_ROUTES = [("My-list", "/my-list"), ("Shows", "/shows"), ("Movies", "/movies"),
           ("Games", "/games"), ("New", "/new"), ("Browse", "/browse")]


def _paired(routes=None, design=None):
    return {rt: lbl for lbl, rt in assign(routes or _ROUTES, design or _design())}


# --- the defect ---------------------------------------------------------------------------------

def test_the_tokenizer_really_does_erase_both_sides():
    """The premise, pinned — if this ever changes the fallback becomes dead code."""
    assert sem("My List") == set()
    assert sem("", "/my-list") == set()


def test_my_list_now_pairs_with_its_own_route():
    assert _paired()["/my-list"] == "My List"


def test_the_route_is_no_longer_labelled_Home():
    """The shipped bug: `<a href="/my-list">Home</a>` — wrong label, wrong destination."""
    assert _paired()["/my-list"] != "Home"


def test_no_label_is_used_twice():
    labels = [lbl for lbl, _ in assign(_ROUTES, _design())]
    assert len(labels) == len(set(labels))


# --- everything that already worked must not move -------------------------------------------------

@pytest.mark.parametrize("route,label", [
    ("/shows", "Shows"), ("/movies", "Movies"), ("/games", "Games"),
    ("/new", "New & Popular"), ("/browse", "Browse by Languages"),
])
def test_the_pairings_that_already_worked_are_unchanged(route, label):
    assert _paired()[route] == label


def test_a_home_route_still_gets_the_home_label():
    routes = [("Home", "/"), ("Shows", "/shows"), ("My-list", "/my-list")]
    assert _paired(routes)["/"] == "Home"
    assert _paired(routes)["/my-list"] == "My List"


def test_a_route_with_no_confident_label_keeps_its_own():
    routes = [("Settings", "/settings"), ("Shows", "/shows")]
    assert _paired(routes)["/settings"] == "Settings"


def test_no_enumeration_is_a_no_op():
    assert assign(_ROUTES, {"screens": []}) == _ROUTES


def test_stopwords_do_not_create_false_matches():
    """`by`/`and`/`of` must not pair 'Browse by Languages' with an unrelated '/by' route."""
    routes = [("Bytes", "/bytes"), ("Shows", "/shows")]
    assert _paired(routes)["/bytes"] == "Bytes"


# --- #651b: the fallback must not invent a home route ---------------------------------------------
#
# #651 stops "My List" going unmatched; #651b stops the MECHANISM that consumed it. The fallback
# used to `min()` over ALL unassigned routes, so with no root left it relabelled the shortest
# survivor — whatever it was. Diffed over the 28 delivered navs, old vs new, every changed label
# is a "Home" being taken OFF a route that is not home, and nothing changes the other way:
#
#     /profiles 'Home' -> 'Profiles'  x4      /my-list 'Home' -> 'My List'  x2
#     /help     'Home' -> 'Help'      x1      routes that legitimately said Home: unchanged

def test_an_unrelated_route_is_never_relabelled_Home():
    """The old code labelled /help and /profiles 'Home' purely for being short."""
    for route in ("/help", "/profiles", "/settings", "/bytes"):
        routes = [("X", route), ("Shows", "/shows")]
        assert _paired(routes)[route] != "Home"


def test_a_real_root_still_wins_the_home_label():
    routes = [("Index", "/"), ("Help", "/help"), ("Shows", "/shows")]
    assert _paired(routes)["/"] == "Home"


@pytest.mark.parametrize("route", ["/", "/home", "/browse", "/dashboard", "/feed", "/index"])
def test_the_home_label_lands_on_any_conventional_root(route):
    """Generalizable: the root is not always '/' — but it is not '/help' either.

    A bare enumeration, so nothing competes: with the full Netflix nav in play `/browse`
    is legitimately claimed by "Browse by Languages" before the fallback ever runs.
    """
    plain = _design("horizontal primary nav: Home, Help")
    assert _paired([("X", route), ("Help", "/help")], plain)[route] == "Home"


def test_the_root_is_preferred_over_another_home_ish_segment():
    routes = [("Feed", "/feed"), ("Index", "/")]
    assert _paired(routes)["/"] == "Home"


def test_with_no_root_at_all_the_label_is_simply_dropped():
    """A missing nav item is a components deduction; a mislabelled one is a broken link."""
    routes = [("Help", "/help"), ("Shows", "/shows")]
    assert "Home" not in [lbl for lbl, _ in assign(routes, _design())]


def test_an_already_claimed_root_is_not_stolen():
    routes = [("Browse", "/browse"), ("Help", "/help")]
    out = _paired(routes)
    assert out["/browse"] == "Browse by Languages"
    assert out["/help"] == "Help"


def test_the_651b_measurement_is_recorded():
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import frontend_scaffold as fs
    flat = " ".join(inspect.getsource(fs._assign_ref_labels).replace("#", " ").split())
    assert "7 of 28 delivered navs" in flat
    assert "0 of 28 lack a root" in flat


# --- the raw fallback is narrow -----------------------------------------------------------------

def test_raw_tokens_are_used_ONLY_when_the_semantic_set_is_empty():
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import frontend_scaffold as fs
    src = inspect.getsource(fs._assign_ref_labels)
    i = src.index("def _toks_651")
    block = src[i:src.index("rtoks = [_toks_651", i)]
    assert "if sem:" in block and "return sem" in block


def test_the_sibling_that_already_fixed_this_is_credited():
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import frontend_scaffold as fs
    flat = " ".join(inspect.getsource(fs._assign_ref_labels).replace("#", " ").split())
    assert "474" in flat and "_filter_nav_to_ref" in flat


def test_the_measurement_is_recorded():
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import frontend_scaffold as fs
    flat = " ".join(inspect.getsource(fs._assign_ref_labels).replace("#", " ").split())
    assert "125 mentions" in flat
    assert "800 of 1254" in flat and "1325 judged screen records" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
