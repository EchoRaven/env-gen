"""#1202cl — a measured colour that is really the backdrop must not be handed over as EXACT.

The decomposition samples the reference screenshot inside each component's region, so a
translucent component, or one over photographic content, measures whatever is BEHIND it. A
component's own colour does not change between screens; a name whose samples disagree across
screens is measuring the backdrop.

netflix r35, one `top_navigation_bar` across nine screens: #271e17 on genre_category (a warm
sports still), #202a33 on games (cover art), #5a564d on browse_home, #000000 on
card_hover_preview — brown to blue-grey to black, spread 148. The framework already knows
this at document level: the measured palette carries `top_nav_translucent_on_hero: #5a564d`
as its own entry. Only the per-component rows, the ones handed to the lane as "EXACT ...
never eyeball", assert the composite as the component's colour — and a lane that obeys paints
one navigation bar nine different colours.

LOCAL-ONLY (agent/tests/ gitignored).
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.visual_fidelity import (  # noqa: E402
    _composited_components_1202cl as C, _spec_snippet)


def _specs(tmp_path, screens):
    d = tmp_path / "design" / "component_specs"
    d.mkdir(parents=True, exist_ok=True)
    for name, comps in screens.items():
        (d / f"{name}.json").write_text(json.dumps({"components": comps}), encoding="utf-8")
    return tmp_path


NAV_VARIES = {
    "a": [{"name": "top_nav", "background": "#271e17"}, {"name": "card", "background": "#141414"}],
    "b": [{"name": "top_nav", "background": "#202a33"}, {"name": "card", "background": "#141414"}],
    "c": [{"name": "top_nav", "background": "#000000"}, {"name": "card", "background": "#141414"}],
}


def test_a_component_that_disagrees_across_screens_is_flagged(tmp_path):
    got = C(_specs(tmp_path, NAV_VARIES))
    assert "top_nav" in got and "backdrop" in got["top_nav"]


def test_a_component_that_agrees_is_left_exact(tmp_path):
    """THE control. Most rows measure correctly and must keep their unqualified instruction —
    this is a caveat on two components, not a blanket weakening."""
    assert "card" not in C(_specs(tmp_path, NAV_VARIES))


def test_a_component_seen_on_fewer_than_three_screens_is_not_judged(tmp_path):
    """Two samples cannot distinguish a translucent component from a legitimate state
    change (a selected tab, a dark-mode variant)."""
    two = {k: v for k, v in list(NAV_VARIES.items())[:2]}
    assert C(_specs(tmp_path, two)) == {}


def test_small_variation_is_not_flagged(tmp_path):
    """Anti-aliasing and JPEG noise move a sample a few units; the threshold must not fire
    on that or every row would carry a caveat and the exact ones would stop being believed."""
    near = {k: [{"name": "top_nav", "background": h}]
            for k, h in (("a", "#141414"), ("b", "#151515"), ("c", "#131313"))}
    assert C(_specs(tmp_path, near)) == {}


def test_a_missing_spec_dir_is_silent(tmp_path):
    assert C(tmp_path) == {}


def test_the_caveat_reaches_the_lane_instruction(tmp_path):
    """A finding that never leaves the helper changes nothing: it has to appear in the text
    the fixing lane actually reads."""
    root = _specs(tmp_path, NAV_VARIES)
    out = _spec_snippet(root, "a")
    assert "⚠" in out and "backdrop" in out
    assert "EXCEPT any row marked" in out, "the header must say the exception exists"
    # the agreeing component keeps its plain row
    card = [l for l in out.splitlines() if "card" in l][0]
    assert "⚠" not in card


def test_a_screen_with_no_composited_component_keeps_the_plain_header(tmp_path):
    """The header only gains the EXCEPT clause when a row on THIS screen carries one."""
    root = _specs(tmp_path, {k: [{"name": "card", "background": "#141414"}]
                             for k in ("a", "b", "c")})
    out = _spec_snippet(root, "a")
    assert "EXCEPT any row marked" not in out and "⚠" not in out


def test_it_flags_the_real_netflix_nav_bar():
    """Ground truth: r35's top_navigation_bar spans 148 across nine screens, and exactly two
    of its twelve rows should be flagged — not the other ten."""
    d = Path("/data/common/haibotong/forgingground-gen/generated/netflix-local-r35")
    if not (d / "design" / "component_specs").is_dir():
        return
    got = C(d)
    assert "top_navigation_bar" in got
    assert len(got) <= 4, f"too broad: {sorted(got)}"
