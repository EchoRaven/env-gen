"""#474 NAV REF-FILTER — r49 docked shows/new_and_popular/my_list for nav 'adds Profiles,
omits My List'. ROOT: both nav_routes derivation sites (frontend_scaffold.py:4632, 5040)
build (segment-label, route) then cap [:7] WITHOUT filtering to the design's measured
primary-nav enumeration, so /profiles (the 'who's watching' SELECTION page — not a browse
destination) leaked into the top nav and the cap then cut a real ref item (My List).

FIX: _filter_nav_to_ref(nav_routes, design) — when the design measured a SUBSTANTIAL nav
enumeration (_ref_nav_labels >=4 labels), keep only routes whose label/route token-matches
a reference label; applied BEFORE the cap at both derivation sites. Design-driven (the
app's OWN measured nav is authoritative), no product literals → a social app whose ref nav
enumerates 'Profiles' KEEPS it. Gated (small/absent enumeration → keep all) + fallback
(never blank the nav). The ROUTE stays reachable; only the nav ENTRY is dropped (#467).
Generalizable to every app/env."""
from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    _filter_nav_to_ref, _ref_nav_labels)


def _netflix_design():
    return {"screens": [{"components": [
        {"id": "primary-nav-links",
         "role": ("horizontal primary nav: Home, Shows, Movies, Games, "
                  "New & Popular, My List, Browse by Languages")},
    ]}]}


def test_ref_labels_parse_precondition():
    ref = _ref_nav_labels(_netflix_design())
    assert "My List" in ref and "Profiles" not in ref, "design nav lists My List, not Profiles"
    assert len(ref) >= 4, "substantial enumeration"


def test_drops_profiles_keeps_my_list():
    nav = [("Home", "/browse"), ("Shows", "/shows"), ("Profiles", "/profiles"),
           ("My List", "/my-list"), ("Movies", "/movies"), ("New", "/new")]
    out = _filter_nav_to_ref(nav, _netflix_design())
    labels = [l for l, _ in out]
    assert "Profiles" not in labels, "#474: /profiles (not in ref nav) dropped from nav"
    assert "My List" in labels, "#474: My List (a ref item) survives"
    # the /profiles ROUTE object is untouched by this filter (only the nav entry is dropped)
    assert ("Profiles", "/profiles") not in out


def test_small_or_absent_enumeration_no_op():
    nav = [("Home", "/browse"), ("Profiles", "/profiles")]
    # no design → _ref_nav_labels == [] → keep everything (no regression)
    assert _filter_nav_to_ref(nav, {}) == nav
    # a THIN enumeration (<4 labels) must not over-filter
    thin = {"screens": [{"components": [
        {"id": "primary-nav-links", "role": "primary nav: Home, Profiles"}]}]}
    assert _filter_nav_to_ref(nav, thin) == nav


def test_never_blanks_the_nav():
    # pathological: none of the routes match the ref labels → keep original (fallback)
    nav = [("Zzz", "/zzz"), ("Qqq", "/qqq")]
    out = _filter_nav_to_ref(nav, _netflix_design())
    assert out == nav, "#474: if the filter would empty the nav, keep the original"


def test_social_app_keeps_profiles():
    # generalization: an app whose OWN measured nav enumerates Profiles KEEPS it
    social = {"screens": [{"components": [
        {"id": "primary-nav-links",
         "role": "primary nav: Home, Profiles, Messages, Notifications, Settings"}]}]}
    nav = [("Home", "/home"), ("Profiles", "/profiles"), ("Messages", "/messages")]
    out = _filter_nav_to_ref(nav, social)
    assert ("Profiles", "/profiles") in out, "#474: social app's ref nav lists Profiles → kept"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
