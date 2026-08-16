r"""#823: the one screen class nothing checks — and two wrong versions before the sound one.

#822: a spec screen with no reference image is absent from `design_system.json`, so the visual
gate never captures, scores or blocks on it (`profiles`, 150 of 150 runs). #788: nothing compares
the spec's `screens` list to the built UI. For exactly those screens there is **no check at all**,
and 22 of 142 corpus runs (15%) shipped with no reachable who's-watching screen.

★ **Two earlier versions were withdrawn, and why is the point.**

1. *"Does `route_hint` exist as a literal path?"* — reported `new_and_popular` because the lane
   routed it `/latest`. The screen exists; only the name differs. An unsatisfiable finding
   (#566z/#820): the lane cannot clear it by building anything.
2. *"Does any route share stemmed tokens with the screen?"* — still reported `landing` (routed
   `/`), `shows`, `title_detail`. Same cause: the spec's names and the app's route vocabulary are
   two different vocabularies.

**The narrowing is the fix, not a better regex.** Screens WITH an image are already covered by the
visual gate, so checking them structurally adds only vocabulary noise. Checking exclusively the
imageless ones removes the entire class: over 142 runs it reports `profiles` (22) and `search` (1)
and nothing else.

A blind probe reports `<unknown: no App.jsx>`, never `[]` — 8 corpus runs are in that state, and
"clean" would be a lie about the instrument.
"""
import pathlib

import pytest

from env_generator.llm_generator.multi_agent.runtime.delivery_gate import (
    _imageless_spec_screens_unreachable_823 as check)


_GEN = pathlib.Path(__file__).resolve().parents[1] / "generated"


def _run(name):
    p = _GEN / name
    if not (p / "design" / "reference_spec.json").is_file():
        pytest.skip(f"{name} not present")
    return p


@pytest.mark.parametrize("name", ["netflix-web-r151", "netflix-web-r141", "netflix-web-r147"])
def test_a_run_that_builds_profiles_is_clean(name):
    assert check(_run(name)) == []


def test_a_run_that_does_not_build_it_is_reported():
    """r150 has no ProfilesPage.jsx and no /profiles route — independently verified."""
    got = check(_run("netflix-web-r150"))
    assert got and got[0].startswith("profiles (")


def test_a_missing_app_jsx_is_unknown_not_clean():
    """★ The instrument rule. 8 corpus runs have no App.jsx; reporting [] would call them clean."""
    got = check(_run("netflix-web-r140"))
    assert got == ["<unknown: no App.jsx to check reachability against>"]


def test_screens_with_an_image_are_never_reported():
    """★ The narrowing, asserted directly: the noisy names from the two withdrawn versions must
    not come back. They are covered by the visual gate and are not this check's business."""
    for name in ("netflix-web-r151", "netflix-web-r141", "netflix-web-r150"):
        got = " ".join(check(_run(name)))
        for noisy in ("landing", "shows", "title_detail", "new_and_popular", "movies"):
            assert noisy not in got, (name, noisy)


def test_reachability_counts_page_files_not_only_routes():
    """`/profiles` and `ProfilesPage.jsx` are both evidence; requiring the route alone would flag
    an app that renders the screen through a differently-named path."""
    import inspect
    src = inspect.getsource(check)
    assert "pages" in src and "_tok(_f.stem)" in src


@pytest.mark.parametrize("bad", ["/nope", None, ""])
def test_faults_are_silent_not_noisy(bad):
    """This runs on the release path; it must never raise and never invent a blocker."""
    assert check(bad) == []


def test_it_is_reported_not_enforced():
    """Switching it on is #774's class of decision and is not mine to make."""
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import delivery_gate as dg
    src = inspect.getsource(dg.validate_delivery_gate)
    assert "_imageless_spec_screens_unreachable_823" in src
    assert 'failed_checks.append("imageless_spec_screen_unreachable")' not in src


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
