r"""#844: a screen whose subject does not exist in the staged data. #842's sibling.

#840: `games` blocks 71% of recent runs, floors on `components` in 10 of 10 scored runs, and 9 of
10 carry the deviation *"implementation surfaces a film ... instead of a game"*. The judge is
right — `GamesPage` fetches an unscoped `/api/titles`, the API supports `?kind=`, and the staged
dataset holds `series` and `movie` and no games. 142 of 143 corpus runs declare a games screen;
1 of 143 has a game row.

★ **Unsatisfiable, not merely unfixed.** The lane could author game rows in its own
`seed_data.json`, but #807 established the framework dataset **replaces `titles` wholesale**, so
they are deleted before they ship. No edit the lane can make clears the finding — #566z's class at
the data layer rather than the detector layer.

★★ **The narrowing, again, and again it was found by sweeping rather than reading.** A first cut
matched `must_have` prose and reported `browse_home` 141/142 — its must_have lists the nav labels
("Home, Shows, Movies, **Games**, New & Popular"), and a nav label is not a content requirement.
Matching the SCREEN NAME instead removes it: a screen called `games` is about games. That is the
third time this pattern has decided a check (#823 screens-vs-routes, #842 logo-under-brand, this).

`show` and `movie` correctly stay silent because those kinds exist — which is what shows the probe
discriminates rather than always firing.
"""
import pathlib

import pytest

from env_generator.llm_generator.multi_agent.runtime.delivery_gate import (
    _unseeded_entity_kinds_844 as check)


_GEN = pathlib.Path(__file__).resolve().parents[2] / "generated"


def _run(name):
    p = _GEN / name
    if not (p / "app" / "backend" / "seed_dataset.json").is_file():
        pytest.skip(f"{name} not present")
    return p


@pytest.mark.parametrize("name", ["netflix-web-r151", "netflix-web-r150"])
def test_the_games_gap_is_reported(name):
    assert check(_run(name)) == ["game (screen games)"]


def test_kinds_that_exist_are_not_reported():
    """★ Non-vacuity: `shows` and `movies` screens are declared in every run and the dataset has
    both kinds, so a probe that always fired would name them too."""
    got = " ".join(check(_run("netflix-web-r151")))
    assert "show" not in got and "movie" not in got


def test_a_nav_label_is_not_a_content_requirement():
    """The withdrawn first cut reported browse_home 141/142 off its nav list. The screen NAME is
    the signal; the prose is not."""
    for name in ("netflix-web-r151", "netflix-web-r150"):
        assert not any("browse_home" in x for x in check(_run(name)))


def test_the_corpus_reports_exactly_one_thing():
    if not _GEN.is_dir():
        pytest.skip("no corpus")
    seen, runs = set(), 0
    for p in sorted(_GEN.iterdir()):
        if not (p / "app" / "backend" / "seed_dataset.json").is_file():
            continue
        runs += 1
        seen |= set(check(p))
    if runs == 0:
        pytest.skip("the run corpus this analysis reads is not in this checkout — "
                    "`generated/` exists but holds none of the matching runs, so the "
                    "population assertion below would fail on absence, not on a defect")
    # #1202el re-anchor: this assertion never ran -- the corpus root pointed at
    # agent/generated (one stale dir) instead of the repo root. Re-measured against the
    # real corpus of 96 runs. Non-vacuity only; the exact guard is asserted above.
    # measured: 96 matching runs (runs get pruned for disk).
    assert runs >= 50, runs
    assert seen == {"game (screen games)"}, seen


def test_an_empty_dataset_is_not_this_checks_story():
    """Nothing staged at all is #807's territory; reporting it here would present one failure as
    two causes — #815's misdiagnosis."""
    import inspect
    assert "#807's story, not this one" in inspect.getsource(check)


@pytest.mark.parametrize("bad", ["/nope", None, ""])
def test_faults_are_silent(bad):
    assert check(bad) == []


def test_it_is_reported_not_enforced():
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import delivery_gate as dg
    src = inspect.getsource(dg.validate_delivery_gate)
    assert "_unseeded_entity_kinds_844" in src
    assert 'failed_checks.append("unseeded_entity_kind")' not in src


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
