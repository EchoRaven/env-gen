r"""#747: the lane declares which reference a page matches, 1182 times, and the gate guessed.

`map_reference_screens` links a measured design screen to an app route. Its most authoritative
layer, #416, INFERS that link from token overlap between the screen name and a registered
ui_page's name/component — because it assumed nothing states it outright.

Something does. The lane writes `metadata.reference_image` on the page it just built. Measured
over the 148-run corpus:

    ui_page records carrying metadata.reference_image                1182
    ... naming a file that exists in that run's design/references/   1119   (94.7%)
    distinct values                                                    54

`load_ui_pages` projected each record to `{name, route, component}` and **dropped `metadata` at
the door**, so none of it ever reached the mapper. The 63 that do not resolve are almost entirely
an extension mismatch (`landing.png` declared, `landing.jpg` staged), which is why the match here
is on the STEM — a declaration that is right about WHICH screen should not be thrown away over a
file suffix.

This is the user's own proposal — let the frontend agent that implements a page transmit which
reference it corresponds to — and the data has been arriving all along.

The two existing exclusions are preserved exactly: an overlay name (#128) or a transient
interaction-state name (#542a) is never given a page route, declaration or not. A declaration
must not be able to promote a dropdown into a blocking screen.
"""
import inspect
import json
import re

import pytest

from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf


def _refs(tmp_path, *names):
    out = []
    d = tmp_path / "design" / "references"
    d.mkdir(parents=True, exist_ok=True)
    for n in names:
        p = d / n
        p.write_bytes(b"\x89PNG\r\n\x1a\n")
        out.append(str(p))
    return out


def _page(name, route, component=None, reference_image=None):
    return {"name": name, "route": route, "component": component or (name + "_page"),
            "reference_image": reference_image}


def _map(tmp_path, refs, pages, known):
    return vf.map_reference_screens(refs, known_routes=set(known), ui_pages=pages)


def _route_of(screens, name):
    for s in screens:
        if s["name"] == name:
            return s.get("route")
    return "<absent>"


# --- load_ui_pages keeps the field ------------------------------------------------------------

def test_load_ui_pages_carries_the_declared_reference(tmp_path):
    hubs = tmp_path / "shared" / "hubs"
    hubs.mkdir(parents=True)
    (hubs / "registryhub_ui_pages.json").write_text(json.dumps({
        "p1": {"name": "browse_home", "route": "/browse", "component": "BrowseHomePage",
               "metadata": {"reference_image": "browse_home.jpg"}},
    }), encoding="utf-8")
    got = vf.load_ui_pages(tmp_path)
    assert got and got[0]["reference_image"] == "browse_home.jpg"


def test_a_page_without_metadata_is_unharmed(tmp_path):
    hubs = tmp_path / "shared" / "hubs"
    hubs.mkdir(parents=True)
    (hubs / "registryhub_ui_pages.json").write_text(json.dumps({
        "p1": {"name": "x", "route": "/x", "component": "XPage"},
        "p2": {"name": "y", "route": "/y", "component": "YPage", "metadata": "not-a-dict"},
    }), encoding="utf-8")
    got = vf.load_ui_pages(tmp_path)
    assert {g["reference_image"] for g in got} == {None}
    assert {g["route"] for g in got} == {"/x", "/y"}


# --- the declaration decides ---------------------------------------------------------------------

def test_a_declaration_beats_the_token_guess(tmp_path):
    """The two disagree on purpose: token overlap would bind `movies` to the page NAMED
    movies; the declaration says the movies reference belongs to /browse/films."""
    refs = _refs(tmp_path, "movies.jpg")
    pages = [_page("movies", "/movies"),
             _page("films", "/browse/films", reference_image="movies.jpg")]
    got = _map(tmp_path, refs, pages, ["/movies", "/browse/films"])
    assert _route_of(got, "movies") == "/browse/films"


def test_an_extension_mismatch_still_matches(tmp_path):
    """63 of the 1182 declarations miss only on the suffix."""
    refs = _refs(tmp_path, "landing.jpg")
    pages = [_page("other", "/somewhere-else", reference_image="landing.png")]
    got = _map(tmp_path, refs, pages, ["/somewhere-else"])
    assert _route_of(got, "landing") == "/somewhere-else"


def test_a_declared_path_is_matched_on_its_basename(tmp_path):
    refs = _refs(tmp_path, "player.jpg")
    pages = [_page("watch", "/watch", reference_image="design/references/player.jpg")]
    got = _map(tmp_path, refs, pages, ["/watch"])
    assert _route_of(got, "player") == "/watch"


# --- what a declaration must NOT be able to do -------------------------------------------------

def _advisory_of(screens, name):
    for s in screens:
        if s["name"] == name:
            return s.get("advisory")
    return "<absent>"


def test_a_declaration_cannot_promote_an_overlay(tmp_path):
    """#128 owns *_menu / *_dropdown. A declaration must not turn one into a blocking page.

    Asserted on ADVISORY, not on the route. My first version checked `route != "/account"` and
    failed — the screen does get a route, from the generic filename→route fallback that has
    always been there. The exclusion #128/#542a own is about never inheriting a PAGE link and
    never being PROMOTED to blocking; it was never about having no route at all."""
    refs = _refs(tmp_path, "account_menu.jpg")
    pages = [_page("account", "/account", reference_image="account_menu.jpg")]
    got = _map(tmp_path, refs, pages, ["/account"])
    assert _advisory_of(got, "account_menu") is True


def test_a_declaration_cannot_promote_a_transient_state(tmp_path):
    """#542a: a hover/preview state a static capture can never reproduce."""
    refs = _refs(tmp_path, "card_hover_preview.jpg")
    pages = [_page("card", "/card", reference_image="card_hover_preview.jpg")]
    got = _map(tmp_path, refs, pages, ["/card"])
    assert _advisory_of(got, "card_hover_preview") is True


def test_a_declared_ordinary_screen_is_NOT_advisory(tmp_path):
    """Non-vacuity for the two above: advisory must not be True for everything."""
    refs = _refs(tmp_path, "movies.jpg")
    pages = [_page("films", "/browse/films", reference_image="movies.jpg")]
    got = _map(tmp_path, refs, pages, ["/browse/films"])
    assert _advisory_of(got, "movies") is not True


def test_a_declared_route_the_app_does_not_serve_is_ignored(tmp_path):
    """The #416 rule that a suggestion never navigates to a 404 must still hold."""
    refs = _refs(tmp_path, "games.jpg")
    pages = [_page("games", "/not-served", reference_image="games.jpg")]
    got = _map(tmp_path, refs, pages, ["/games"])
    assert _route_of(got, "games") != "/not-served"


def test_an_empty_declaration_is_not_a_match(tmp_path):
    refs = _refs(tmp_path, "shows.jpg")
    pages = [_page("shows", "/shows", reference_image="")]
    got = _map(tmp_path, refs, pages, ["/shows"])
    assert _route_of(got, "shows") == "/shows", "falls through to #416, unchanged"


# --- #416 is untouched when nothing is declared ---------------------------------------------------

def test_the_416_path_still_works(tmp_path):
    refs = _refs(tmp_path, "browse_home.jpg")
    pages = [_page("browse_home", "/browse", component="BrowseHomePage")]
    got = _map(tmp_path, refs, pages, ["/browse"])
    assert _route_of(got, "browse_home") == "/browse"


def test_a_declaration_for_a_DIFFERENT_screen_does_not_leak(tmp_path):
    refs = _refs(tmp_path, "shows.jpg")
    pages = [_page("movies", "/movies", reference_image="movies.jpg"),
             _page("shows", "/shows", component="ShowsPage")]
    got = _map(tmp_path, refs, pages, ["/movies", "/shows"])
    assert _route_of(got, "shows") == "/shows"


def test_no_pages_at_all_is_a_no_op(tmp_path):
    refs = _refs(tmp_path, "login.jpg")
    assert vf.map_reference_screens(refs, known_routes={"/login"}, ui_pages=None)


# --- provenance -------------------------------------------------------------------------------------

def _prov(fn) -> str:
    src = inspect.getsource(fn)
    return " ".join(l.strip().lstrip("#").strip() for l in src.split("\n"))


def test_the_corpus_measurement_is_recorded():
    p = _prov(vf.load_ui_pages)
    assert "**1182** ui_page records carry it" in p
    assert "1119 of them (94.7%)" in p


def test_it_records_that_the_field_was_dropped_at_the_door():
    p = _prov(vf.load_ui_pages)
    assert "dropped `metadata`" in p or "This projection dropped `metadata`" in p


def test_it_records_whose_idea_this_was():
    p = _prov(vf.map_reference_screens)
    assert "the user's own proposal" in p
    assert "the data to honour it has been arriving all along" in p


def test_it_records_why_the_stem_and_not_the_filename():
    p = _prov(vf.map_reference_screens)
    assert "extension mismatch" in p
    assert "should not be discarded over a file suffix" in p


def test_the_exclusions_are_recorded_as_deliberate():
    p = _prov(vf.map_reference_screens)
    assert "must not be able to promote a dropdown into a blocking screen" in p


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))


# --- #758: the declaration is no longer silent --------------------------------------------------

def test_a_disagreement_is_a_WARNING(tmp_path, caplog):
    """The case item 67 could not answer: the declaration and the guess pick different pages.
    Every earlier run took the guess and no artifact said so."""
    import logging
    refs = _refs(tmp_path, "movies.jpg")
    pages = [_page("movies", "/movies"),
             _page("films", "/browse/films", reference_image="movies.jpg")]
    with caplog.at_level(logging.WARNING, logger=vf.__name__):
        _map(tmp_path, refs, pages, ["/movies", "/browse/films"])
    msg = " ".join(r.getMessage() for r in caplog.records)
    assert "#758 declared reference OVERRULES the name guess" in msg
    assert "/browse/films" in msg and "/movies" in msg


def test_an_agreeing_declaration_is_only_INFO(tmp_path, caplog):
    """A declaration that matches the guess is provenance, not news."""
    import logging
    refs = _refs(tmp_path, "browse_home.jpg")
    pages = [_page("browse_home", "/browse", reference_image="browse_home.jpg")]
    with caplog.at_level(logging.INFO, logger=vf.__name__):
        _map(tmp_path, refs, pages, ["/browse"])
    recs = [r for r in caplog.records if "#758" in r.getMessage()]
    assert recs and all(r.levelno == logging.INFO for r in recs), [r.levelname for r in recs]


def test_no_declaration_logs_nothing(tmp_path, caplog):
    import logging
    refs = _refs(tmp_path, "shows.jpg")
    with caplog.at_level(logging.INFO, logger=vf.__name__):
        _map(tmp_path, refs, [_page("shows", "/shows")], ["/shows"])
    assert not [r for r in caplog.records if "#758" in r.getMessage()]


def test_the_guess_is_still_computed_for_the_fallback(tmp_path):
    """#758 must not have turned the guess off — it is still the path when nothing is declared."""
    refs = _refs(tmp_path, "browse_home.jpg")
    got = _map(tmp_path, refs, [_page("browse_home", "/browse")], ["/browse"])
    assert _route_of(got, "browse_home") == "/browse"


def test_it_records_why_the_silence_mattered():
    import inspect
    src = inspect.getsource(vf.map_reference_screens)
    i = src.index("#758: SAY WHEN THE DECLARATION DECIDED")
    blk = " ".join(l.strip().lstrip("#").strip()
                   for l in src[i:src.index("_matched_page = _declared_page", i)].split("\n"))
    assert "r149 — which carried 15 declarations" in blk
    assert "An improvement nobody can see fired" in blk
