r"""#1202al: the frontend lane is told the rule it was breaking in 47 of 117 environments.

#1202ai measures props React drops because the component never destructures them — 152
occurrences across 47 of the 117 corpus environments — and #1202aj files each finding as a
task. Both are after the fact. The lane's own instructions never mentioned prop contracts at
all: the frontend agent prompt's five matches for "prop" are all the word "proposal".

So the rule now lives where the lane reads before writing UI. It is stated with the measurement
and three real examples, because a rule without a consequence reads as style advice:

    <PostHeader createdAt>          takes {user}                  -> no timestamp ever renders
    <LoginForm setToken>            takes {setIsRegister}         -> the token is never stored
    <NetflixChrome title subtitle>  takes {children, activeLabel} -> the page heading is absent

The framework's OWN projected components are clean — scaffolding three pages and scanning the
output finds zero — so this is entirely a lane-authoring rule, which is why it belongs in the
skill and not in the projector.
"""

import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
_SKILL = (THIS_DIR.parent
          / "env_generator/llm_generator/multi_agent/bundled_skills/frontend-design/SKILL.md")


def test_the_rule_is_in_the_skill():
    src = _SKILL.read_text(encoding="utf-8")
    assert "silently dropped" in src
    assert "destructur" in src


def test_it_states_the_consequence_not_just_the_rule():
    """A rule with no consequence reads as style advice and gets skipped."""
    src = _SKILL.read_text(encoding="utf-8")
    assert "no console error" in src
    assert "every gate stays green" in src


def test_it_carries_the_measurement():
    src = _SKILL.read_text(encoding="utf-8")
    assert "152" in src and "47 of" in src


def test_it_names_real_examples_from_the_corpus():
    src = _SKILL.read_text(encoding="utf-8")
    for example in ("PostHeader", "LoginForm", "NetflixChrome"):
        assert example in src, example


def test_the_rule_sits_in_the_env_gen_section():
    """It has to be next to the other things checked at sign-off, not in the styling advice."""
    src = _SKILL.read_text(encoding="utf-8")
    i = src.index("## env-gen integration")
    j = src.index("silently dropped")
    # the ui_smoke line INSIDE that section, not an earlier mention elsewhere
    k = src.index("validation:ui_smoke", i)
    assert i < j < k


def test_the_projected_components_do_not_break_the_rule(tmp_path):
    """The framework's own output must not violate a rule it hands the lane."""
    sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))
    from multi_agent.runtime.frontend_scaffold import scaffold_pages_from_contract
    from multi_agent.runtime.frontend_audit import dropped_prop_findings_1202ai
    fe = tmp_path / "app" / "frontend"
    (fe / "src" / "pages").mkdir(parents=True)
    (fe / "src" / "components").mkdir(parents=True)
    scaffold_pages_from_contract(fe, [
        {"name": "browse", "route": "/browse", "component": "BrowsePage",
         "path": "app/frontend/src/pages/BrowsePage.jsx", "apis_used": ["GET /api/titles"]},
        {"name": "login", "route": "/login", "component": "LoginPage",
         "path": "app/frontend/src/pages/LoginPage.jsx", "apis_used": ["POST /auth/login"]},
    ])
    assert dropped_prop_findings_1202ai(fe / "src") == []
