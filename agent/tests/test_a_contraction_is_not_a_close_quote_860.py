r"""#860: the quoted-title capture cut every heading at its first apostrophe.

`_section_title_221` returns a quoted span verbatim because a quoted span is curated copy. Its
pattern was one character class doing two jobs — delimiter AND body exclusion:

    ['‘’“”"]([^'‘’“”"]{2,60})['‘’“”"]

so a straight `'` inside the span closed it. Measured against the corpus design systems — these
are headings the framework **shipped**, not hypotheticals:

    "thumbs-down icon with caption 'We won't suggest this to you again'"  ->  'We won'      144 runs
    "thumbs-up icon with caption 'We'll show you more like this'"         ->  'We'          144 runs
    "double thumbs-up icon with caption 'We know you're a true fan!'"     ->  'We know you' 141 runs
    "breadcrumb ('TV Shows >') and page H1 'Sports TV Shows'"             ->  'TV Shows >'  142 runs

★ **The corpus also killed the fix I was about to write.** The visible defect was placeholder
headings (`'hover preview card'`, `'page title'`, `'row2 label tv comedies'`), and the obvious
move was to run quoted candidates through #432/#459's rejection filters, which the unquoted path
already applies. Pulling the actual list of quoted titles that ship shows they are overwhelmingly
real curated copy — `'Browse by Languages'` (147 runs), `'Only on Netflix'`, `'New on Netflix'`,
`'My List'`, `'Your Next Watch'`, `'TV Comedies'`. That filter would have deleted every one of
them. **The hypothesis was reasonable, cheap to test, and wrong** — and the apostrophe bug was
only visible *because* I listed the real values instead of filtering them.

Both rules here are delimiter-shaped, not content-shaped, so no legitimate title can be caught by
them: the close must match the open, and a straight `'` closes only when the next character is
not a letter — exactly what separates `won't` from a closing quote.
"""
import pytest

from env_generator.llm_generator.multi_agent.runtime import frontend_scaffold as fs


_f = fs._section_title_221


def test_the_extractor_is_wired():
    """Non-vacuity: a rename would make every case below pass on ''."""
    assert _f("rail titled 'Only on Netflix'") == "Only on Netflix"


@pytest.mark.parametrize("role,want", [
    ("thumbs-down icon with caption 'We won't suggest this to you again'",
     "We won't suggest this to you again"),
    ("thumbs-up icon with caption 'We'll show you more like this'",
     "We'll show you more like this"),
    ("double thumbs-up icon with caption 'We know you're a true fan!'",
     "We know you're a true fan!"),
])
def test_a_contraction_does_not_close_the_quote(role, want):
    """The three real roles, at 144 / 144 / 141 runs."""
    assert _f(role) == want


@pytest.mark.parametrize("role,want", [
    ("caption 'Today's Top Picks'", "Today's Top Picks"),
    ("rail 'What's New'", "What's New"),
])
def test_a_singular_possessive_survives_too(role, want):
    """`Today's` is a contraction-shaped apostrophe (letter follows), so the same rule covers it."""
    assert _f(role) == want


def test_a_title_ending_in_a_plural_noun_closes_there():
    r"""★ The case that nearly cost 290+ real titles. A PLURAL possessive (`'Kids' Shows'`) is
    genuinely ambiguous — no rule settles it from the text — and my first test asserted the
    human reading. Checking the corpus first showed the `s' ` pattern occurs 1483 times and is
    almost entirely **a title ending in a plural noun plus its closing quote**: `'TV Shows'`
    (290), `'Select Your Preferences'` (258), `'Movies'` (189), `'Episodes'` (185), `'Games'`
    (166). Stopping at that quote is REQUIRED, and a greedy rule would have swallowed the rest of
    the sentence on every one of them.

    So the ambiguous case is left ambiguous on purpose, and the test asserts the behaviour the
    data demands. The probe that found this also had to be corrected — `[A-Za-z]+s'\s` matches a
    possessive and a closing quote identically, which is why the count had to be READ rather than
    trusted."""
    assert _f("header 'TV Shows' and a subtitle") == "TV Shows"
    assert _f("rail 'Select Your Preferences' below the hero") == "Select Your Preferences"
    assert _f("two rails 'Today' and 'Tomorrow'") == "Today"


@pytest.mark.parametrize("title", ["Browse by Languages", "Only on Netflix", "New on Netflix",
                                   "My List", "Your Next Watch", "TV Comedies", "Recently Added",
                                   "Top 10 (This Week)", "Select Your Preferences"])
def test_the_real_curated_titles_are_untouched(title):
    """★ Non-regression against the corpus's actual shipped headings — the list that refuted the
    first version of this fix. 147 runs depend on the top entry alone."""
    assert _f(f"section title for '{title}'") == title


@pytest.mark.parametrize("role,want", [
    ("crumb 'Movies ›'", "Movies"),
    ("crumb 'Shows »'", "Shows"),
    ("crumb 'New & Popular >'", "New & Popular"),
])
def test_a_breadcrumb_chevron_is_not_part_of_the_heading(role, want):
    """The chevron strip, on roles with a SINGLE quoted span. The two-span case moved to #875."""
    assert _f(role) == want


def test_the_breadcrumb_no_longer_beats_the_page_h1_875():
    """★ This case used to assert `'TV Shows'` — the BREADCRUMB — because that is what first-wins
    produced, and #860 recorded it as *"the text does not settle which"*. #875 measured that
    claim: of 458 roles with two or more quoted spans, **160 carry a positional cue**, and the
    span nearest the cue is the heading. The old expectation was this file pinning a defect its
    own write-up had named."""
    assert _f("breadcrumb ('TV Shows >') and page H1 'Sports TV Shows'") == "Sports TV Shows"


def test_a_title_that_merely_contains_an_arrow_word_is_safe():
    """The strip is anchored to the END, so an internal separator survives."""
    assert _f("rail 'Action & Adventure'") == "Action & Adventure"
    assert _f("rail 'Top 10 / Trending'") == "Top 10 / Trending"


@pytest.mark.parametrize("role", ["hover preview card", "page title", "row2 label tv comedies",
                                  "first content", "poster cards for"])
def test_unquoted_component_descriptions_are_still_rejected(role):
    """#432/#459 still own the unquoted path; #860 changed only the capture."""
    assert _f(role) == ""


@pytest.mark.parametrize("role", ["", "no quotes here", "a 'x' too short", "''"])
def test_degenerate_input_returns_empty_or_falls_through(role):
    out = _f(role)
    assert isinstance(out, str)
    assert "'" not in out[:1]


def test_typographic_quotes_pair_correctly():
    """Curly quotes are unambiguous and must not be affected by the apostrophe rule."""
    assert _f("rail “Only on Netflix”") == "Only on Netflix"
    assert _f("rail ‘Only on Netflix’") == "Only on Netflix"


def test_a_curly_apostrophe_inside_straight_quotes_survives():
    """The mixed case the analyst actually produces."""
    assert _f("caption 'We won’t suggest this'") == "We won’t suggest this"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
