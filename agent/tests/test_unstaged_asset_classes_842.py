r"""#842: the spec asks for an asset class design-prep never stages — and nothing compared them.

#841 found that no avatar is ever staged, so the lane (owning seed_data.json, told to author
realistic data, with nothing to point at) filled `avatar_url` with a crop of a flyout panel. The
judge correctly reports a blank square on my_list, new_and_popular and movies — and the avatar is
in the SHARED TOP NAV, so it costs `components` on every authenticated screen.

#788 established that `must_have` is never machine-checked. This is the half of it that can be
checked without semantics:

    must_have prose  "profile avatars grid" | "profile avatar dropdown"
    staged           backdrops | brand | fonts | icons | posters | video

★ **A closed vocabulary on both sides is what makes it sound.** #823 withdrew two versions that
matched SCREEN names against ROUTE names — two open vocabularies, and both versions reported
screens that were built. Asset classes are a short fixed list and the staged side is a handful of
directory names, so the same narrowing that rescued #823 applies here by construction.

Measured over 151 corpus runs it reports `avatar` and nothing else. An earlier cut also reported
`logo`, which was a **false positive**: the wordmark is staged under `brand/`, not `logo/`. That
one word is the whole difference between a useful report and the noise #823 was withdrawn for.

It does NOT cover #840's gap — that is a missing entity KIND in the dataset (no games), not a
missing asset class. A sibling check, not this one.
"""
import pathlib

import pytest

from env_generator.llm_generator.multi_agent.runtime.delivery_gate import (
    _unstaged_asset_classes_842 as check)


_GEN = pathlib.Path(__file__).resolve().parents[1] / "generated"


def _run(name):
    p = _GEN / name
    if not (p / "design" / "assets").is_dir():
        pytest.skip(f"{name} not present")
    return p


@pytest.mark.parametrize("name", ["netflix-web-r151", "netflix-web-r150", "netflix-web-r141"])
def test_the_avatar_gap_is_reported(name):
    got = check(_run(name))
    assert got == ["avatar (asked by profiles)"], got


def test_it_says_which_screen_asked():
    """'avatar is missing' sends the reader looking; naming the screen ends it (#798's rule)."""
    assert "asked by" in check(_run("netflix-web-r151"))[0]


def test_the_wordmark_under_brand_is_not_a_false_positive():
    """★ The one word that separates this from #823's withdrawn versions. must_have says "logo";
    the asset is staged as `brand/netflix_wordmark.svg`. An earlier cut reported it 150/150."""
    assert not any("logo" in x for x in check(_run("netflix-web-r151")))


def test_the_corpus_reports_exactly_one_class():
    """Non-vacuity plus noise-freedom in one: it must find the real gap and nothing else."""
    if not _GEN.is_dir():
        pytest.skip("no corpus")
    seen, runs = set(), 0
    for p in sorted(_GEN.iterdir()):
        if not (p / "design" / "assets").is_dir():
            continue
        runs += 1
        seen |= {x.split(" (")[0] for x in check(p)}
    assert runs >= 100, runs
    assert seen == {"avatar"}, seen


@pytest.mark.parametrize("bad", ["/nope", None, ""])
def test_faults_are_silent(bad):
    """It runs on the release path and must never invent a blocker."""
    assert check(bad) == []


def test_it_is_reported_not_enforced():
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import delivery_gate as dg
    src = inspect.getsource(dg.validate_delivery_gate)
    assert "_unstaged_asset_classes_842" in src
    assert 'failed_checks.append("unstaged_asset_class")' not in src


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
