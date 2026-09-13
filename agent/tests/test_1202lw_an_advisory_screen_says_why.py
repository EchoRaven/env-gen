"""#1202lw — the gate asserted "overlay" for every advisory screen, whatever the real reason.

GROUND TRUTH (tiktok-web-r121 resume #3, 11:47:45):

    Visual fidelity PASSED (fyp_feed_comments_panel=0.69, fyp_feed_logged_out=0.76,
      explore_grid=0.52, following_suggested_creators=0.56, friends_suggested_creators=0.28,
      live_discover=0.40, login_modal=0.56, messages_dm_empty=0.13):
      all 2 screens ≥ 0.65 (blocking avg 0.72)
      [advisory (overlay, non-blocking): explore_grid(0.52), ... messages_dm_empty(0.13)]

`design/design_system.json` classifies every one of those as `kind=page`, not overlay. The
real reason is in the same log one line earlier:

    VISUAL MILESTONE-SCOPE (#565): demoted 7 non-owned screen(s) ['explore_grid',
      'following_suggested_creators', 'friends_suggested_creators', 'live_discover',
      'messages_dm_empty', 'notifications_activity', 'profile_own'] to advisory for this
      milestone (owned routes=[...])

Nine minutes later the browser test-user independently reported `friends_suggested_creators_
page`, `live_discover_page` and `messages_dm_empty_page` BLANK — so a reader asking whether a
0.13 matters is precisely the reader that sentence misdirects. (It misdirected me: I went to
the classification file and found `kind=page`, which is not where the answer was.)

#949's rule, already settled in this module for capture failures: naming a cause nobody
checked is worse than naming none, because it sends the reader somewhere real to look for
something that never happened. Everything needed was already in scope — `_scope_excluded_
names` from the #565 pass, and `advisory_reason`, which earlier demotions set and nothing
ever read.
"""
import inspect
import re

import pytest

from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf


def _summary_src():
    src = inspect.getsource(vf)
    i = src.index("_adv_groups_1202lw")
    return src[:i + 4000]


def test_the_fixed_overlay_label_is_gone():
    # The string survives in the fix's own comment, which QUOTES the r121 log line it
    # replaces — so assert it is no longer EMITTED, not that it is absent from the file.
    # (The first draft asserted absence and failed on the explanation of its own fix.)
    src = inspect.getsource(vf)
    emitting = [ln for ln in src.splitlines()
                if "advisory (overlay, non-blocking)" in ln
                and not ln.lstrip().startswith("#")]
    assert not emitting, ("the label is still emitted, not merely quoted: %s" % emitting)


def test_milestone_scope_is_named_as_itself():
    src = inspect.getsource(vf)
    assert "not this milestone's routes (#565)" in src


def test_the_existing_advisory_reason_field_is_finally_read():
    """#595-era demotions have been WRITING `advisory_reason` with nothing reading it."""
    src = inspect.getsource(vf)
    assert src.count('advisory_reason') >= 4
    i = src.index("_adv_reason_1202lw")
    assert 'advisory_reason' in src[i:i + 900], (
        "the reason field is still written-only at the one place a reader looks")


def test_the_reason_function_prefers_scope_then_recorded_then_fallback():
    src = inspect.getsource(vf)
    i = src.index("def _adv_reason_1202lw")
    body = src[i:i + 700]
    i_scope = body.index("_scope_excluded_names")
    i_reason = body.index("advisory_reason")
    i_fallback = body.index("overlay/transient")
    assert i_scope < i_reason < i_fallback, (
        "a screen demoted BY SCOPE must not be reported as an overlay just because it also "
        "lacks a recorded reason")


def test_screens_are_grouped_by_reason_not_listed_flat():
    src = inspect.getsource(vf)
    assert "_adv_groups_1202lw.setdefault" in src
    i = src.index('summary += " [advisory (non-blocking)')
    assert '"; ".join(_adv_note)' in src[i:i + 200]


def test_the_fallback_still_covers_a_genuine_overlay():
    """★ Non-vacuity: login_modal really IS `kind=overlay` in r121's classification, and must
    still be describable."""
    src = inspect.getsource(vf)
    i = src.index("def _adv_reason_1202lw")
    assert 'return "overlay/transient screen"' in src[i:i + 700]


def test_the_reason_is_bounded():
    """A recorded reason is prose from elsewhere; the summary is a log line."""
    src = inspect.getsource(vf)
    i = src.index("def _adv_reason_1202lw")
    assert re.search(r"_why\[:\d+\]", src[i:i + 700]), "an unbounded reason can flood the line"
