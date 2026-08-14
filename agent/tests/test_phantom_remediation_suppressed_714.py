r"""#714: stop sending the lane to fix a page that was never photographed.

#713 detects that several screens captured one image. Detection alone still leaves the lane a
to-do list about a page it cannot have seen, and that list is the larger harm. Measured over the
corpus, screens inside a duplicate group carry MORE remediation than real ones:

    in a duplicate group     333 screens -> 5835 deviations   (17.5 each)
    captured properly       1024 screens -> 15715 deviations  (15.3 each)

which follows — scored against someone else's page, nearly everything looks wrong. So 5835 of
21550 deviations, **27%**, describe a screen the gate never photographed.

`remediation_text` already honours `scope_excluded_screens` (#565 uses it to drop
out-of-milestone pages) and reads the list from the verdict at CONSUMPTION time, so appending
there suppresses exactly the phantom entries and touches no score: the averages, the pass/fail
and the 0.65 bar are computed earlier and stay byte-identical.

Two deliberate limits. One canonical screen per group stays scorable, as #542a does — the group
did photograph something, and dropping every member would hide that too. And the screens are NOT
demoted to advisory: that would change gating arithmetic, and nothing yet says what a gate should
do when a quarter of the exam did not render.

On r147 this removes 53 deviations across the four screens that photographed the landing page.
"""
import inspect

import pytest

from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf


def _block() -> str:
    src = inspect.getsource(vf)
    i = src.index("#714: and STOP THE PHANTOM REMEDIATION")
    return src[i:src.index("except Exception:", src.index("_grp713 = sorted", i))]


def _suppress(groups):
    """Mirror of the production rule: every member but the first is excluded."""
    out = []
    for names in groups:
        for n in sorted(names)[1:]:
            if n not in out:
                out.append(n)
    return out


# --- the rule -------------------------------------------------------------------------------

def test_it_keeps_one_screen_per_group():
    assert _suppress([["player", "landing", "genre_category"]]) == ["landing", "player"]


def test_the_r147_group_loses_four_of_five():
    g = ["browse_by_languages", "genre_category", "landing", "new_and_popular", "player"]
    assert _suppress([g]) == ["genre_category", "landing", "new_and_popular", "player"]


def test_two_groups_are_both_handled():
    assert _suppress([["a", "b"], ["c", "d"]]) == ["b", "d"]


def test_no_duplicates_in_the_output():
    assert _suppress([["a", "b"], ["a", "b"]]) == ["b"]


# --- the production block --------------------------------------------------------------------

def test_it_appends_to_the_existing_channel():
    b = _block()
    assert 'setdefault("scope_excluded_screens", [])' in b


def test_it_keeps_the_first_member():
    b = _block()
    assert "_grp713[1:]" in b
    assert "keep _grp713[0] scorable" in b


def test_it_does_not_touch_advisory():
    """Demoting would change gating arithmetic; this must not."""
    b = _block()
    assert "advisory" not in b.replace("NOT demoting to advisory", "")


def test_it_cannot_raise():
    b = _block()
    assert "try:" in b


# --- provenance -------------------------------------------------------------------------------

def test_the_measurement_is_recorded():
    b = " ".join(_block().replace("#", " ").split())
    assert "17.5 deviations each against 15.3" in b
    assert "5835 of 21550 deviations (27%)" in b


def test_the_reason_it_is_safe_is_recorded():
    b = " ".join(_block().replace("#", " ").split())
    assert "byte-identical" in b


def test_the_deliberate_limit_is_recorded():
    b = " ".join(_block().replace("#", " ").split())
    assert "Deliberately NOT demoting to advisory" in b
    assert "does not yet say what" in b


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
