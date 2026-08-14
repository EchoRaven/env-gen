r"""#726: four wrong claims lived in prose, all green, because nothing reads the prose.

Item 48 found the same failure four times, each a copy of a claim that had been measured false:

    frontend_audit.py            kind='standard' — struck through when #708 measured it
    test_duplicate_route_content_615.py   the SAME claim, in a docstring, alive a day longer
    test_gating_average_divergence_711.py two tests asserting a withdrawn consequence's presence
    test_gate_sees_every_p0_630.py        "Blast radius 4 of 21" — the one claim in item 22's
                                          sweep that does not reproduce, and the justification
                                          for deferring a release

None was an assertion. All four were green the whole time. The tooling added this session reads
code (#716's checker patterns) and the document (#719's cross-references); nothing reads the
sentences in between, which is exactly where these lived.

This guard does. Each entry is a claim this session measured false, with the marker that must
appear near any surviving copy. It cannot judge new claims — only keep the settled ones settled —
which is the honest limit of a text check.
"""
import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SEARCH_DIRS = [ROOT / "env_generator" / "llm_generator", ROOT / "tests"]

# claim substring -> a marker that must appear within RADIUS chars before or after it.
# Add an entry when a measurement overturns something already written down.
OVERTURNED = {
    "kind='standard'": ("~~", "RETIRED", "STALE", "seed_dataset"),
    "Blast radius 4 of 21": ("~~", "does NOT reproduce"),
    "A release authorised on the former ships the latter": ("~~", "RETRACTION", "is WRONG"),
    "a single lucky pass never triggers a release": ("TRUE as written", "#712r", "~~"),
}
RADIUS = 900

# WHY THE REGISTRY IS FOUR AND NOT TWELVE. This session produced twelve retraction commits, so
# four looks thin. It was tested rather than assumed: six more overturned phrasings were run
# through this same sweep — "accelerates rather than tapering", "160 attempts", "did not
# deliver", "the capture list is stale", "routes did not resolve", "clear the checker" — and
# they produced ZERO genuine unmarked copies. Four is adequate for what actually exists in the
# tree, not a starting point someone forgot to finish.
#
# The two apparent hits in that trial were both false alarms, and they show this guard's real
# failure mode: a marker list narrower than the correction's actual wording.
#
#   test_unfinished_run_banner_717.py   the claim sits in a two-column table whose RIGHT column
#                                       is the correction ("it delivered v1.0.0 in the 3,000
#                                       lines after I looked") — marked, just not with the words
#                                       I had guessed
#   visual_fidelity.py                  #718's comment QUOTING #713's sentence in order to
#                                       explain why it is wrong — the quotation trap that has
#                                       bitten four assertions in this session
#
# So when adding an entry, read the correction that is already there and take the markers FROM
# it. Markers invented in advance produce alarms that train a reader to ignore the guard.


def _files():
    for d in SEARCH_DIRS:
        for p in d.rglob("*.py"):
            if p.name == Path(__file__).name:
                continue
            yield p


def _unmarked(claim, markers):
    hits = []
    for p in _files():
        try:
            t = p.read_text(errors="ignore")
        except Exception:
            continue
        for m in re.finditer(re.escape(claim), t):
            window = t[max(0, m.start() - RADIUS):m.end() + RADIUS]
            if not any(mk in window for mk in markers):
                hits.append(f"{p.name}:{t[:m.start()].count(chr(10)) + 1}")
    return hits


# --- the guard ------------------------------------------------------------------------------

@pytest.mark.parametrize("claim,markers", sorted(OVERTURNED.items()))
def test_every_copy_of_an_overturned_claim_carries_its_correction(claim, markers):
    unmarked = _unmarked(claim, markers)
    assert not unmarked, (
        f"{claim!r} was measured false, and these copies state it with no correction within "
        f"{RADIUS} chars — the shape item 48 hit four times: " + ", ".join(unmarked))


@pytest.mark.parametrize("claim", sorted(OVERTURNED))
def test_each_claim_still_appears_somewhere(claim):
    """If a claim vanishes entirely the entry is dead weight — and deleting rather than striking
    through is the thing item 48 argues against, so this notices that too."""
    found = any(claim in p.read_text(errors="ignore") for p in _files())
    assert found, f"{claim!r} is gone from the tree; drop the entry or restore the reasoning"


# --- the guard's own limits, stated ---------------------------------------------------------------

def test_the_registry_is_not_empty():
    assert len(OVERTURNED) >= 4


def test_every_entry_has_at_least_one_marker():
    for claim, markers in OVERTURNED.items():
        assert markers, claim
        assert all(isinstance(m, str) and m for m in markers), claim


def test_it_searches_both_code_and_tests():
    """Three of the four instances were in tests, one in production — both surfaces or nothing."""
    names = {d.name for d in SEARCH_DIRS}
    assert "tests" in names and "llm_generator" in names


def test_the_radius_is_wide_enough_for_a_struck_paragraph():
    """#630's correction runs to several hundred characters; a tight window would miss it."""
    assert RADIUS >= 600


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))


def test_the_guard_is_not_vacuous(tmp_path, monkeypatch):
    """Negative control. A guard over prose is easy to write so that it can never fire — this
    plants an unmarked copy in a scratch directory and requires the sweep to name it."""
    probe = tmp_path / "probe.py"
    probe.write_text(
        '"""A page cannot be filtered: the seed gives every title '
        "kind='standard' here.\"\"\"\n",
        encoding="utf-8")
    monkeypatch.setattr(
        __import__(__name__.split(".")[-1] if "." in __name__ else __name__),
        "SEARCH_DIRS", [tmp_path], raising=False)
    hits = _unmarked("kind='standard'", OVERTURNED["kind='standard'"])
    assert hits and "probe.py" in hits[0], hits


def test_the_control_would_pass_once_marked(tmp_path, monkeypatch):
    """And the same copy, struck through, must stop firing — otherwise the guard is just noise."""
    probe = tmp_path / "probe.py"
    probe.write_text(
        '"""~~the seed gives every title '
        "kind='standard'~~ RETIRED: seed_dataset has movie 28 / series 32.\"\"\"\n",
        encoding="utf-8")
    monkeypatch.setattr(
        __import__(__name__.split(".")[-1] if "." in __name__ else __name__),
        "SEARCH_DIRS", [tmp_path], raising=False)
    assert not _unmarked("kind='standard'", OVERTURNED["kind='standard'"])
