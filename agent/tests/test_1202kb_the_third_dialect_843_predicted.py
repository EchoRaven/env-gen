"""#1202kb: #843 predicted a third table dialect and tiktok-r113 supplied it.

`_DESC_TABLE_RE` knew two ways a milestone slice can declare a table — `- users: cols` and
`- users(cols)` — and #843's own comment explains why a third would stay invisible: "a slice
in the second dialect parses to zero tables ... neither numerator nor denominator ... the
bracket dialect was never seen because the only runs using it produced no tables and therefore
no evidence that anything was missing."

The third is SQUARE brackets:

    - users[id, username, display_name, avatar_url, bio, following_count, ...]

Measured over the corpus: 295 table entries in that dialect across 10 runs that use it
exclusively, against 617 in the colon form. Every one of those runs had a FIX #42 backstop
that could back nothing up, and nothing said so — until r113 died on
`contract.data_model.tables MUST be a non-empty list` with its tables written in it.

r113's slices now yield 13 tables where they yielded 0.
"""
import sys
import pathlib

_AGENT = pathlib.Path(__file__).resolve().parents[1]
if str(_AGENT) not in sys.path:
    sys.path.insert(0, str(_AGENT))

import pytest                                                          # noqa: E402

from env_generator.llm_generator.multi_agent.runtime.kickoff.run_kickoff import (  # noqa: E402
    extract_contract_from_description as _extract)


def _tables(body):
    return [t["name"] for t in (_extract("Data model:\n" + body).get("tables") or [])]


@pytest.mark.parametrize("line,label", [
    ("- users: id, username, email", "colon"),
    ("- users(id, username, email)", "parenthesised"),
    ("- users[id, username, email]", "square-bracket (#1202kb)"),
    ("- table: users: id, username, email", "table-prefixed (#773)"),
])
def test_every_known_dialect_yields_the_table(line, label):
    assert _tables(line) == ["users"], label


def test_the_columns_survive_the_bracket_form():
    got = _extract("Data model:\n- videos[id, author_id, caption, thumbnail_url]")
    cols = [c["name"] for c in got["tables"][0]["columns"]]
    assert cols == ["id", "author_id", "caption", "thumbnail_url"]


def test_r113s_shape_end_to_end():
    """★ The real slice's opening lines, verbatim in shape."""
    body = ("DATA MODEL:\n"
            "- users[id, username, display_name, avatar_url, bio, following_count, verified]\n"
            "- videos[id, author_id, video_url, thumbnail_url, caption, sound_id]\n"
            "- comments[id, video_id, user_id, text, image_url]\n")
    assert _tables(body.split("\n", 1)[1]) == ["users", "videos", "comments"]


def test_prose_still_yields_nothing():
    """Non-vacuity in the other direction: the widening must not invent tables from prose.

    A sentence with a bracketed aside is exactly what a looser pattern would swallow.
    """
    assert _tables("- Build the shared sidebar [For You, Explore, Following] first") == []


def test_a_bare_word_is_not_a_table():
    assert _tables("- users") == []
