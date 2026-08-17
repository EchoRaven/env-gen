r"""#902/#903: a page with NO route was projected against the LANDING screen.

Found by pulling on one r153 deviation — *"Row titles all say 'Browse by Languages' instead of
category"* — and refusing to stop at the first plausible cause. Three readings were wrong before
this one, and each is worth keeping because each looked finished:

| reading | why it died |
|---|---|
| the row titles are mislabelled | the delivered `LanguagesPage.jsx` has **no rows at all** — a flat grid |
| rule S (#545) forces selector-named screens to grid | `#551` already exempts a selector name carrying >=2 measured rails |
| `_is_rail_comp` under-counts the design's phrasing | it counts **4**, and `_wants_rows_539` answers **"rows"** |

So the archetype logic was right and was being asked about **the wrong screen**.

`scaffold_pages_from_contract` reads its pages from `registryhub.list_ui_pages()`, where **9 of
r153's 20 records carry `route: ""`**. It derives the canonical route for React-Router (that is
#387, this file's direct ancestor) — and then hands `_design_screen_for_route` the record's own
empty route. `_norm_route_221("")` returns `"/"`, so the lookup asks for the **site root** and
exact-matches `landing`, which wins outright:

    page                 registry route   design screen resolved      should be
    browse_home_page     ''               landing                     browse_home
    genre_category_page  ''               landing                     genre_category
    languages_page       ''               landing                     browse_by_languages
    login_page           ''               landing                     login
    my_list_page         ''               landing                     my_list
    player_page          ''               landing                     player
    profiles_page        ''               landing                     (no match)

**7 of the 12 routed pages projected against the wrong reference.** `languages_page` is the one
that surfaced: landing's archetype is a flat grid, so the four content shelves `browse_by_languages`
measured never had a chance to render.

★ The guard that should have caught this **could not fire**: `_norm_route_221` has no falsy
output, so `if not want: return None` is unreachable. A blank route and the root are the same
value by the time anyone can check — the "empty means clean vs empty means nothing" discriminator
(`stage_contract`'s own docstring) landing in the projector. And `landing` is the worst possible
default to collapse onto: it is the one screen every app has, so the miss always finds a
plausible-looking victim instead of returning nothing.

#902 makes blank mean *no route signal* (fall through to the hints-driven fuzzy phase, which is
honest about a miss); #903 hands the wired route down so the exact phase can still work — without
it `my_list_page` degrades from wrong-but-confident to no-match.
"""
import re
import tempfile
from pathlib import Path

import pytest

from env_generator.llm_generator.multi_agent.runtime import frontend_scaffold as fs
from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    _design_screen_for_route, scaffold_pages_from_contract)


def _design():
    """Two screens, the shape that made this invisible: a landing at the root and a real page
    whose route the blank record cannot express."""
    return {"screens": [
        {"name": "landing", "route": "/", "kind": "page",
         "components": [{"id": "hero", "role": "hero banner with email capture"},
                        {"id": "cta", "role": "sign in call to action"}]},
        {"name": "browse_by_languages", "route": "/browse/languages", "kind": "page",
         # the ids matter: `_is_rail_comp` reads them, and r153's real rails are named
         # `row1-carousel`/`row2-carousel`. A fixture carrying only the prose `role` looks
         # identical to a reader and counts ZERO rails — which is how this fixture was wrong
         # the first time.
         "components": [{"id": "row1-carousel", "role": "first content row of 5 title cards"},
                        {"id": "row2-carousel", "role": "second content row of 5 title cards"},
                        {"id": "lang-dropdown", "role": "language dropdown selector"}]},
    ]}


# --------------------------------------------------------------------------- #902

def test_the_normaliser_still_turns_blank_into_the_root():
    """Non-vacuity, and the mechanism itself. If this ever stops being true the bug is gone by
    other means and this ticket should be re-read rather than trusted."""
    assert fs._norm_route_221("") == "/"
    assert fs._norm_route_221(None) == "/"


def test_a_blank_route_does_not_resolve_to_the_landing_screen():
    """The defect, stated as behaviour: hints that name a different screen must beat a route
    that says nothing."""
    got = _design_screen_for_route(_design(), "", hints=("languages_page", "LanguagesPage"))
    assert (got or {}).get("name") != "landing"


def test_a_blank_route_resolves_via_the_hints():
    got = _design_screen_for_route(_design(), "", hints=("languages_page", "LanguagesPage"))
    assert (got or {}).get("name") == "browse_by_languages"


def test_an_explicit_root_route_still_matches_landing():
    """★ Non-regression, and the reason blank could not simply be rejected: `/` is a REAL route
    that a real page really has. The fix has to separate 'no route' from 'the root', not treat
    both as absent."""
    got = _design_screen_for_route(_design(), "/", hints=("landing_page", "LandingPage"))
    assert (got or {}).get("name") == "landing"


def test_a_blank_route_with_useless_hints_returns_nothing():
    """★ The honest miss. `_design_screen_for_route`'s own docstring says *"no shared token → no
    match (a wrong graft is worse than the generic floor)"* — that rule was being violated for
    every blank-route page, silently, in landing's favour."""
    assert _design_screen_for_route(_design(), "", hints=("zzz_unrelated", "Zzz")) is None


def test_a_real_route_is_unaffected():
    got = _design_screen_for_route(_design(), "/browse/languages", hints=("languages_page",))
    assert (got or {}).get("name") == "browse_by_languages"


def test_the_archetype_follows_the_corrected_screen():
    """★ The end of the chain the deviation pointed at: with the right screen, `_wants_rows_539`
    already answers 'rows' — #551 was never broken."""
    scr = _design_screen_for_route(_design(), "", hints=("languages_page", "LanguagesPage"))
    assert fs._wants_rows_539(scr) == "rows"


# --------------------------------------------------------------------------- #903

def _wire_and_capture(ui_pages):
    """Drive the real scaffolder and record every route `_design_screen_for_route` is asked
    about. Patching the lookup (rather than reading source) is what makes this a test of the
    WIRING: it fails if the derived route stops reaching the call, whatever the call looks like."""
    seen = []
    orig = fs._design_screen_for_route
    orig_load = fs._load_design_for_projection

    def _spy(design, route, hints=()):
        seen.append(route)
        return orig(design, route, hints=hints)

    fe = Path(tempfile.mkdtemp()) / "app" / "frontend"
    (fe / "src" / "pages").mkdir(parents=True, exist_ok=True)
    # the lookup is reached only under `if design and ...`; a tmp tree has no design file, so
    # without this the spy records NOTHING and every assertion below passes vacuously on []
    # — which is exactly what the first version of this test did.
    fs._design_screen_for_route = _spy
    fs._load_design_for_projection = lambda _fd: _design()
    try:
        scaffold_pages_from_contract(fe, ui_pages)
    finally:
        fs._design_screen_for_route = orig
        fs._load_design_for_projection = orig_load
    app = fe / "src" / "App.jsx"
    text = app.read_text(encoding="utf-8") if app.exists() else ""
    assert seen, "the design lookup was never reached — every assertion on `seen` would be vacuous"
    return seen, set(re.findall(r'<Route\s+path=["\']([^"\']+)["\']', text))


def test_the_wired_route_reaches_the_design_lookup():
    """★ The 'writer with no reader' half. The canonical route is derived two lines above the
    lookup and was not used by it."""
    seen, routes = _wire_and_capture([
        {"name": "browse_home", "route": "/browse", "component": "BrowseHomePage",
         "apis_used": ["GET /api/titles"]},
        {"name": "my_list_page", "route": "", "component": "", "apis_used": ["GET /api/my-list"]},
    ])
    assert "/my-list" in routes, "#387's derivation must still work"
    assert "" not in seen, seen
    assert "/my-list" in seen, seen


def test_the_hub_record_is_not_mutated():
    """The route is carried on a COPY. Writing it back would edit the registry's own dict through
    a list the scaffolder does not own — a side effect no caller of a scaffolder expects."""
    rec = {"name": "my_list_page", "route": "", "component": "", "apis_used": []}
    _wire_and_capture([
        {"name": "anchor", "route": "/x", "component": "Anchor", "apis_used": []}, rec])
    assert rec["route"] == ""


def test_a_declared_route_is_never_overwritten():
    seen, _ = _wire_and_capture([
        {"name": "games_page", "route": "/games", "component": "GamesPage", "apis_used": []},
    ])
    assert "/games" in seen and all(s != "" for s in seen), seen


# --------------------------------------------------------------------------- #904

def _blank_route_page():
    return [{"name": "landing_page", "route": "", "component": "LandingPage", "apis_used": []}]


def test_a_blank_route_does_not_mark_the_root_covered():
    """The third site of the same root: `missing_design_screen_pages` builds its covered-route
    set through the same normaliser, so ONE page with no route made the measured landing screen
    look already-served and it was never synthesized."""
    got = fs.missing_design_screen_pages(_design(), [{"name": "x", "route": "", "apis_used": []}], [])
    assert any(str(p.get("route")) == "/" for p in got), [p.get("route") for p in got]


def test_it_does_not_synthesize_a_duplicate_page():
    """★ The reason the obvious one-line version of #904 is not the whole story. If a REAL page
    for the root is registered with a blank route, dropping it from `covered` must not produce a
    second one — #226's name-token pass is what prevents that, and this test is the only thing
    that says so.

    ★ Recorded because the first attempt to measure this LIED: it simulated the change by
    deleting the page from `ui_pages` entirely, which also emptied `page_token_sets`, and
    'proved' a duplicate that the real change does not create."""
    got = fs.missing_design_screen_pages(_design(), _blank_route_page(), [])
    assert not any(str(p.get("route")) == "/" for p in got), [p.get("route") for p in got]
    assert [p.get("route") for p in got] == ["/browse/languages"], "the OTHER screen still is"


def test_a_declared_root_page_still_covers_the_root():
    """Non-regression: an explicit `/` page must keep suppressing the synthesis."""
    got = fs.missing_design_screen_pages(
        _design(), [{"name": "home", "route": "/", "apis_used": []}], [])
    assert not any(str(p.get("route")) == "/" for p in got)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
