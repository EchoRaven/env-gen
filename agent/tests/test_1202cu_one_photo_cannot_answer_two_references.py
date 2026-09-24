"""#1202cu — photograph a route's later states where they actually are.

Several reference frames map to ONE route. #718 documented the group and computed what
it costs, then did nothing: it is a comment and a log line. r41 paid for that. Its
browse_home_rows scored 0.42 and BLOCKED the release while browse_home, the same
scroll-top photo, scored 0.69 — and the judge, grading that one photo against two
references, wrote "Remove the hero banner from the /browse rows state" against a screen
whose sibling is graded on the hero being present.

#509 established the shape of the answer for overlay states (drive the interaction
before the shot, best-effort, never regress). Scroll is the same problem with a simpler
driver, and the JS was verified against a real browser: scrollY 0 -> 800 -> 1600 at a
800px viewport.
"""
from pathlib import Path

import pytest

from env_generator.llm_generator.multi_agent.runtime.visual_fidelity import (
    scroll_state_index_1202cu,
    _SCROLL_STATE_MAX_1202CU,
)


def test_the_second_state_of_a_route_is_photographed_a_viewport_down():
    """r41's exact shape: browse_home is the base, browse_home_rows is one screen down."""
    idx = scroll_state_index_1202cu([
        {"name": "browse_home", "route": "/browse"},
        {"name": "browse_home_rows", "route": "/browse"},
    ])
    assert idx == {"browse_home_rows": 1}


def test_a_route_with_one_screen_is_untouched():
    """The overwhelmingly common case must be byte-identical to today — an app whose
    screens each own a route must not start scrolling."""
    assert scroll_state_index_1202cu([
        {"name": "home", "route": "/"},
        {"name": "settings", "route": "/settings"},
    ]) == {}


def test_advisory_overlays_are_left_to_the_509_driver():
    """advisory IS #128's authoritative overlay classification. Scrolling under an open
    menu photographs neither the menu nor the rows."""
    idx = scroll_state_index_1202cu([
        {"name": "browse_home", "route": "/browse"},
        {"name": "account_menu", "route": "/browse", "advisory": True},
        {"name": "card_hover_preview", "route": "/browse", "advisory": True},
        {"name": "browse_home_rows", "route": "/browse"},
    ])
    assert idx == {"browse_home_rows": 1}


def test_the_offset_is_bounded():
    """A route with many states must not scroll into an empty footer, where every
    screen would score the same blank."""
    idx = scroll_state_index_1202cu(
        [{"name": f"s{i}", "route": "/r"} for i in range(8)])
    assert max(idx.values()) == _SCROLL_STATE_MAX_1202CU


def test_bad_input_cannot_break_a_capture():
    """This runs inside the capture loop; raising here would cost the whole round's
    screenshots, which is far worse than not scrolling."""
    assert scroll_state_index_1202cu(None) == {}
    assert scroll_state_index_1202cu([None, {"no_name": 1}, {"name": "x"}]) == {}


def test_the_scroll_happens_before_the_shot_and_cannot_raise():
    """Order is the mechanism, and best-effort is what makes it safe to add: a failed
    scroll must leave exactly today's scroll-top capture."""
    src = Path("env_generator/llm_generator/multi_agent/runtime/"
               "visual_fidelity.py").read_text()
    body = src[src.index("_sk1202cu = _scroll_1202cu.get"):]
    body = body[:body.index("shots[screen[\"name\"]] = str(dest)")]
    assert body.index("window.scrollTo") < body.index("_screenshot_with_retry_1065")
    assert "except Exception:" in body[:body.index("_screenshot_with_retry_1065")]
