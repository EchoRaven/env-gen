"""Fix #65 — detect a wholesale light/dark theme inversion and lead the visual
remediation with it (outlook run-50, live 2026-07-02).

run-50 delivered a USABLE app (auth_ok=True, 3 milestones) but every page scored
0.20 vs the reference: the run's text said 'light theme' while the reference
screenshots are DARK Outlook, so the frontend built LIGHT (top_bar/nav_rail
rendered #ffffff) against a #292929/#09101a DARK reference. The per-component
MEASURED COLOR DIFF (#52) was correct but scattered — it buried the ONE
structural fact (wrong base theme) that dominates similarity (large-area
background = the #1 lever). theme_inversion() surfaces it as a single
high-signal remediation line: reference images WIN over text 'theme' wording,
flip the base theme first. LOCAL-ONLY (agent/tests/ gitignored).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.material_prep import theme_inversion  # noqa: E402


def _bg(comp, actual, expected):
    return {"kind": "background", "component": comp, "actual": actual, "expected": expected}


# ------------------------------------------------------------- detector
def test_run50_light_build_dark_reference_wants_dark():
    devs = [_bg("top_bar", "#ffffff", "#292929"),
            _bg("nav_rail", "#ffffff", "#09101a"),
            _bg("menu_bar", "#f8f8f8", "#060e15"),
            _bg("left_pane", "#ffffff", "#141414"),
            _bg("calendar_grid", "#ffffff", "#1f1f1f")]
    assert theme_inversion(devs) == "dark"


def test_dark_build_light_reference_wants_light():
    devs = [_bg(c, "#191919", "#ffffff") for c in ("a", "b", "c", "d")]
    assert theme_inversion(devs) == "light"


def test_close_colors_not_flagged():
    devs = [_bg(c, "#eeeeee", "#f5f5f5") for c in ("a", "b", "c", "d")]
    assert theme_inversion(devs) is None


def test_mixed_directions_not_flagged():
    devs = [_bg("a", "#ffffff", "#111111"), _bg("b", "#111111", "#ffffff"),
            _bg("c", "#ffffff", "#101010")]
    assert theme_inversion(devs) is None      # no 2/3 same-direction majority


def test_too_few_backgrounds_not_flagged():
    assert theme_inversion([_bg("a", "#ffffff", "#111111"),
                            _bg("b", "#ffffff", "#111111")]) is None


def test_accent_only_deviations_ignored():
    devs = [{"kind": "accent_missing", "component": "x", "hue": "blue",
             "expected": "#2d4edf"}] * 5
    assert theme_inversion(devs) is None


def test_partial_majority_two_thirds():
    # 4 inverted + 1 close (5 total) → 4 >= ceil(2*5/3)=4 → flagged
    devs = [_bg(c, "#ffffff", "#151515") for c in ("a", "b", "c", "d")]
    devs.append(_bg("e", "#fbfbfb", "#f0f0f0"))
    assert theme_inversion(devs) == "dark"
    # 3 inverted + 2 close (5 total) → 3 < 4 → not flagged
    devs2 = [_bg(c, "#ffffff", "#151515") for c in ("a", "b", "c")]
    devs2 += [_bg("d", "#fbfbfb", "#f0f0f0"), _bg("e", "#fafafa", "#eeeeee")]
    assert theme_inversion(devs2) is None


# ------------------------------------------------------ remediation wiring
def test_remediation_leads_with_theme_warning():
    from multi_agent.runtime.visual_fidelity import _measured_diff_lines
    r = {"name": "outlook_inbox", "route": "/inbox", "reference": "/refs/outlook_inbox.png",
         "measured_deviations": [
             _bg("top_bar", "#ffffff", "#292929"),
             _bg("nav_rail", "#ffffff", "#09101a"),
             _bg("list", "#ffffff", "#1f1f1f")]}
    lines = _measured_diff_lines(r)
    text = "\n".join(lines)
    assert "WRONG BASE THEME" in text
    assert "DARK" in text and "flip the app's BASE theme to dark" in text
    # the theme line comes BEFORE the per-component color diff
    assert text.index("WRONG BASE THEME") < text.index("MEASURED COLOR DIFF")


def test_remediation_no_theme_warning_when_colors_close():
    from multi_agent.runtime.visual_fidelity import _measured_diff_lines
    r = {"name": "x", "route": "/x", "reference": "/refs/x.png",
         "measured_deviations": [_bg("top_bar", "#2b2b2b", "#292929")]}
    text = "\n".join(_measured_diff_lines(r))
    assert "WRONG BASE THEME" not in text


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
