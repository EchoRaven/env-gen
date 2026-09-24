"""A2b — explain the THEME MECHANISM to the lane for dark-variant failing screens.

login_dark sat at 0.15 across run-73/75/76 while login_light climbed: the measured dark
hexes DO reach the lane (A2 geometry block prints them), but nothing ever explains that
the gate captures the SAME /login component with html.dark + [data-theme=dark] +
prefers-color-scheme:dark (#141), so the lane never writes dark-variant CSS and the dark
capture photographs light pixels — the judge's 0.15 is honest (run-65 定性). A2b adds a
THEME VARIANT block for failing screens whose scheme (screen_color_scheme #141) is
dark/light-variant, stating the mechanism + forbidding a forked page.
ENVGEN_THEME_VARIANT_FIX=0 reverts. LOCAL-ONLY (agent/tests/ gitignored).
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.visual_fidelity import remediation_text  # noqa: E402


def _mk_out(tmp_path):
    out = tmp_path / "out"
    (out / "design").mkdir(parents=True)
    (out / "design" / "design_system.json").write_text(json.dumps({
        "assets": [], "screens": [
            {"name": "login_dark", "route": "/login", "kind": "page", "components": []},
        ]}))
    (out / "app" / "frontend" / "src").mkdir(parents=True)
    return out


def _failing(name, sim=0.15):
    return {"screens": [
        {"name": name, "route": "/login", "similarity": sim, "passed": False,
         "dimensions": {}, "deviations": [], "fixes": ["darken it"]},
    ]}


def test_dark_screen_gets_theme_mechanism_block(tmp_path):
    out = _mk_out(tmp_path)
    text = remediation_text(_failing("login_dark"), str(out))
    sect = text[text.index("## login_dark"):]
    assert "THEME VARIANT" in sect
    assert "html.dark" in sect, "must state HOW the gate renders the dark variant"
    assert "dark:" in sect, "must point at Tailwind dark: variants / .dark scoped CSS"
    assert sect.index("THEME VARIANT") < sect.index("darken it"), \
        "mechanism precedes the judge fixes"


def test_light_variant_screen_gets_light_wording(tmp_path):
    out = _mk_out(tmp_path)
    text = remediation_text(_failing("login_light"), str(out))
    sect = text[text.index("## login_light"):]
    assert "THEME VARIANT" in sect and "light" in sect.lower()


def test_dark_block_flags_wired_page_without_dark_variants(tmp_path):
    """run-78 autopsy: the lane wrote perfect dark: variants (measured hexes)
    into components/login/* — files NO page imports — while the page actually
    wired at /login (pages/LoginPage.jsx) stayed bg-white with zero dark:
    support. The mechanism block must point at the WIRED file when it carries
    no dark: token so the work lands where it renders."""
    import json as _json
    out = _mk_out(tmp_path)
    hubs = out / "shared" / "hubs"
    hubs.mkdir(parents=True)
    (hubs / "registryhub_ui_pages.json").write_text(_json.dumps({
        "login": {"route": "/login", "component": "LoginPage", "status": "implemented"}}))
    pages = out / "app" / "frontend" / "src" / "pages"
    pages.mkdir(parents=True)
    (pages / "LoginPage.jsx").write_text(
        "export default () => <div className='bg-white text-black'>login</div>;")
    text = remediation_text(_failing("login_dark"), str(out))
    sect = text[text.index("## login_dark"):]
    assert "LoginPage.jsx" in sect and "no `dark:`" in sect, \
        "must name the WIRED page file that lacks dark: variants"

    # once the wired file HAS dark: variants, the extra warning disappears
    (pages / "LoginPage.jsx").write_text(
        "export default () => <div className='bg-white dark:bg-[#0c1014]'>login</div>;")
    text2 = remediation_text(_failing("login_dark"), str(out))
    assert "no `dark:`" not in text2


def test_unthemed_screen_gets_no_block(tmp_path):
    out = _mk_out(tmp_path)
    text = remediation_text(_failing("explore"), str(out))
    assert "THEME VARIANT" not in text


def test_disable_switch(tmp_path, monkeypatch):
    monkeypatch.setenv("ENVGEN_THEME_VARIANT_FIX", "0")
    out = _mk_out(tmp_path)
    text = remediation_text(_failing("login_dark"), str(out))
    assert "THEME VARIANT" not in text


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
