"""#1117: what gets stored must contain the reason it was stored.

`GeneratorMemory` auto-files an inter-agent message as durable `tech_context`
knowledge when the message mentions api / endpoint / schema. The admission test ran
on the WHOLE message; the stored text was its first 300 characters. So the API fact
that justified keeping the entry was routinely truncated away, and what persisted was
whatever coordination preamble the message happened to open with — later handed back
to agents by `get_relevant_knowledge` as fact.

Corpus: 3607 knowledge entries across 66 runs, every one written by that branch
(nothing else reaches the persisted store), and 883 of them — 24% — contain none of
the keywords they were admitted for.
"""
import pytest

from env_generator.llm_generator.memory.generator_memory import (
    _api_excerpt_1117,
    _API_KEYWORDS_1117,
    _API_EXCERPT_CHARS_1117,
)


def _has_keyword(text):
    low = (text or "").lower()
    return any(k in low for k in _API_KEYWORDS_1117)


def test_the_excerpt_carries_the_keyword_that_admitted_the_message():
    """The corpus shape: task chatter first, the API fact far past char 300."""
    preamble = (
        "## Validation Summary - DELIVERY BLOCKED\n\n"
        "**task_4315db82f9 status**: IN_PROGRESS (cannot complete - no flow evidence). "
        "Filed 9 fresh check records. Orchestrator confirmed via DM that no further "
        "verifier work is needed this round; proceeding with the retro instead. "
        "Cancelled 11 blocked tasks with detailed reasons and re-woke two assignees. "
    )
    assert len(preamble) > _API_EXCERPT_CHARS_1117, "fixture must exceed the window"
    fact = "GET /api/notes now returns {items: [...]} instead of a bare list."
    msg = preamble + fact

    # what the old code would have stored
    old_stored = msg[:_API_EXCERPT_CHARS_1117]
    assert not _has_keyword(old_stored), "fixture no longer reproduces the defect"

    got = _api_excerpt_1117(msg)
    assert got is not None, "the message stopped being admitted at all"
    assert _has_keyword(got), (
        "the stored excerpt still does not contain the reason it was stored: %r" % got
    )
    assert "/api/notes" in got


def test_admission_is_unchanged():
    """#1117 changes WHAT is stored, never WHICH messages are admitted."""
    assert _api_excerpt_1117("no relevant words here at all") is None
    assert _api_excerpt_1117("") is None
    assert _api_excerpt_1117(None) is None
    for kw in _API_KEYWORDS_1117:
        assert _api_excerpt_1117("please review the %s change" % kw) is not None


def test_a_short_message_is_stored_whole():
    msg = "The /api/login endpoint now issues RS256."
    assert _api_excerpt_1117(msg) == msg


def test_the_window_is_bounded():
    msg = "x" * 5000 + " endpoint " + "y" * 5000
    got = _api_excerpt_1117(msg)
    # the ellipsis markers may add a couple of characters on either side
    assert len(got) <= _API_EXCERPT_CHARS_1117 + 4
    assert "endpoint" in got


def test_a_truncated_excerpt_is_marked_as_such():
    msg = "z" * 1000 + " schema details follow " + "w" * 1000
    got = _api_excerpt_1117(msg)
    assert got.startswith("…") and got.endswith("…"), (
        "an excerpt cut from the middle must not read as the whole message: %r" % got[:60]
    )


def test_the_excerpt_does_not_begin_mid_token():
    msg = ("alpha bravo charlie delta echo foxtrot golf hotel india juliet " * 8
           + "the endpoint is /api/v1/notes")
    got = _api_excerpt_1117(msg)
    body = got.lstrip("…")
    assert body, "excerpt was empty"
    # the first token of the excerpt must be a whole word from the source
    first = body.split()[0]
    assert (" " + first) in msg or msg.startswith(first), (
        "excerpt starts mid-token: %r" % first
    )


@pytest.mark.parametrize("kw", list(_API_KEYWORDS_1117))
def test_every_keyword_is_reachable_past_the_old_window(kw):
    msg = "q" * (_API_EXCERPT_CHARS_1117 + 50) + " " + kw + " matters"
    got = _api_excerpt_1117(msg)
    assert got is not None and kw in got.lower()
