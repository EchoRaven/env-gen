"""#1203kc: the two halves #1203kb left — and a comment of mine that was false.

#1203kb withheld the "consider reverting it" order when a screen in this round had no
photograph. Two things were wrong with it:

1. Its comment said the MIRROR case (the previous round holding the uncaptured screens, so
   "your last round helped" credits the lane for the harness recovering) was "out of reach
   here because this function receives `prev_live` as a NUMBER". The caller computes
   `_this_live` from `screens` and stores it as `_prev_live_average` on the same line — it is
   holding the screens at the moment it remembers the number. The claim was checkable in two
   tool calls and shipped unchecked; a false sentence in the framework is its own defect
   (#1203j2).

2. It counted EVERY screen. The blocking average excludes `advisory` and `blank` ones, so one
   of those cannot have moved the number, and excusing a drop it could not have caused trades
   the false accusation for a MISSED regression. 35 of 146 corpus screens are advisory.

Mirror case measured by pairing each run's consecutive visual tasks: 22 cases, 3 modern
(r159, r162, r166); netflix-r34 reported 0.03 → 0.48 after a round that lost three shots.
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


def _head(screens, prev, now, rnd=2, prev_unshot=None):
    return VF.remediation_text({"screens": screens, "min_similarity": 0.6}, None,
                               prev_live=prev, this_live=now, round_no=rnd,
                               prev_unshot=prev_unshot).split("\n\n", 1)[0]


_NO_SHOT = {"capture_missing": True,
            "capture_error": "TimeoutError: Page.goto: Timeout 20000ms exceeded"}
_SHOT_BAD = _screen("explore_grid", 0.31)


# --- the narrowing: a screen that cannot move the average cannot excuse a move in it -----

def test_an_advisory_unphotographed_screen_does_not_excuse_the_drop_1203kc():
    adv = _screen("account_menu", 0.0, advisory=True, **_NO_SHOT)
    head = _head([adv, _SHOT_BAD], 0.36, 0.00)
    assert "YOUR LAST ROUND MADE THIS WORSE" in head, (
        "#1203kc: an advisory screen is excluded from the blocking average (the caller's "
        "`_lb`), so it cannot have caused this drop. Excusing it would trade #1203kb's false "
        "accusation for a MISSED regression.\n" + head)


def test_a_blank_unphotographed_screen_does_not_excuse_the_drop_1203kc():
    blank = _screen("live_discover", 0.0, blank=True, **_NO_SHOT)
    head = _head([blank, _SHOT_BAD], 0.36, 0.00)
    assert "YOUR LAST ROUND MADE THIS WORSE" in head, head


def test_the_same_screen_without_the_flags_still_arms_1203kb_1203kc():
    """NON-VACUITY for both tests above: the filter is what changed the answer, not the
    fixture. Same screen, no advisory/blank -> #1203kb must still fire."""
    plain = _screen("live_discover", 0.0, **_NO_SHOT)
    head = _head([plain, _SHOT_BAD], 0.36, 0.00)
    assert "do NOT revert anything on this number" in head, head
    assert "live_discover" in head, head


def test_the_predicate_has_one_owner_1203kc():
    f = VF._unshot_blocking_1203kc
    assert f([{"name": "a", "capture_missing": True}]) == ["a"]
    assert f([{"name": "a", "capture_error": "boom"}]) == ["a"]
    assert f([{"name": "a", "capture_missing": True, "advisory": True}]) == []
    assert f([{"name": "a", "capture_missing": True, "blank": True}]) == []
    assert f([{"name": "a"}]) == []
    assert f(None) == [] and f([]) == [] and f(["not a mapping"]) == []


# --- the mirror case ---------------------------------------------------------------------

def test_a_gain_after_a_round_that_lost_shots_is_not_a_confirmation_1203kc():
    head = _head([_SHOT_BAD], 0.03, 0.48, prev_unshot=["a", "b", "c"])
    assert "Keep going in the same direction" not in head, (
        "#1203kc: the previous round's average was depressed by the harness, so this gain is "
        "partly it recovering — 'keep going in the same direction' is a false "
        "confirmation.\n" + head)
    assert "PREVIOUS round" in head and "3 screen(s)" in head, head
    # the gain itself is still reported — withholding the confirmation is not hiding the fact
    assert "0.03" in head and "0.48" in head and "+0.45" in head, head
    assert "a, b, c" in head, "name them, or the lane cannot check the claim"


def test_a_clean_gain_keeps_the_original_sentence_1203kc():
    head = _head([_SHOT_BAD], 0.48, 0.61, rnd=8, prev_unshot=[])
    assert head == ("Round 8. Your last round helped: blocking average 0.48 → 0.61 "
                    "(+0.13). Keep going in the same direction."), repr(head)


def test_the_mirror_does_not_touch_a_drop_1203kc():
    """A previous round that lost shots says nothing about a FALL this round."""
    head = _head([_SHOT_BAD], 0.50, 0.40, prev_unshot=["a"])
    assert "YOUR LAST ROUND MADE THIS WORSE" in head, head


# --- the cross-round store, which is where the behaviour actually lives ------------------
#
# A mutation that made the caller forget (`self._prev_unshot_1203kc = []`) survived every
# test above: they hand `prev_unshot` straight to `remediation_text`, so none of them ever
# exercised the wiring, and the branch could have been dead in production with the suite
# green. That is why the store is a named seam now.

class _FakeGate1203kc:
    """Just enough of VisualFidelityGate to drive the swap; `self` is all the method uses."""
    _remember_unshot_1203kc = VF.VisualFidelityGate._remember_unshot_1203kc


def test_the_first_round_has_no_previous_and_says_so_1203kc():
    g = _FakeGate1203kc()
    assert g._remember_unshot_1203kc([_screen("a", 0.5)]) is None, (
        "None means 'there was no previous round'; [] would mean 'it lost nothing' (#771b)")


def test_the_store_hands_the_previous_round_forward_1203kc():
    g = _FakeGate1203kc()
    lost = [_screen("live_discover", 0.0, **_NO_SHOT), _screen("ok", 0.7)]
    clean = [_screen("live_discover", 0.62), _screen("ok", 0.7)]
    assert g._remember_unshot_1203kc(lost) is None          # round 1
    assert g._remember_unshot_1203kc(clean) == ["live_discover"], (
        "round 2 must receive round 1's unphotographed screens — this is the fact the "
        "mirror branch needs and the only place it can come from")
    assert g._remember_unshot_1203kc(clean) == [], (
        "round 3 must see that round 2 lost nothing, not round 1's stale list")


def test_the_store_applies_the_same_narrowing_1203kc():
    g = _FakeGate1203kc()
    g._remember_unshot_1203kc([_screen("account_menu", 0.0, advisory=True, **_NO_SHOT)])
    assert g._prev_unshot_1203kc == [], (
        "one owner for the predicate (#1032): an advisory screen is excluded on both sides")
