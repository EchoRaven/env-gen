"""#422 (netflix r15 verdict.json): the visual judge flagged WRONG nav copy on every
screen (copy dim 0.40) — "labels differ: Profiles/Browse/New vs Home/Shows/Movies/
Games/New & Popular/My List/Browse by Languages". Root: the projector labels nav
items from the URL SEGMENT (/new→'New', /browse→'Browse'), not the reference's
measured labels. The design_system DOES carry them (primary-nav-links component
role: 'horizontal primary nav: Home, Shows, Movies, ...').

FIX: _ref_nav_labels parses those labels; _assign_ref_labels relabels each app route
with the best UNIQUE reference label, keeping the href unchanged (navigation intact)
and falling back to the segment label when no confident match. The tricky case —
/browse ('Browse', the home page) and /browse/languages both token-match 'Browse by
Languages' — is resolved by greedy-by-overlap (the 2-token /browse/languages wins it)
plus a Home-type leftover paired to the primary browse route. Locks this in."""
from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    _ref_nav_labels, _assign_ref_labels, _ref_nav_jsx)

_DESIGN = {"screens": [{"components": [
    {"id": "primary-nav-links",
     "role": "horizontal primary nav: Home, Shows, Movies, Games, New & Popular, My List, Browse by Languages",
     "state": "'Home' pill selected/highlighted"}]}]}

# app routes with the projector's current segment-derived labels (incl the collision pair)
_ROUTES = [("Browse", "/browse"), ("Shows", "/shows"), ("Movies", "/movies"),
           ("Games", "/games"), ("New", "/new"), ("My List", "/my-list"),
           ("Browse Languages", "/browse/languages"), ("Search", "/search")]


def test_parses_labels_from_primary_nav_role():
    assert _ref_nav_labels(_DESIGN) == [
        "Home", "Shows", "Movies", "Games", "New & Popular", "My List",
        "Browse by Languages"]


def test_parses_paren_and_nav_links_forms():
    d1 = {"screens": [{"components": [
        {"id": "primary-nav-links", "role": "horizontal nav (Home, Shows, Movies)"}]}]}
    assert _ref_nav_labels(d1) == ["Home", "Shows", "Movies"]
    d2 = {"screens": [{"components": [
        {"id": "primary-nav-links", "role": "nav links: Feed, Explore, Profile"}]}]}
    assert _ref_nav_labels(d2) == ["Feed", "Explore", "Profile"]


def test_no_nav_component_returns_empty():
    assert _ref_nav_labels({"screens": [{"components": [
        {"id": "hero", "role": "billboard"}]}]}) == []
    assert _ref_nav_labels({}) == []


def test_assignment_resolves_browse_collision():
    got = dict((rt, lbl) for lbl, rt in _assign_ref_labels(_ROUTES, _DESIGN))
    # the 2-token /browse/languages claims 'Browse by Languages'...
    assert got["/browse/languages"] == "Browse by Languages"
    # ...so /browse (the home page) gets the leftover Home label, NOT a mislabel
    assert got["/browse"] == "Home"


def test_assignment_exact_and_token_matches():
    got = dict((rt, lbl) for lbl, rt in _assign_ref_labels(_ROUTES, _DESIGN))
    assert got["/shows"] == "Shows"
    assert got["/movies"] == "Movies"
    assert got["/games"] == "Games"
    assert got["/my-list"] == "My List"
    assert got["/new"] == "New & Popular"          # token 'new'


def test_href_never_changes_and_unmatched_kept():
    out = _assign_ref_labels(_ROUTES, _DESIGN)
    assert [rt for _l, rt in out] == [rt for _l, rt in _ROUTES], "routes/hrefs unchanged"
    got = dict((rt, lbl) for lbl, rt in out)
    assert got["/search"] == "Search"  # no ref label → segment label kept (no regression)


def test_no_design_labels_is_noop():
    assert _assign_ref_labels(_ROUTES, {}) == _ROUTES


def test_no_duplicate_labels_assigned():
    out = [lbl for lbl, _rt in _assign_ref_labels(_ROUTES, _DESIGN)]
    assert len(out) == len(set(out)), "each reference label used at most once"


def test_ref_nav_jsx_renders_reference_labels():
    out = _ref_nav_jsx(_ROUTES, "#e50914", vertical=False, design=_DESIGN)
    assert "New &amp; Popular" in out or "New & Popular" in out
    assert "Browse by Languages" in out
    assert 'href="/new"' in out and 'href="/browse/languages"' in out  # hrefs intact


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
