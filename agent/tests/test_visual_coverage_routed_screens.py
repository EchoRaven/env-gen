"""#416: the visual gate judged only measured screens the design-prep analyst
labeled kind=='page'. On netflix-web-r13 the analyst mislabeled the SHOWCASE
screens browse_home and title_detail as kind=='overlay' even though the app
registered dedicated routed pages for them (browse_home_page/BrowseHomePage @
/browse; title_detail_page/TitleDetailPage @ /title/:id). Advisory screens only
fill the leftover cap budget, and with 12 blocking pages vs max_screens=8 that
budget was 0 -> the two real hero pages were dropped from the exam entirely
(12/20 judged), so the fidelity metric never saw them and the projector's
enrichments went unscored.

The fix links each measured design screen to the app's OWN registered ui_page by
the #226 name-token vocabulary (design_screen<->ui_page<->route). A STRONG match
(name/component tokens equal) means the app built a dedicated routed page for the
screen: the gate uses that page's ACTUAL served route (authoritative — handles
/title/:id) and judges it as a blocking page, overriding the overlay mislabel.
Structural overlays (*_menu / *_dropdown) and screens with no dedicated page stay
advisory (#128), and a route the app does not serve stays skipped (never a 404).

Isolation harness mirrors tests/test_visual_fidelity_coverage.py: visual_fidelity's
only sibling import is `from .validation_runner import _service_host_port` — stub
it, then exec the module source under a synthetic package."""
import sys
import types
import json
from pathlib import Path

_SRC = (Path(__file__).resolve().parents[1] / "env_generator" / "llm_generator"
        / "multi_agent" / "runtime" / "visual_fidelity.py")


def _load():
    pkg = types.ModuleType("vf_pkg")
    pkg.__path__ = []
    vr = types.ModuleType("vf_pkg.validation_runner")
    vr._service_host_port = lambda *a, **k: None
    sys.modules["vf_pkg"] = pkg
    import env_generator.llm_generator.multi_agent.runtime.message_format as _mf1034
    sys.modules["vf_pkg.message_format"] = _mf1034  # #1034: leaf helper, no deps
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


def _build_project(tmp_path, screens, ui_pages):
    """Write a design_system.json + registryhub_ui_pages.json + reference pngs;
    return (project_dir, [ref paths]). Exercises load_screen_classifications and
    load_ui_pages end to end, not just the pure mapper."""
    proj = tmp_path
    (proj / "design").mkdir(parents=True, exist_ok=True)
    (proj / "shared" / "hubs").mkdir(parents=True, exist_ok=True)
    (proj / "design" / "design_system.json").write_text(
        json.dumps({"screens": screens}), encoding="utf-8")
    (proj / "shared" / "hubs" / "registryhub_ui_pages.json").write_text(
        json.dumps({p["name"]: {"route": p.get("route", ""),
                                "component": p.get("component", "")}
                    for p in ui_pages}), encoding="utf-8")
    refs = []
    for s in screens:
        f = proj / f"{s['name']}.png"
        f.write_bytes(b"\x89PNG\r\n")
        refs.append(str(f))
    return proj, refs


# The app the design references depict: /browse and /title/:id are SERVED, and
# the app registered dedicated pages for the browse-home and title-detail screens.
_KNOWN = {"/", "/login", "/browse", "/account", "/title/:id"}
_UI_PAGES = [
    {"name": "browse_home_page", "route": "/browse", "component": "BrowseHomePage"},
    {"name": "title_detail_page", "route": "/title/:id", "component": "TitleDetailPage"},
    # a real page exists for the account menu's tokens, to prove the *_menu overlay
    # guard (not the absence of a page) is what keeps it advisory.
    {"name": "account_menu_page", "route": "/account", "component": "AccountMenu"},
]
_SCREENS = [
    # analyst MISLABELED these two real hero pages as overlays:
    {"name": "browse_home", "route": "/browse", "kind": "overlay",
     "components": [{"id": "hero"}, {"id": "rail"}]},
    {"name": "title_detail", "route": "/title/:id", "kind": "overlay",
     "components": [{"id": "art"}]},
    # a GENUINE overlay: a dropdown on the browse page, no dedicated page (and its
    # name is a structural overlay token) -> must stay advisory / not captured.
    {"name": "account_menu", "route": "/browse", "kind": "overlay",
     "components": [{"id": "menu"}]},
    # a variant of the browse page (extra 'rows' token) -> no strong page match,
    # stays advisory.
    {"name": "browse_home_rows", "route": "/browse", "kind": "overlay",
     "components": [{"id": "rows"}]},
    # a real page the app DOES serve, to keep the blocking set non-trivial.
    {"name": "login", "route": "/login", "kind": "page",
     "components": [{"id": "form"}]},
    # a page whose route the app does NOT serve -> must stay skipped (route=None).
    {"name": "settings", "route": "/settings", "kind": "page",
     "components": [{"id": "panel"}]},
]


def _map(tmp_path):
    proj, refs = _build_project(tmp_path, _SCREENS, _UI_PAGES)
    cls = VF.load_screen_classifications(proj)
    pages = VF.load_ui_pages(proj)
    return {s["name"]: s for s in
            VF.map_reference_screens(refs, _KNOWN, classifications=cls, ui_pages=pages)}


def test_loaders_read_the_project(tmp_path):
    proj, _ = _build_project(tmp_path, _SCREENS, _UI_PAGES)
    cls = VF.load_screen_classifications(proj)
    assert cls["browse_home"]["kind"] == "overlay"        # the mislabel is present
    pages = {p["route"] for p in VF.load_ui_pages(proj)}
    assert {"/browse", "/title/:id", "/account"} <= pages  # registered pages loaded


def test_browse_home_promoted_to_its_app_route(tmp_path):
    """A measured screen the app built a dedicated ui_page for is routed to that
    page's ACTUAL route and judged as a blocking page — even when #132 mislabeled
    it kind='overlay'. NOT '/' and NOT skipped."""
    by = _map(tmp_path)
    bh = by["browse_home"]
    assert bh["route"] == "/browse", bh          # authoritative ui_page route, not '/'
    assert bh["advisory"] is False, bh           # promoted -> blocking (judged)


def test_title_detail_promoted_to_param_route(tmp_path):
    """The link resolves a PARAM route (/title/:id) that no filename token can
    derive — proving the design_screen<->ui_page<->route linkage, not the guess."""
    td = _map(tmp_path)["title_detail"]
    assert td["route"] == "/title/:id", td
    assert td["advisory"] is False, td


def test_promoted_screens_join_the_blocking_exam(tmp_path):
    """End to end: the promoted screens enter the judged set as BLOCKING pages
    (before #416 they were advisory overflow, dropped whenever the cap was full),
    the overlays are only ever advisory (non-blocking) fillers, and an unserved
    route is never selected. Blocking membership — not raw selection — is the
    guarantee: r13 had 14 blocking pages so its overlays had 0 advisory budget."""
    by = _map(tmp_path)
    selected = VF._select_judged_screens(list(by.values()), max_screens=8)
    blocking = {s["name"] for s in selected if not s["advisory"]}
    advisory = {s["name"] for s in selected if s["advisory"]}
    assert {"browse_home", "title_detail", "login"} <= blocking  # promoted -> exam
    assert "account_menu" not in blocking     # overlay never becomes a blocking page
    assert "browse_home_rows" not in blocking
    assert advisory <= {"account_menu", "browse_home_rows"}  # overlays stay advisory
    assert "settings" not in blocking and "settings" not in advisory  # unserved -> skipped


def test_overlay_named_screen_stays_advisory(tmp_path):
    """An OVERLAY screen whose name is a structural token (account_menu) stays
    advisory and is NOT captured as a page — even though a ui_page whose tokens
    equal it exists (account_menu_page). The #128 name rule owns it: it neither
    inherits the page route nor gets promoted (dropdowns/popups never become
    full pages)."""
    am = _map(tmp_path)["account_menu"]
    assert am["advisory"] is True, am
    assert am["route"] != "/account", am   # did NOT inherit the ui_page route
    assert am["route"] == "/browse", am    # keeps its classified base-page route


def test_variant_without_dedicated_page_stays_advisory(tmp_path):
    """A variant of a page (browse_home_ROWS carries an extra 'rows' token the
    ui_page lacks) is NOT a strong match, so it is not promoted and stays
    advisory — a variant must not graft onto the base page."""
    bhr = _map(tmp_path)["browse_home_rows"]
    assert bhr["advisory"] is True, bhr


def test_unserved_route_stays_skipped(tmp_path):
    """A measured page whose route the app does not serve stays skipped
    (route=None) — the gate never navigates to a 404."""
    st = _map(tmp_path)["settings"]
    assert st["route"] is None, st


def test_no_ui_pages_falls_back_to_prior_behavior(tmp_path):
    """Without a ui_pages registry the mapper behaves exactly as before: the
    mislabeled overlays stay advisory (the fallback path is untouched)."""
    proj, refs = _build_project(tmp_path, _SCREENS, _UI_PAGES)
    cls = VF.load_screen_classifications(proj)
    by = {s["name"]: s for s in
          VF.map_reference_screens(refs, _KNOWN, classifications=cls, ui_pages=None)}
    assert by["browse_home"]["advisory"] is True    # no linkage -> no promotion
    assert by["title_detail"]["advisory"] is True


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
