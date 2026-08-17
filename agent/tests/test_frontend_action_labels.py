"""#451 (netflix r36 judge's MOST-REPEATED miss across browse_home/movies/shows/
games: "hero lacks key CTAs"). The hero renders its Play/More-Info CTAs only when
_action_labels_221 extracts labels from the design's action component, but the old
'Capitalized phrase immediately before ( or the word button' rule missed the common
measured formats — "Play and More Info action buttons" → [] and "Play and More Info
CTA buttons" → ['Info CTA'] — so those heroes shipped with NO CTAs. FIX: drop
parentheticals, split on and/&/comma, strip role-noise (primary/secondary/cta/
action/button/…), keep the Capitalized label run per fragment. Generalizable —
parses the design's own action role, no product literals. Locks it in."""
from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    _action_labels_221, _render_reference_page)


def test_extracts_labels_across_role_phrasings():
    cases = {
        "Play (primary) and More Info (secondary) buttons": ["Play", "More Info"],
        "Play and More Info action buttons": ["Play", "More Info"],
        "Play and More Info CTA buttons": ["Play", "More Info"],
        "Row with Play (primary) and More Info (secondary) buttons": ["Play", "More Info"],
        "Primary Play Game button and secondary More Info button": ["Play Game", "More Info"],
    }
    for role, exp in cases.items():
        assert _action_labels_221(role) == exp, f"{role!r} → {_action_labels_221(role)!r}"


def test_quoted_labels_take_precedence():
    assert _action_labels_221("'Get Started' button") == ["Get Started"]
    assert _action_labels_221('"Sign In" and "Sign Up" buttons') == ["Sign In", "Sign Up"]


def test_no_labels_from_all_lowercase_prose():
    # all-lowercase prose yields nothing (there IS no capitalized label to extract).
    # NOTE: _action_labels_221 is only called on components that pass _is_action_comp
    # (role contains 'button'/'action'), so it never runs on rail/prose roles in
    # practice — it is a pure Capitalized-run extractor, gated at the call site.
    assert _action_labels_221("metadata line: genre, year, seasons, rating") == []
    assert _action_labels_221("") == [] and _action_labels_221(None) == []


def test_caps_at_three_and_dedups():
    out = _action_labels_221("Play and Play and More Info and Download and Share buttons")
    assert out[:1] == ["Play"] and len(out) <= 3 and out.count("Play") == 1


# ── integration: a hero whose action role uses the 'action buttons' phrasing now
#    renders the Play CTA (previously empty) ──
_DESIGN = {"design_system": {"palette": {"bg": "#141414", "accent": "#e50914"},
                             "theme": {"default": "dark"}}, "assets": []}


def test_hero_renders_ctas_from_action_buttons_phrasing():
    scr = {"route": "/shows", "name": "shows", "kind": "page", "components": [
        {"id": "hero", "region": [0.0, 0.0, 1.0, 0.78], "role": "featured show backdrop"},
        {"id": "cta", "region": [0.03, 0.75, 0.28, 0.82],
         "role": "Play and More Info action buttons"},
        {"id": "rail", "region": [0.03, 0.89, 1.0, 1.0], "role": "poster rail of Top Picks",
         "geometry": {"columns": 6}}]}
    out = _render_reference_page("ShowsPage", {"route": "/shows"}, scr, _DESIGN,
                                 [("Shows", "/shows")], "/api/titles")
    assert "▶" in out, "hero Play CTA (▶) present"
    assert "More Info" in out, "hero secondary CTA present"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
