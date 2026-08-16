r"""#875: "the text does not settle which" was too strong — 160 of 458 roles settle it.

Third deferral audited. #860 recorded the breadcrumb-beats-H1 case as unfixable: *"which of two
quoted spans is the title is a judgement the text does not settle."* Measured over the corpus
design systems:

    roles with 2+ quoted spans                                 458
    ...carrying a positional cue (H1 / page title / heading)   160   (35%)

★ And the cue's SIDE varies, which is what makes the naive rule wrong:

    breadcrumb ('TV Shows >') and page H1 'Sports TV Shows'    cue BEFORE its span
    'Episodes' section title on left with season selector …    cue AFTER its span

"Take the span after the cue" would pick the season selector in the second.

★ **And "nearest the cue" is wrong too** — the test below caught it. In
`breadcrumb 'Home >' and section title 'Action Movies'` the cue sits *between* the two spans, 15
characters from one and 16 from the other, and the right answer is the far one. The rule is
**adjacency**: a cue with nothing but whitespace before it labels the PRECEDING span; otherwise it
announces the NEXT one. The 298 roles with no cue keep #860's first-wins behaviour byte-identical.

★ **The old expectation was pinned in #860's own test file** — it asserted `'TV Shows'`, the
breadcrumb, because that is what first-wins produced. A test encoding a defect its own write-up had
already named; corrected alongside this.

**Item 185 audited in the same pass and its reason SURVIVED**: the only title-art-ish asset staged
anywhere is `netflix-wordmark` (149 runs), which `_brand_logo_url` already renders. There is no
per-title branded art in the corpus, so *"deferred for a missing input"* holds. Three deferrals
checked, two reasons refuted, one confirmed — which is the point of checking rather than assuming
either way.
"""
import pytest

from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    _section_title_221 as _f)


def test_a_cue_before_its_span_wins():
    """The r95-shaped role that motivated #860's deferral."""
    assert _f("breadcrumb ('TV Shows >') and page H1 'Sports TV Shows'") == "Sports TV Shows"


def test_a_cue_after_its_span_wins():
    """★ Why 'the span after the cue' is the wrong rule."""
    assert _f("'Episodes' section title on left with season selector 'The Hawk' on right") \
        == "Episodes"


@pytest.mark.parametrize("cue", ["page H1", "H1", "page title", "section title", "heading",
                                 "page header"])
def test_every_cue_word_is_recognised(cue):
    assert _f(f"breadcrumb 'Home >' and {cue} 'Action Movies'") == "Action Movies"


def test_no_cue_keeps_first_wins():
    """★ Non-regression for the 298 roles without a cue: #860's behaviour, unchanged."""
    assert _f("Primary CTA 'Play Game' (light) and secondary 'More Info' (translucent)") \
        == "Play Game"


def test_a_single_span_is_unaffected_by_the_cue_rule():
    """A cue with only one span must not change anything — the rule needs two to choose between."""
    assert _f("page H1 'Only on Netflix'") == "Only on Netflix"
    assert _f("rail titled 'Only on Netflix'") == "Only on Netflix"


def test_the_860_behaviours_survive():
    """Contractions, curly quotes and the chevron strip all still hold."""
    assert _f("caption 'We won't suggest this to you again'") \
        == "We won't suggest this to you again"
    assert _f("rail “Only on Netflix”") == "Only on Netflix"
    assert _f("crumb 'Movies ›'") == "Movies"


def test_the_chevron_strip_applies_to_the_chosen_span_too():
    """If the cue picks a span that ends in a separator, it is still cleaned."""
    assert _f("crumb 'Home' and page H1 'Sports >'") == "Sports"


def test_unquoted_component_descriptions_are_still_rejected():
    """#432/#459 own the unquoted path; a cue must not resurrect a debug label."""
    assert _f("page title hover preview card") == ""
    assert _f("section title row2 label") == ""


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))


def test_a_cue_between_two_spans_labels_the_following_one():
    """★ The case that killed the first rule. Raw distance picks 'Home' (15 chars vs 16); the cue
    is separated from it by " and ", so it announces the next span instead."""
    assert _f("breadcrumb 'Home >' and section title 'Action Movies'") == "Action Movies"


def test_only_whitespace_counts_as_adjacent():
    """A word between the span and the cue breaks the label relationship."""
    assert _f("'Episodes' section title with 'The Hawk'") == "Episodes"
    assert _f("'Episodes' rail and section title 'The Hawk'") == "The Hawk"
