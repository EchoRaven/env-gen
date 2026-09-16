"""#1202pb: the framework's sign-in template carries no product's footer copy.

`_AUTH_FOOTER_LINKS_540` — FAQ, Help Center, Terms of Use, Privacy, Cookie Preferences, Corporate
Information — and a "Questions? Contact support" fallback were emitted into every spec-driven
login page whatever the product. #873 gated those lines in the base template only. The literals
are in the delivered trees of 13 tiktok runs (r102-r117); r111/r119/r123's `login_modal` captures
are byte-identical Netflix-style pages. The pipeline must be domain-agnostic.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.frontend_scaffold import _auth_spec_540  # noqa: E402


def _screen(*roles):
    return {"components": [{"role": r} for r in roles]}


def test_a_design_that_names_no_footer_gets_none():
    spec = _auth_spec_540(_screen('page heading "Log in to TikTok"',
                                  "email or mobile input field"))
    assert spec is not None and spec["footer_links"] == []
    assert spec["contact"] == ""


def test_a_design_that_names_footer_links_gets_exactly_those():
    spec = _auth_spec_540(_screen('page heading "Sign In"',
                                  'footer links "FAQ", "Help Center", "Privacy"'))
    assert spec["footer_links"] == ["FAQ", "Help Center", "Privacy"]


def test_the_rendered_page_carries_no_foreign_literal():
    """Behavioural: render the real sign-in page for a TikTok-shaped spec."""
    from multi_agent.runtime.frontend_scaffold import _auth_page_src_540
    screen = _screen('page heading "Log in to TikTok"', "email or mobile input field")
    src = _auth_page_src_540("LoginPage", {"route": "/login", "name": "LoginPage"}, screen,
                             {}, {"bg": "#000000", "accent": "#fe2c55"}, {}, ["/", "/login"])
    assert "Log in to TikTok" in src, src[:400]
    for foreign in ("Cookie Preferences", "Corporate Information", "Contact support",
                    "Help Center"):
        assert foreign not in src, foreign


def test_declared_footer_copy_is_rendered():
    from multi_agent.runtime.frontend_scaffold import _auth_page_src_540
    screen = _screen('page heading "Sign In"', 'footer links "Terms", "Privacy"')
    src = _auth_page_src_540("LoginPage", {"route": "/login", "name": "LoginPage"}, screen,
                             {}, {"bg": "#000000"}, {}, ["/", "/login"])
    assert "Terms" in src and "Privacy" in src


def test_a_declared_but_unlabelled_footer_band_keeps_neutral_links():
    """#463 added the footer because a login page with none scored 0.35 ("missing footer"). A
    band the design measured but did not label keeps content — generic conventions, not
    Netflix's "Corporate Information" / "Cookie Preferences"."""
    from multi_agent.runtime.frontend_scaffold import _auth_page_src_540
    screen = _screen('page heading "Sign In"', "footer section with link columns")
    src = _auth_page_src_540("LoginPage", {"route": "/login", "name": "LoginPage"}, screen,
                             {}, {"bg": "#000000"}, {}, ["/", "/login"])
    assert "Help" in src and "Terms" in src and "Privacy" in src
    assert "Corporate Information" not in src and "Cookie Preferences" not in src
