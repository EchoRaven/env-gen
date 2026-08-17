r"""#571 (netflix r134, live; r98 before it): `_design_screen_for_route`'s fuzzy pass SKIPPED
every non-page screen -- `if str(s.get("kind")) != "page": continue` -- while its own docstring
says "kind=='page' PREFERRED over overlays". A preference had been implemented as a hard filter.

Consequence: a detail route (`/title/:id`, reference screen `title_detail`, classified
kind=overlay) could never reach its own reference. The best remaining PAGE won on route tokens
alone -- `player` at `/watch/:titleId` shares {title, id} -- so both routes projected the SAME
component. r134 shipped `Player.jsx` and `TitleDetailModal.jsx` BYTE-IDENTICAL apart from the
function name and the param name (87 lines each, both `data-projected="ref"`, both a full-screen
video player with pause/rewind/volume/CC/fullscreen controls). The judge scored title_detail
**0.08** ("Reference is a title detail modal overlay ...; Implementation is a full-screen video
player"), holding the blocking average at 0.5533 against a 0.65 bar.

Unfixable by the lane -- both pages are framework-projected. #534 papers over it only when the
lane has authored its own detail-modal component, which r134's had not; r98 hit the same thing
at 0.06, 36 runs earlier.

Fix: rank instead of filter -- score, then NAME COVERAGE (what separates `title_detail` 2/2 from
`player` 0/1 on a tie), then the documented page preference as the final tie-break.
"""
import pytest

from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    _design_screen_for_route,
)


def _screen(name, route, kind="page"):
    return {"name": name, "route": route, "kind": kind,
            "components": [{"role": "region"}]}


# r134's reference set, in the shape the projector sees it.
_DESIGN = {"screens": [
    _screen("browse_home", "/browse"),
    _screen("player", "/watch/:titleId"),
    _screen("title_detail", "/title/:id", kind="overlay"),
    _screen("my_list", "/my-list"),
]}


def _hints_for(page_name, component):
    return (page_name, page_name, component, page_name)


def test_r134_detail_route_reaches_its_own_overlay_reference():
    got = _design_screen_for_route(
        _DESIGN, "/title/:id", hints=_hints_for("title_detail", "TitleDetailModal"))
    assert got is not None and got["name"] == "title_detail", got


def test_the_player_route_still_gets_the_player():
    got = _design_screen_for_route(
        _DESIGN, "/watch/:titleId", hints=_hints_for("player", "Player"))
    assert got is not None and got["name"] == "player", got


def test_two_routes_no_longer_collapse_to_one_reference():
    """The observable r134 defect: Player.jsx and TitleDetailModal.jsx byte-identical."""
    a = _design_screen_for_route(_DESIGN, "/title/:id",
                                 hints=_hints_for("title_detail", "TitleDetailModal"))
    b = _design_screen_for_route(_DESIGN, "/watch/:titleId",
                                 hints=_hints_for("player", "Player"))
    assert a and b and a["name"] != b["name"], (a, b)


def test_exact_route_match_still_wins_and_still_prefers_a_page():
    """Unchanged path: an exact route match short-circuits, page over overlay."""
    design = {"screens": [
        _screen("dup_overlay", "/browse", kind="overlay"),
        _screen("browse_home", "/browse"),
    ]}
    got = _design_screen_for_route(design, "/browse", hints=("browse_home",))
    assert got["name"] == "browse_home"


def test_page_still_wins_a_genuine_tie():
    """The documented preference survives as the final tie-break: same score, same name
    coverage → the page."""
    design = {"screens": [
        _screen("settings", "/settings", kind="overlay"),
        _screen("settings", "/settings-page"),
    ]}
    got = _design_screen_for_route(design, "/settings/panel", hints=("settings",))
    assert got is not None and got.get("kind", "page") == "page", got


def test_no_shared_token_still_returns_nothing():
    """A wrong graft is worse than the generic floor (#226) — unchanged."""
    assert _design_screen_for_route(_DESIGN, "/zzz-unrelated", hints=("zzz",)) is None


def test_screens_without_components_are_still_ignored():
    design = {"screens": [{"name": "title_detail", "route": "/title/:id",
                           "kind": "overlay", "components": []}]}
    assert _design_screen_for_route(design, "/title/:id", hints=("title_detail",)) is None


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
