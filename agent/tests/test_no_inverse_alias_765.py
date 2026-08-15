r"""#765: the alias repair could rewire an operation to its own inverse.

`_best_match` resolves a name a component imports from `api.js` but which `api.js` does not
export, by SYMMETRIC substring containment: `_norm(e) in target or target in _norm(e)`. That rule
exists for honest near-misses — `getTitle` → `getTitles` — and it is right for those.

A negation PREFIX makes the base name a strict substring of its own opposite, so the same rule
produced:

    unrateTitle  -> rateTitle        unfollowUser -> followUser
    unlikePost   -> likePost         deactivateUser -> activateUser

**This is worse than #753's stub.** A stub says on the console that the implementation is missing
and returns an empty value. An inverse alias APPEARS TO WORK: "unlike" likes, "unfollow" follows,
and nothing in the app, the delivery gate or the log contradicts it.

Refused only when the whole remainder matches — the containment rule keeps every case it was
built for. `disableProfile`/`enableProfile` and `logout`/`login` never reach here at all: they
fail containment, which is why the corpus shape to guard is specifically the prefix.

Found by sweeping every framework repair that MUTATES generated source (29 of them) for the one
property #764 turned out to have: choosing a replacement from a candidate set. Exactly two do —
`repair_dead_nav_links` (#764) and this one.
"""
import inspect
import logging

import pytest

from env_generator.llm_generator.multi_agent.runtime import frontend_scaffold as fs


# --- the inversions, both directions ------------------------------------------------------------

@pytest.mark.parametrize("missing,exported", [
    ("unrateTitle", "rateTitle"),
    ("unfollowUser", "followUser"),
    ("unlikePost", "likePost"),
    ("deactivateUser", "activateUser"),
    ("disconnectAccount", "connectAccount"),
    ("nonMemberView", "memberView"),
    ("antiAliasFrame", "aliasFrame"),
])
def test_a_negated_name_is_never_aliased_to_its_base(missing, exported):
    assert fs._best_match(missing, {exported}) is None


@pytest.mark.parametrize("missing,exported", [
    ("rateTitle", "unrateTitle"),
    ("likePost", "unlikePost"),
])
def test_the_refusal_is_symmetric(missing, exported):
    """Either side may be the negated one — the lane can be missing either."""
    assert fs._best_match(missing, {exported}) is None


def test_the_refusal_is_announced():
    """Silent refusal would just look like the stub path, and #758's lesson is that an
    improvement nobody can see fired cannot be evaluated."""
    src = inspect.getsource(fs._best_match)
    assert "#765 refusing to alias" in src
    assert "APPEARS TO WORK" in src


# --- everything the containment rule exists for still works -------------------------------------

@pytest.mark.parametrize("missing,exported", [
    ("getTitle", "getTitles"),
    ("removeTitle", "removeTitleFromList"),
    ("getMyList", "getMyListItems"),
    ("fetchGenre", "fetchGenres"),
])
def test_an_honest_near_miss_is_still_aliased(missing, exported):
    assert fs._best_match(missing, {exported}) == exported


def test_an_exact_normalised_match_is_untouched():
    assert fs._best_match("get_titles", {"getTitles"}) == "getTitles"


def test_a_real_inverse_still_falls_through_to_the_stub():
    """Refusing must not mean 'do nothing' — #753's stub is the correct destination, and it
    tells the lane the implementation is MISSING rather than silently doing the opposite."""
    assert fs._best_match("unlikePost", {"likePost"}) is None


def test_a_better_candidate_is_still_chosen_when_one_exists():
    """Refusing the inverse must not discard the whole candidate set."""
    assert fs._best_match("unlikePost", {"likePost", "unlikePosts"}) == "unlikePosts"


# --- the predicate ----------------------------------------------------------------------------------

@pytest.mark.parametrize("a,b,expected", [
    ("unratetitle", "ratetitle", True),
    ("ratetitle", "unratetitle", True),
    ("gettitle", "gettitles", False),      # a SUFFIX difference is not a negation
    ("ratetitle", "ratetitle", False),     # identical is not an inverse
    ("", "ratetitle", False),
    ("ratetitle", "", False),
    ("understand", "stand", False),        # "under" is not in the prefix list
])
def test_the_inverse_predicate(a, b, expected):
    assert fs._is_inverse_of_765(a, b) is expected


def test_the_prefix_list_is_whole_word_negations_only():
    """A loose list would start refusing honest matches. `re`/`pre`/`sub` are NOT negations."""
    for bad in ("re", "pre", "sub", "over", "under", "multi"):
        assert bad not in fs._NEGATION_PREFIXES_765, bad


# --- provenance ----------------------------------------------------------------------------------------

def _prov() -> str:
    src = inspect.getsource(fs._best_match)
    i = src.index("#765: NEVER ALIAS AN OPERATION TO ITS INVERSE")
    return " ".join(l.strip().lstrip("#").strip() for l in src[i:src.index("_rej765 =", i)].split("\n"))


def test_the_examples_are_recorded():
    p = _prov()
    assert "unrateTitle  -> rateTitle" in p or "unrateTitle -> rateTitle" in p
    assert "unlikePost" in p


def test_it_records_why_this_beats_the_stub_in_severity():
    p = _prov()
    assert "worse than #753's stub" in p
    assert "APPEARS TO WORK" in p


def test_it_records_what_must_NOT_start_being_refused():
    p = _prov()
    assert "getTitle -> getTitles" in p


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
