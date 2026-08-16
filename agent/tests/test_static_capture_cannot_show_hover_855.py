r"""#855: the largest deviation class by run count is one no change can satisfy.

Found by mining the RESULTS rather than the source. `deviations` has 7763 entries over 119 runs
but **7537 distinct strings** — the raw templates are almost all unique judge prose, so exact
grouping shows nothing. Clustering by meaning (the "dedupe wordings" rule that once summed a
pagination indicator across five names) re-ranks it completely:

    hover preview card   160 entries / 94 runs   <- #1 by run count
    language selector    117 / 93
    colour / contrast    110 / 68
    blank, never hydrated 90 / 55
    auth guard redirect   43 / 11                <- matches the recorded 43-over-11 exactly

That last row is the instrument's own check: it reproduces a previously-measured figure.

★ Then the decisive question — WHICH SCREEN carries it. **121 of 160 (76%) are on
`browse_by_languages` and `my_list`**, ordinary static catalog pages, not on `card_hover_preview`.
The Netflix reference images depict a card mid-hover; the judge faithfully reports the difference;
`remediation_text` hands it to the lane as a concrete instruction; the lane builds a hover card;
the next static route capture still shows no hover state; the deviation recurs.

#542a already knows a static capture cannot reproduce a hover — but it tests the SCREEN NAME
(`_TRANSIENT_STATE_RE` over `card_hover_preview`), and `my_list` is a perfectly ordinary name, so
it never fires. This is #566z's unsatisfiable-expectation engine at the visual gate.

**Safety, measured the way #660 measured its own drop:** 188 of 7763 lines (2.4%) match;
**0 screens have ALL of their deviations in this shape and 0 BLOCKING screens do**, so nothing is
ever left without an actionable line. Dropped from the INSTRUCTIONS only — the verdict record
keeps every entry, and the builder prints how many it withheld and why, because an erased finding
is #791's defect.
"""
import pytest

from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf


_f = vf._unsatisfiable_by_static_capture_855


def test_the_helper_exists_and_the_regex_is_live():
    """Non-vacuity: a regex that matches nothing would make every positive case below fail open."""
    assert vf._DEMANDS_INTERACTION_855.search("missing hover preview card")


@pytest.mark.parametrize("screen", ["my_list", "browse_by_languages", "new_and_popular",
                                    "genre_category", "browse_home_rows"])
def test_a_hover_demand_on_a_static_page_is_unsatisfiable(screen):
    """The 188 measured lines, on the five screens that actually carry them."""
    assert _f("Missing hover preview card with play/add/like/expand actions", screen)


@pytest.mark.parametrize("screen", ["card_hover_preview", "account_menu", "rate_dialog",
                                    "profile_flyout", "language_dropdown"])
def test_a_hover_demand_on_an_overlay_screen_is_kept(screen):
    """★ The blast radius. On a transient/overlay screen the overlay genuinely should render —
    #509 gives those an interaction capture — and 39 of the hover entries are on
    `card_hover_preview` itself. Suppressing those would hide real defects."""
    assert not _f("Missing hover preview card", screen)


@pytest.mark.parametrize("text", ["Nav order differs from reference",
                                  "Heading casing: 'My List' vs 'MY LIST'",
                                  "route /browse rendered BLANK",
                                  "Missing English language selector next to Sign In"])
def test_ordinary_deviations_are_untouched(text):
    """Non-regression over the other clustered classes — none of them may be swallowed."""
    assert not _f(text, "my_list")


@pytest.mark.parametrize("text", ["shows a hover overlay", "on mouseover the card expands",
                                  "no :hover treatment", "missing on mouse enter preview"])
def test_the_other_spellings_are_caught(text):
    """The judge is free prose; one spelling is not a detector."""
    assert _f(text, "my_list")


def test_hoverboard_is_not_a_hover_demand():
    """Word boundary. `\\bhover\\b` must not fire on an unrelated token — the substring form of
    this check is what made 'latest' hit 'test' in the seed audit."""
    assert not _f("the hoverboard product tile is missing", "my_list")


# --- the builder ---------------------------------------------------------------------------------

def _body(devs):
    """The screen record's key is `name`, not `screen` — the builder does `r['name']` and
    `r['route']`. The first fixture here used `screen` and every builder case died on a KeyError
    rather than on the behaviour under test, which is the same field-location trap that produced
    two wrong zeros earlier in this session, this time in a fixture instead of a probe."""
    r = {"name": "my_list", "route": "/my-list", "similarity": 0.4, "passed": False,
         "deviations": devs, "dimensions": {}, "fixes": []}
    return vf.remediation_text({"screens": [r]}, output_dir=None)


def test_the_instruction_list_drops_them_and_says_so():
    """Not silently. An erased finding is #791's defect; the lane must be told the note exists and
    is not work, or the next round re-reports it as an unaddressed deviation."""
    out = _body(["Nav order differs from reference",
                 "Missing hover preview card with play/add actions"])
    assert "Nav order differs" in out
    assert "Missing hover preview card" not in out
    assert "HOVER/interaction state" in out and "not work" in out


def test_a_screen_keeps_its_actionable_lines():
    """The #660 safety test, as a case: 0 screens had ALL deviations in this shape, so a screen
    must never come back with an empty Differences block."""
    out = _body(["Nav order differs from reference", "Heading casing wrong"])
    assert "Differences (where + what):" in out
    assert "HOVER/interaction" not in out


def test_the_all_unsatisfiable_screen_still_gets_the_explanation():
    """Measured as 0 of 1404 screen records, but if it ever happens the lane must not receive a
    bare screen heading with nothing under it."""
    out = _body(["Missing hover preview card"])
    assert "HOVER/interaction state" in out
    assert "Differences (where + what):" not in out


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
