"""#429 (netflix r25 title_detail=0.18, lowest screen): a DETAIL/OVERLAY screen
(design kind=overlay, route /title/:id) shipped as a full app-shell PAGE — nav +
45vh hero + a bogus 40%-wide right <aside> with ▲▼ prev/next — instead of the
reference's centered MODAL (scrim, close-X, Play/Add/Like actions, meta, description).
FIX: render detail/overlay screens (STRICT: param route AND detail/overlay name or
kind) as a scrim + centered card populated from the entity's own data, with NO
app-shell nav/aside. Detection is strict so non-param pages (browse/movies) are
never affected. Generalizable — any app's detail/overlay screen, no product
literals. Locks it in."""
from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    _render_reference_page)

_DESIGN = {
    "design_system": {"palette": {"bg": "#141414", "accent": "#e50914"},
                      "theme": {"default": "dark"}},
    "assets": [{"id": "b1", "file": "backdrops/b1.jpg", "type": "jpg",
                "dims": [1280, 720], "staged_path": "public/assets/backdrops/b1.jpg"}],
}

_DETAIL = {"route": "/title/:id", "name": "title_detail", "kind": "overlay",
           "components": [
               {"id": "hero", "region": [0.0, 0.0, 1.0, 0.5],
                "role": "title art backdrop", "assets": ["b1"]},
               {"id": "actions", "region": [0.05, 0.45, 0.6, 0.52],
                "role": "Play and Add buttons"}]}


def _detail():
    return _render_reference_page("TitleDetailPage", {"route": "/title/:id"},
                                  _DETAIL, _DESIGN, [("Home", "/browse")],
                                  "/api/titles/:id")


def test_detail_renders_modal_scrim_not_appshell_page():
    out = _detail()
    assert "fixed inset-0 z-50" in out, "detail screen must render a modal scrim"
    assert "max-w-3xl" in out, "centered modal card"
    # NOT the app-shell page structure
    assert "flex min-h-screen" not in out, "must not ship the full-page app shell"


def test_detail_modal_has_close_and_actions():
    out = _detail()
    assert 'aria-label="Close"' in out and "window.history.back()" in out
    assert "Play" in out and 'aria-label="Add to My List"' in out and 'aria-label="Like"' in out


def test_detail_modal_is_data_driven():
    out = _detail()
    assert "_titleOf(cur)" in out          # title from the entity
    # #783: via the accessor. 2 of 139 corpus content tables spell it rating_label/rating_age,
    # and the accessor must NOT fall back to `rating` — see test_projected_metadata_accessors_782.
    assert "_ratingOf(cur)" in out    # meta row from the entity's fields
    assert "_subOf(cur)" in out            # description from the entity


def test_detail_modal_no_bogus_aside_or_updown():
    out = _detail()
    # the wrong 40%-wide right aside + ▲▼ prev/next must be gone for detail screens
    assert "\\u25B2" not in out and "\\u25BC" not in out, "no ▲▼ side controls"
    assert "40.0%" not in out


# ── regression guard: non-detail pages must stay pages, NOT become modals ──
_HOME = {"route": "/browse", "name": "browse_home", "components": [
    {"id": "hero", "region": [0.0, 0.0, 1.0, 0.5], "role": "hero billboard",
     "assets": ["b1"]},
    {"id": "rail", "region": [0.0, 0.6, 1.0, 0.85], "role": "poster rail",
     "geometry": {"columns": 6}}]}
_MOVIES = {"route": "/movies", "name": "movies", "components": [
    {"id": "grid", "region": [0.0, 0.2, 1.0, 0.9], "role": "poster grid",
     "geometry": {"columns": 5}}]}


def test_home_page_not_a_modal():
    out = _render_reference_page("BrowseHomePage", {"route": "/browse"}, _HOME,
                                 _DESIGN, [("Home", "/browse")], "/api/titles")
    assert "fixed inset-0 z-50" not in out, "home (no param route) must stay a page"
    assert "flex min-h-screen" in out


def test_param_route_without_detail_name_not_modal():
    # a player-like param route whose name isn't a detail/overlay must NOT modal-ize
    scr = {"route": "/watch/:id", "name": "player", "components": [
        {"id": "vid", "region": [0, 0, 1, 1], "role": "full-screen video"}]}
    out = _render_reference_page("PlayerPage", {"route": "/watch/:id"}, scr,
                                 _DESIGN, [("Home", "/browse")], "")
    assert "fixed inset-0 z-50" not in out, "player is not a detail modal"


def test_movies_grid_not_a_modal():
    out = _render_reference_page("MoviesPage", {"route": "/movies"}, _MOVIES,
                                 _DESIGN, [("Movies", "/movies")], "/api/titles")
    assert "fixed inset-0 z-50" not in out


# ── #456: NARROW the modal trigger to screens whose reference is dominantly a centered
#    dialog/detail overlay. r39 showed the over-broad #447/#452 rule mis-rendered full
#    browse PAGES as bare modals (browse_home 0.08 via kind=overlay; card_hover_preview
#    0.15 via a 'preview'/'hover' name). A bare modal fires ONLY on (a) an ENTITY/PARAM
#    route + a detail/modal name (title_detail /title/:id), or (b) an explicit
#    'dialog'/'modal' name word (rate_dialog). Everything else is a page. ──
def test_param_route_detail_renders_modal():
    # title_detail: param route + 'detail' name → modal (scored 0.50 as a modal)
    scr = {"route": "/title/:id", "name": "title_detail", "kind": "page",
           "components": [{"id": "c", "region": [0.2, 0.1, 0.8, 0.9], "role": "detail panel"}]}
    out = _render_reference_page("TitleDetail", {"route": "/title/:id"}, scr, _DESIGN,
                                 [("Home", "/browse")], "/api/titles/:id")
    assert "fixed inset-0 z-50" in out, "param-route detail → modal"


def test_explicit_dialog_name_renders_modal():
    # rate_dialog: explicit 'dialog' name word → modal even on a nav route, no param
    scr = {"route": "/browse", "name": "rate_dialog", "kind": "overlay",
           "components": [{"id": "c", "region": [0.3, 0.3, 0.7, 0.7], "role": "rating dialog"}]}
    out = _render_reference_page("RateDialog", {"route": "/browse"}, scr, _DESIGN,
                                 [("Home", "/browse")], "/api/x")
    assert "fixed inset-0 z-50" in out, "'dialog' name → modal"


def test_browse_page_mislabeled_overlay_stays_page_456():
    # #456 regression (r39 browse_home 0.08): a browse PAGE mislabeled kind=overlay,
    # non-param route, no dialog/modal name → PAGE, NOT a bare modal — regardless of
    # whether its route matches the passed nav_routes (runtime-independent).
    for nm, rt in (("browse_home", "/browse"), ("shows_genres_menu", "/shows")):
        scr = {"route": rt, "name": nm, "kind": "overlay", "components": [
            {"id": "hero", "region": [0.0, 0.05, 1.0, 0.6], "role": "hero billboard"},
            {"id": "rail", "region": [0.0, 0.65, 1.0, 0.85], "role": "poster rail"}]}
        # pass nav_routes that do NOT contain the screen's route (the r39 runtime mismatch)
        out = _render_reference_page(nm, {"route": rt}, scr, _DESIGN,
                                     [("X", "/somewhere-else")], "/api/titles")
        assert "fixed inset-0 z-50" not in out, f"{nm} (overlay page) must stay a page"
        assert "flex min-h-screen" in out


def test_preview_hover_name_page_not_modal_456():
    # #456 regression (r39 card_hover_preview 0.15): a browse-page-WITH-a-hover-popover
    # (weak 'preview'/'hover'/'card' name token, non-param route, no dialog/modal word)
    # must render as a PAGE (its browse layout), not a bare centered modal.
    for nm in ("card_hover_preview", "card_preview", "hover_card"):
        scr = {"route": "/browse", "name": nm, "kind": "page", "components": [
            {"id": "hero", "region": [0.0, 0.05, 1.0, 0.3], "role": "hero backdrop"},
            {"id": "rail", "region": [0.0, 0.35, 1.0, 0.6], "role": "carousel of tiles"}]}
        out = _render_reference_page(nm, {"route": "/browse"}, scr, _DESIGN,
                                     [("Home", "/browse")], "/api/x")
        assert "fixed inset-0 z-50" not in out, f"{nm} (page-with-overlay) must stay a page"


def test_page_kind_screens_never_modal_regression():
    # browse/movies/games/player pages must NEVER become modals (no false-positive)
    for nm, rt in (("browse_home", "/browse"), ("games", "/browse/games"),
                   ("player", "/watch/:id")):
        scr = {"route": rt, "name": nm, "kind": "page", "components": [
            {"id": "h", "region": [0.0, 0.05, 1.0, 0.6], "role": "hero billboard"}]}
        out = _render_reference_page(nm, {"route": rt}, scr, _DESIGN,
                                     [("X", rt)], "/api/titles")
        assert "fixed inset-0 z-50" not in out, f"{nm} (page) must NOT be a modal"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
