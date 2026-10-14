"""#1203kb: the visual task ordered a revert on a drop the harness caused.

#768 is explicit that a screen the harness never photographed "scored a hard 0.00 that
COUNTED". That zero lands in the blocking average, so #619's delta reads it as the lane's
regression and the FIRST LINE of the remediation task says "consider reverting" the round
that caused it — while the same task, further down, says "produced NO capture this pass …
This is not a verdict on the page".

Measured over the whole corpus: 511 visual remediation tasks, 82 carry the accusation, and
34 of those also report an unphotographed screen (r181 0.36 → 0.00 on one, netflix-r21
0.74 → 0.07 on three). "Revert the round that touched this" is an instruction, and the round
it points at may have been correct work.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime import visual_fidelity as VF  # noqa: E402


def _screen(name, sim, **kw):
    s = {"name": name, "route": "/" + name, "similarity": sim, "passed": sim >= 0.6,
         "dimensions": {}, "deviations": [], "fixes": []}
    s.update(kw)
    return s


def _result(screens):
    return {"screens": screens, "min_similarity": 0.6}


def _body(screens, prev, now, rnd=2):
    return VF.remediation_text(_result(screens), output_dir=None,
                               prev_live=prev, this_live=now, round_no=rnd)


# The three shapes, by what the round actually knows:
#   A: a screen took no photograph  -> the number is unattributable -> no revert order
#   B: every screen was captured    -> a real regression            -> the order stands
#   C: the average went UP          -> untouched by this patch
_UNSHOT = _screen("fyp_feed_comments_panel", 0.0, capture_missing=True,
                  capture_error="TimeoutError: Page.goto: Timeout 20000ms exceeded")
_SHOT_BAD = _screen("explore_grid", 0.31)
_SHOT_OK = _screen("login_modal", 0.78)


def test_a_drop_with_an_unphotographed_screen_does_not_order_a_revert_1203kb():
    body = _body([_UNSHOT, _SHOT_BAD], 0.36, 0.00)
    head = body.split("\n\n", 1)[0]
    assert "YOUR LAST ROUND MADE THIS WORSE" not in head, (
        "#1203kb: an unphotographed screen counts 0.00 (#768), so this drop is not "
        "attributable to the lane and must not be announced as its regression.\n" + head)
    assert "do NOT revert anything on this number" in head, head
    # it must still REPORT the drop — withholding the order is not withholding the fact
    assert "0.36" in head and "0.00" in head and "-0.36" in head, head
    # and it must name the screen that was not photographed, or the lane cannot check it
    assert "fyp_feed_comments_panel" in head, head
    assert "#768" in head, "cite the rule that makes an unphotographed screen a 0.00"


def test_a_real_regression_still_gets_the_revert_order_1203kb():
    """The half that must NOT change: with every screen captured, the accusation stands."""
    body = _body([_SHOT_BAD, _SHOT_OK], 0.36, 0.00)
    head = body.split("\n\n", 1)[0]
    assert "YOUR LAST ROUND MADE THIS WORSE" in head, (
        "#1203kb must not soften a drop the lane really caused — that would trade a false "
        "accusation for a missed regression (the #1202xc shape).\n" + head)
    assert "consider reverting it" in head, head


def test_the_text_is_unchanged_when_every_screen_was_captured_1203kb():
    """Byte-identical to the pre-patch sentence, so nothing else re-learns this wording."""
    body = _body([_SHOT_BAD, _SHOT_OK], 0.50, 0.40, rnd=3)
    assert body.startswith(
        "Round 3. ⚠ YOUR LAST ROUND MADE THIS WORSE: the blocking average went "
        "0.50 → 0.40 (-0.10). Before changing anything else, look at what that round "
        "touched and consider reverting it — the screens listed below are scored on the "
        "CURRENT code.\n\n"), repr(body[:260])


def test_an_improvement_is_untouched_by_this_patch_1203kb():
    body = _body([_UNSHOT, _SHOT_OK], 0.20, 0.40)
    head = body.split("\n\n", 1)[0]
    assert "Your last round helped" in head, head
    assert "do NOT revert" not in head, (
        "the patch is scoped to the DROP branch; an uncaptured screen must not rewrite the "
        "improvement message\n" + head)


def test_a_capture_error_alone_is_enough_1203kb():
    """#935 records the exception without #768's flag on some paths; either one means the
    round has no photograph to judge, so both have to arm this."""
    only_err = _screen("live_discover", 0.0,
                       capture_error="Error: Page.screenshot: Target page closed")
    head = _body([only_err, _SHOT_BAD], 0.40, 0.10).split("\n\n", 1)[0]
    assert "do NOT revert anything on this number" in head, head
    assert "live_discover" in head, head
