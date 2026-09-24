"""FIX #285 — _flow_key doesn't fold the _ui / _page_ui suffixes, so a passing record can't
clear a same-flow failing twin (tiktok r70, live).

#237 made _flow_key suffix-insensitive for `_page` / `_screen` so a verifier record under
either spelling satisfies a required flow. But the verifier also writes `_ui` and `_page_ui`
variants, and _flow_key folds NEITHER: it strips one trailing `_page`/`_screen` and stops.

r70 (live) died on exactly this. For every critical page the verifier wrote TWO ui_flow
records — an early `<name>_page` that FAILED and a later `<name>_page_ui` that PASSED:

    following_suggested_creators_page     -> failed
    following_suggested_creators_page_ui  -> passed      (real: browser flow passed)

_flow_key('..._page')    -> '...creators'                (strips _page)
_flow_key('..._page_ui') -> '...creators_page_ui'        (trailing _ui, no strip)

Different keys → the passing `_page_ui` record can never clear the failing `_page` twin, so
compute_flow_coverage reported 6 flows FAILED though every one had actually passed. That was
the sole remaining delivery-gate blocker (deliverability_ui_flow_failed) through two
CONVERGING-GRACE extensions.

Fix: fold `_ui` too, and fold COMPOUND suffixes (`_page_ui` -> strip both) by looping until
stable, so `X`, `X_page`, `X_ui`, `X_page_ui`, `X_screen_ui` all share the key `X`.
ENV-AGNOSTIC + LOCAL-ONLY (agent/tests/ gitignored).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.flow_coverage import _flow_key  # noqa: E402


def test_ui_suffix_folds():
    assert _flow_key("fyp_feed_ui") == _flow_key("fyp_feed") == "fyp_feed"
    assert _flow_key("signup_ui") == _flow_key("signup") == "signup"
    assert _flow_key("login_modal_ui") == _flow_key("login_modal") == "login_modal"


def test_page_ui_compound_folds_to_bare():
    """The exact r70 wedge: _page and _page_ui must share a key."""
    bare = "following_suggested_creators"
    assert _flow_key("following_suggested_creators_page") == bare
    assert _flow_key("following_suggested_creators_page_ui") == bare
    assert _flow_key("explore_grid_page") == _flow_key("explore_grid_page_ui") == "explore_grid"


def test_237_page_screen_still_fold():
    """The behaviour #237 added must survive."""
    assert _flow_key("explore") == _flow_key("explore_page") == _flow_key("explore_screen") == "explore"


def test_screen_ui_compound_also_folds():
    assert _flow_key("discover_screen_ui") == _flow_key("discover") == "discover"


def test_ui_page_order_also_folds():
    """Defensive: the rarer _ui_page ordering should collapse too."""
    assert _flow_key("live_discover_ui_page") == "live_discover"


def test_bare_case_and_blank_are_safe():
    assert _flow_key("FYP_Feed") == "fyp_feed"
    assert _flow_key("  signup  ") == "signup"
    assert _flow_key("") == ""
    # a bare name with no fold suffix is unchanged
    assert _flow_key("profile") == "profile"


def test_does_not_overstrip_names_that_merely_contain_ui():
    """Only a trailing _ui token folds; an internal 'ui' must stay."""
    assert _flow_key("guided_tour") == "guided_tour"
    assert _flow_key("build_ui_editor") == "build_ui_editor"
