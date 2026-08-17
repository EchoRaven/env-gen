"""#385: the visual-fidelity gate capped judged screens at max_screens=8, but
visual_gate_verdict FAILS any OWNED (page) screen left unjudged. So any app with
>8 page screens (netflix r10: 13) permanently blocks — 5+ owned screens 'never
judged', unfixable by the frontend lane (13 deferrals stuck on attempt 1/3).
_select_judged_screens now judges EVERY blocking screen; the cap only trims
ADVISORY (overlay/state) overflow.

Isolation harness: visual_fidelity's only sibling import is
`from .validation_runner import _service_host_port` — stub it, then exec the
module source under a synthetic package (importing by package path would pull the
whole engine graph)."""
import sys
import types
import importlib.util
from pathlib import Path

_SRC = (Path(__file__).resolve().parents[1] / "env_generator" / "llm_generator"
        / "multi_agent" / "runtime" / "visual_fidelity.py")


def _load():
    pkg = types.ModuleType("vf_pkg")
    pkg.__path__ = []
    vr = types.ModuleType("vf_pkg.validation_runner")
    vr._service_host_port = lambda *a, **k: None
    sys.modules["vf_pkg"] = pkg
    sys.modules["vf_pkg.validation_runner"] = vr
    # #898: `visual_fidelity` derives its ceilings via `stage_contract.llm_ceiling_898`, imported
    # inside the accessor. This harness hand-stubs each module the source reaches, so a new one
    # must be added here too — the same contract `validation_runner` above is satisfying.
    import env_generator.llm_generator.multi_agent.runtime.stage_contract as _sc
    sys.modules["vf_pkg.stage_contract"] = _sc
    mod = types.ModuleType("vf_pkg.visual_fidelity")
    mod.__package__ = "vf_pkg"
    exec(compile(_SRC.read_text(encoding="utf-8"), str(_SRC), "exec"), mod.__dict__)
    return mod


VF = _load()


def _mk(name, route, advisory=False):
    return {"name": name, "path": f"/x/{name}.png", "route": route, "auth": True,
            "advisory": advisory}


def test_all_blocking_judged_when_over_cap():
    # 13 blocking + 7 advisory, cap 8 -> ALL 13 blocking judged, 0 advisory
    blk = [_mk(f"page{i}", f"/p{i}") for i in range(13)]
    adv = [_mk(f"ov{i}", f"/o{i}", advisory=True) for i in range(7)]
    got = VF._select_judged_screens(blk + adv, max_screens=8)
    names = {s["name"] for s in got}
    assert all(s["name"] in names for s in blk), "a blocking screen was dropped by the cap"
    assert len([s for s in got if not s["advisory"]]) == 13
    assert len([s for s in got if s["advisory"]]) == 0  # cap fully spent on blocking


def test_advisory_fills_remaining_cap_budget():
    # 3 blocking + 10 advisory, cap 8 -> 3 blocking + 5 advisory = 8
    blk = [_mk(f"page{i}", f"/p{i}") for i in range(3)]
    adv = [_mk(f"ov{i}", f"/o{i}", advisory=True) for i in range(10)]
    got = VF._select_judged_screens(blk + adv, max_screens=8)
    assert len([s for s in got if not s["advisory"]]) == 3
    assert len([s for s in got if s["advisory"]]) == 5


def test_unrouted_screens_never_selected():
    screens = [_mk("a", "/a"), _mk("b", None), _mk("c", "/c", advisory=True), _mk("d", None, advisory=True)]
    got = {s["name"] for s in VF._select_judged_screens(screens, max_screens=8)}
    assert got == {"a", "c"}


def test_netflix_owned_pages_all_judged_end_to_end(tmp_path):
    """The real r10 scenario: 20 reference screens + the generated App.jsx routes ->
    every OWNED page (incl login, movies, my_list, new_and_popular) is judged."""
    routes = {"/", "/browse", "/browse/genre/:genreId", "/browse/languages", "/games",
              "/login", "/movies", "/my-list", "/new", "/profiles", "/shows",
              "/signup", "/title/:id", "/watch/:titleId"}
    screen_names = ["account_menu", "browse_by_languages", "browse_home",
                    "browse_home_rows", "card_hover_preview", "card_preview", "games",
                    "genre_category", "landing", "login", "movies", "my_list",
                    "new_and_popular", "player_controls", "player", "rate_dialog",
                    "shows_genres_menu", "shows", "title_detail"]
    refs = []
    for n in screen_names:
        f = tmp_path / f"{n}.png"
        f.write_bytes(b"\x89PNG\r\n")
        refs.append(str(f))
    screens = VF.map_reference_screens(refs, routes)
    judged = VF._select_judged_screens(screens, max_screens=8)
    judged_names = {s["name"] for s in judged}
    # these 4 previously showed up as 'never judged' despite clean routes -> must be judged now
    for owned in ("login", "movies", "my_list", "new_and_popular"):
        assert owned in judged_names, f"{owned} still not judged"
    # every routed non-advisory (page) screen must be judged (no owned screen dropped)
    routed_pages = {s["name"] for s in screens if s.get("route") and not s.get("advisory")}
    assert routed_pages <= judged_names, f"owned dropped: {routed_pages - judged_names}"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
