r"""#1202uk: the hint built to stop the agent guessing was reporting the page as unlabelled.

`describe_interactive_candidates` (#362) lists what IS interactable after a selector miss.
It read six ATTRIBUTES and no text, so a control whose only identity is what it says on
screen produced an empty `attrs` dict and was `continue`d out of the list entirely.

MEASURED against a live generated app (r132, port 8009), read with the real function:

    page offers 19 interactable controls
    the hint reported 10
    the 9 it silently dropped were the WHOLE left navigation --
      For You, Shop, Explore, Following, LIVE, Upload, Profile, More, Log in
    4 more survived only as `{type='button'}`, which names nothing

ACROSS 151 RUN LOGS: 538 browser click/fill failures, 230 carrying this list, and 90 of
those (39%) majority `{type='...'}` entries.

THE COST, in r134, exactly: eight delivery-blocking `ui_flow` checks, each written as "only
unlabeled buttons were interactable" / "cannot locate accessible Like control". The verifier
was quoting this list. The app was RIGHT -- its own saved screenshot shows the labelled
control on screen, and the source carries `aria-label="Like"` -- so the frontend was sent P0s
to add labels that already existed, reported them fixed, and the rerun read the same noise.

PART TWO. Naming the text-only controls made the list complete and so LONGER, and `limit`
then truncated at the navigation: asking for "Like" returned a list ending at "Get App" with
the Like button past the cut -- worse than the omission. The list is now RANKED by what was
asked for. That also repairs the verb/label mismatch on its own: agents ask for `name="Like"`
while generated apps label controls "Like video"/"Open comments"/"Toggle sound", and
`role=button[name="Like"]` -- what the role branch builds -- is an EXACT match, so it misses.
Ranking hands the agent the real string instead of a second guess. Verified live:

    wanted='Like'    -> {aria-label='Like video', data-testid='like-video', ...} FIRST
    wanted='Comment' -> {aria-label='Open comments', data-testid='open-comments', ...} FIRST

DOMAIN-AGNOSTIC: ranking is a two-way case-folded substring over the values already
collected. It knows nothing of what a control means, asserted below by running the identical
page through with the labels renamed to opaque tokens.

LOCAL-ONLY (gitignored)."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from tools.browser.interaction import (  # noqa: E402
    _EMPTY_PAGE_688,
    describe_interactive_candidates,
)


class _El:
    """A stand-in for a Playwright element handle: only the three calls the probe makes."""

    def __init__(self, attrs=None, text=""):
        self._a = dict(attrs or {})
        self._t = text

    async def get_attribute(self, name):
        return self._a.get(name)

    async def inner_text(self):
        return self._t


class _Page:
    def __init__(self, els):
        self._els = els

    async def query_selector_all(self, _sel):
        return list(self._els)


def _run(els, **kw):
    return asyncio.run(describe_interactive_candidates(_Page(els), **kw))


# The r132 navigation, as the live page actually serves it: a <button> carrying nothing but
# its own text.
NAV = [_El(text=t) for t in ("For You", "Shop", "Explore", "Following", "LIVE",
                             "Upload", "Profile", "More", "Log in")]
LIKE = _El({"aria-label": "Like video", "type": "button", "data-testid": "like-video"}, "672K")
SEARCH = _El({"placeholder": "Search", "aria-label": "Search"})


def test_a_control_named_only_by_its_text_is_reported():
    """★ The defect itself: nine real controls were deleted from the list."""
    out = _run(NAV)
    for label in ("For You", "Explore", "Upload", "Log in"):
        assert label in out, f"{label!r} missing from {out!r}"


def test_the_navigation_is_not_silently_dropped():
    """The count, not just one sample -- the whole nav has to survive."""
    out = _run(NAV + [SEARCH, LIKE], limit=40)
    assert out.count("{") == 11, out


def test_what_was_asked_for_is_ranked_first():
    """★ Part two, and the thing that unblocks r134: the verb finds the verb-object label."""
    out = _run(NAV + [SEARCH, LIKE], wanted="Like")
    first = out.split(";")[0]
    assert "like-video" in first, f"Like control not ranked first: {out!r}"


def test_ranking_survives_truncation():
    """★ The regression part one introduced, asserted directly: a complete list is longer,
    so without ranking the answer falls off the end."""
    out = _run(NAV + [SEARCH, LIKE], limit=5, wanted="Like")
    assert "like-video" in out, out
    assert "more" in out, f"truncation not announced: {out!r}"


def test_truncation_announces_itself():
    """#883: a cut list that does not say so reads as exhaustive, and the agent concludes the
    control is absent -- the same wrong inference this ticket exists to stop."""
    out = _run(NAV, limit=3)
    assert "... and 6 more" in out, out
    assert "more" not in _run(NAV, limit=40), "announced a cut that did not happen"


def test_no_wanted_keeps_dom_order():
    """★ The property the ranking could most easily have cost: the callers that pass nothing
    must see exactly what they saw before."""
    els = NAV + [SEARCH, LIKE]
    assert _run(els, limit=40) == _run(els, limit=40, wanted="")
    assert _run(els, limit=40).index("For You") < _run(els, limit=40).index("Like video")


def test_it_is_domain_agnostic():
    """★ The user's iron rule. Renaming every label to an opaque token must not change the
    behaviour -- the ranking reads values, never meanings."""
    opaque_nav = [_El(text=f"tok{i}") for i in range(9)]
    opaque_hit = _El({"aria-label": "tok9 zz", "data-testid": "tok9-zz"}, "1")
    out = _run(opaque_nav + [opaque_hit], wanted="tok9")
    assert "tok9-zz" in out.split(";")[0], out


def test_an_element_with_nothing_at_all_is_still_skipped():
    """A control with no attribute and no text cannot be named by any selector, and listing
    it as `{}` would be the same noise this ticket removes."""
    out = _run([_El(), _El(), _El(text="Real")])
    assert out.count("{") == 1, out


def test_an_empty_page_still_reports_the_688_sentinel():
    """★ #688's distinction -- "the probe looked and the page offers nothing" vs "could not
    look" -- is the one diagnosis that inverts, so it must survive this change."""
    assert _run([]) == _EMPTY_PAGE_688
    assert asyncio.run(describe_interactive_candidates(None)) == ""


def test_it_never_raises_on_a_hostile_element():
    """It runs on an ALREADY-failing path: an element that throws must cost that element,
    not the hint."""

    class _Bad(_El):
        async def inner_text(self):
            raise RuntimeError("detached")

    out = _run([_Bad({"aria-label": "Still here"}), _El(text="Real")])
    assert "Still here" in out and "Real" in out, out


def test_a_page_of_unlabelled_controls_still_produces_a_hint():
    r"""★ The regression my own first version of this fix introduced, pinned so it cannot
    come back.

    I tightened the skip to require one of the NAMING keys, which dropped `{type='button'}`.
    On a page whose controls are all unlabelled icon buttons that empties the list, and an
    empty list returns `""` -- which #688 defines as "could not look", so
    `_candidates_hint_688` drops the hint ENTIRELY and the agent is back to the bare
    "Timeout 5000ms exceeded" that #362 was written to replace.

    `{type='button'}` is a poor entry, but "this page has controls I cannot name" is true and
    is the diagnosis that should send a label defect to the frontend. Ranking, not skipping,
    is what keeps it from crowding out the answer.
    """
    only_noise = [_El({"type": "button"}) for _ in range(4)]
    out = _run(only_noise)
    assert out and out != _EMPTY_PAGE_688, f"hint collapsed to {out!r}"
    assert out.count("{") == 4, out


def test_noise_never_outranks_the_answer():
    """The other half: with `wanted`, an addressable match must precede the unnameable ones
    even when they come first in the DOM."""
    els = [_El({"type": "button"}) for _ in range(11)] + [LIKE]
    out = _run(els, limit=3, wanted="Like")
    assert "like-video" in out.split(";")[0], out


def test_the_answer_is_ranked_even_when_it_sits_late_in_the_dom():
    r"""★ The second hole my own first version left: the SCAN was capped before the ranking.

    Collection ran `els[:limit * 3]`, so with the default limit only the first 36 elements
    were examined -- and ranking happens after. A control past that point could not be
    surfaced however well it matched, which is the same "the list says it isn't there" wrong
    inference the ticket exists to remove, just moved one step earlier.

    MEASURED over 21 live pages across three running generated environments (r122/r126/r132):
    6 to 47 interactable controls per page, median 19, busiest 47 (r126/explore). So the old
    cap of 36 was already inside the real range, not a theoretical edge.
    """
    els = [_El({"type": "button"}) for _ in range(60)] + [LIKE]
    out = _run(els, limit=4, wanted="Like")
    assert "like-video" in out.split(";")[0], out


def test_a_category_attribute_cannot_outrank_a_name():
    r"""★ The inversion my own ranking introduced, on the path #1202un then wired.

    `_rank` compared `wanted` against EVERY collected value, and `type` is one of them. But
    `type` is a CATEGORY, never an identifier -- and `browser_fill` passes its raw CSS
    selector as `wanted`. So `wanted="button.submit"` matched every bare `{type='button'}`,
    which then tied with (and by DOM order beat) the one element carrying
    `aria-label='Submit'` and `data-testid='submit-btn'`.

    Measured on the shape a live page produces -- 8 unnamed buttons then one real control --
    the real match came LAST: the noise this ticket exists to demote, promoted by the fix
    itself. `type` stays in the DISPLAYED entry, where it is informative; it just cannot rank.
    """
    noise = [_El({"type": "button"}) for _ in range(8)]
    real = _El({"aria-label": "Submit", "type": "submit", "data-testid": "submit-btn"}, "Submit")
    for wanted in ("button.submit", "Submit", "submit-btn", "input[type='submit']"):
        out = _run(noise + [real], limit=3, wanted=wanted)
        assert "submit-btn" in out.split(";")[0], (wanted, out)


def test_type_is_still_shown_even_though_it_cannot_rank():
    """The other half: demoting it from the ranking must not delete it from the entry."""
    out = _run([_El({"type": "button"})])
    assert "type='button'" in out, out
