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
import ast
import inspect
import re

import pytest

from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf

# #943: AST anchors, not byte windows. The first draft of this file used six
# `src[i:i + N]` slices and tripped the ratchet on the same day I widened it — the
# mechanisms under test are a nested function and one augmented assignment, both of
# which the parser can hand over exactly.
_SRC = inspect.getsource(vf)
_TREE = ast.parse(_SRC)


def _reason_fn_src() -> str:
    for n in ast.walk(_TREE):
        if isinstance(n, ast.FunctionDef) and n.name == "_adv_reason_1202lw":
            return ast.get_source_segment(_SRC, n) or ""
    raise AssertionError("_adv_reason_1202lw is gone — the advisory reason is unexplained again")


def _summary_stmt_src() -> str:
    out = []
    for n in ast.walk(_TREE):
        if (isinstance(n, ast.AugAssign)
                and isinstance(n.target, ast.Name) and n.target.id == "summary"
                and "advisory" in (ast.unparse(n) or "")):
            out.append(ast.unparse(n))
    assert out, "the advisory clause no longer reaches the summary"
    return "\n".join(out)


def test_the_fixed_overlay_label_is_gone():
    """The string survives in the fix's own comment, which QUOTES the r121 log line it
    replaces — so assert it is no longer EMITTED, not that it is absent from the file."""
    emitting = [ln for ln in _SRC.splitlines()
                if "advisory (overlay, non-blocking)" in ln
                and not ln.lstrip().startswith("#")]
    assert not emitting, ("the label is still emitted, not merely quoted: %s" % emitting)


def test_milestone_scope_is_named_as_itself():
    assert "not this milestone's routes (#565)" in _reason_fn_src()


def test_the_existing_advisory_reason_field_is_finally_read():
    """#595-era demotions have been WRITING `advisory_reason` with nothing reading it."""
    assert _SRC.count("advisory_reason") >= 4
    assert "advisory_reason" in _reason_fn_src(), (
        "the reason field is still written-only at the one place a reader looks")


def test_the_reason_function_prefers_scope_then_recorded_then_fallback():
    body = _reason_fn_src()
    i_scope = body.index("_scope_excluded_names")
    i_reason = body.index("advisory_reason")
    i_fallback = body.index("overlay/transient")
    assert i_scope < i_reason < i_fallback, (
        "a screen demoted BY SCOPE must not be reported as an overlay just because it also "
        "lacks a recorded reason")


def test_screens_are_grouped_by_reason_not_listed_flat():
    assert "_adv_groups_1202lw.setdefault" in _SRC
    # `ast.unparse` normalises quoting, so compare on a quote-insensitive form.
    stmt = _summary_stmt_src().replace("'", '"')
    assert '"; ".join(_adv_note)' in stmt, stmt


def test_the_fallback_still_covers_a_genuine_overlay():
    """★ Non-vacuity: login_modal really IS `kind=overlay` in r121's classification, and must
    still be describable."""
    assert 'return "overlay/transient screen"' in _reason_fn_src()


def test_the_reason_is_bounded():
    """A recorded reason is prose from elsewhere; the summary is a log line."""
    assert re.search(r"_why\[:\d+\]", _reason_fn_src()), (
        "an unbounded reason can flood the line")


def test_the_reason_function_is_reached_by_the_grouping():
    """★ Reachability: a helper nothing calls explains nothing."""
    assert "_adv_reason_1202lw(r)" in _SRC
