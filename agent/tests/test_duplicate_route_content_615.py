r"""#615: N nav destinations, one unfiltered collection.

The generic form of "click Games, see Movies" — and it needs no product vocabulary. Distinct
routes whose DELIVERED page components fetch an identical, unparameterised endpoint set render
identical content; the finding is simply "these k routes are the same page".

Measured over the arc: **32 of 45** runs have at least one such group in the delivered code (not
merely in the declared `apis_used`). r100 is the worst — SIX routes, each fetching only
`/api/titles` with no filter:

    /browse  /browse/languages  /games  /movies  /new  /shows

Deliberately NOT wired as a delivery blocker. At 32/45 it would wedge nearly every run, and
whether "six identical pages" should block or merely be reported is a CALIBRATION decision, not
a measurement — the same class as the 0.65 fidelity bar. Also worth knowing before anyone
"fixes" it by inventing route-derived filters: the seed gives every title `kind='standard'`, so
such a filter would return everything or nothing.
"""
import pytest

from env_generator.llm_generator.multi_agent.runtime.frontend_audit import (
    duplicate_route_content_groups as groups,
)


def _tree(tmp_path, files):
    d = tmp_path / "src" / "pages"
    d.mkdir(parents=True, exist_ok=True)
    for name, body in files.items():
        (d / f"{name}.jsx").write_text(body, encoding="utf-8")
    return tmp_path


def _page(route, comp):
    return {"route": route, "component": comp}


# --- the real r100 shape ------------------------------------------------------------------

def test_six_routes_on_one_unfiltered_collection_are_reported(tmp_path):
    fe = _tree(tmp_path, {c: "fetch('/api/titles')" for c in
                          ("BrowseHomePage", "GamesPage", "MoviesPage", "ShowsPage")})
    ui = {c: _page(r, c) for r, c in (("/browse", "BrowseHomePage"), ("/games", "GamesPage"),
                                      ("/movies", "MoviesPage"), ("/shows", "ShowsPage"))}
    g = groups(fe, ui)
    assert len(g) == 1
    assert g[0]["routes"] == ["/browse", "/games", "/movies", "/shows"]
    assert g[0]["endpoints"] == ["/api/titles"]


def test_the_largest_group_comes_first(tmp_path):
    fe = _tree(tmp_path, {"A": "fetch('/api/titles')", "B": "fetch('/api/titles')",
                          "C": "fetch('/api/titles')",
                          "D": "fetch('/api/my-list')", "E": "fetch('/api/my-list')"})
    ui = {c: _page(f"/{c.lower()}", c) for c in "ABCDE"}
    g = groups(fe, ui)
    assert [len(x["routes"]) for x in g] == [3, 2]


# --- what must NOT be reported ---------------------------------------------------------------

def test_pages_that_fetch_different_things_are_not_a_group(tmp_path):
    fe = _tree(tmp_path, {"A": "fetch('/api/titles')", "B": "fetch('/api/genres')"})
    assert groups(fe, {c: _page(f"/{c}", c) for c in "AB"}) == []


def test_a_PARAMETERISED_fetch_differentiates_the_page(tmp_path):
    """`/api/titles/{id}` is per-item — those pages are not the same page."""
    fe = _tree(tmp_path, {"A": "fetch(`/api/titles/{id}`)", "B": "fetch(`/api/titles/{id}`)"})
    assert groups(fe, {c: _page(f"/{c}", c) for c in "AB"}) == []


def test_a_QUERY_differentiates_the_page(tmp_path):
    fe = _tree(tmp_path, {"A": "fetch('/api/titles?kind=movie')",
                          "B": "fetch('/api/titles?kind=show')"})
    assert groups(fe, {c: _page(f"/{c}", c) for c in "AB"}) == []


def test_one_route_alone_is_never_a_group(tmp_path):
    fe = _tree(tmp_path, {"A": "fetch('/api/titles')"})
    assert groups(fe, {"A": _page("/a", "A")}) == []


def test_the_SAME_route_declared_twice_is_not_a_group(tmp_path):
    """#593's duplicate records must not masquerade as duplicate CONTENT."""
    fe = _tree(tmp_path, {"A": "fetch('/api/titles')", "B": "fetch('/api/titles')"})
    ui = {"a": _page("/x", "A"), "b": _page("/x", "B")}
    assert groups(fe, ui) == []


def test_a_page_that_fetches_nothing_is_ignored(tmp_path):
    fe = _tree(tmp_path, {"A": "export default function A(){return null}",
                          "B": "export default function B(){return null}"})
    assert groups(fe, {c: _page(f"/{c}", c) for c in "AB"}) == []


# --- robustness ---------------------------------------------------------------------------------

def test_a_missing_component_file_is_skipped(tmp_path):
    fe = _tree(tmp_path, {"A": "fetch('/api/titles')"})
    ui = {"a": _page("/a", "A"), "b": _page("/b", "Nope")}
    assert groups(fe, ui) == []


def test_junk_inputs_return_an_empty_list(tmp_path):
    assert groups(tmp_path, None) == []
    assert groups(tmp_path, {}) == []
    assert groups("/nonexistent", {"a": _page("/a", "A")}) == []
    fe = _tree(tmp_path, {"A": "fetch('/api/titles')"})
    assert groups(fe, [None, "x", {}]) == []


def test_a_LIST_of_pages_is_accepted_too(tmp_path):
    fe = _tree(tmp_path, {"A": "fetch('/api/titles')", "B": "fetch('/api/titles')"})
    g = groups(fe, [_page("/a", "A"), _page("/b", "B")])
    assert g and g[0]["routes"] == ["/a", "/b"]


def test_it_is_not_wired_as_a_delivery_blocker():
    """32/45 runs would wedge; whether this blocks is a calibration call, not a measurement."""
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import frontend_audit as fa
    assert "duplicate_route_content_groups" not in inspect.getsource(fa.ui_page_delivery_blockers)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
