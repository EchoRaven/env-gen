"""Once owner-scoped pages POPULATE, the seed content must also read realistically.
Regressions fixed (outlook MM, 2026-06-29): a message ``from_name`` / ``contacts.name``
rendered "Getting Started" (a project title, not a person); ``unread_count`` was 1773
(one huge-number formula for every count); ``subject`` was omitted (blank subject lines).
"""

import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.backend_skeleton import (  # noqa: E402
    _seed_cell, _seed_number, _is_person_name, _SEED_PEOPLE, _SEED_TITLES)


def _cell(col, table, i=0):
    return _seed_cell(col, table, i, None, {})


def test_person_columns_get_people_not_titles():
    # senders / contacts / authors / attendees → a real person name
    for col, table in [("from_name", "messages"), ("name", "contacts"),
                       ("sender_name", "messages"), ("author_name", "posts"),
                       ("full_name", "users"), ("name", "attendees")]:
        assert _cell(col, table) in _SEED_PEOPLE, f"{table}.{col} should be a person"


def test_label_columns_get_neutral_titles():
    # folder / calendar / event / board names are titles, not people
    for col, table in [("name", "folders"), ("name", "calendars"),
                       ("title", "events"), ("name", "projects"), ("subject", "messages")]:
        assert _cell(col, table) in _SEED_TITLES, f"{table}.{col} should be a title"


def test_subject_is_not_blank():
    from multi_agent.runtime.backend_skeleton import _SEED_OMIT
    assert _cell("subject", "messages") is not _SEED_OMIT
    assert _cell("subject", "messages") in _SEED_TITLES


def test_email_columns_are_emails():
    for col in ("email", "from_email", "sender_email", "to_email"):
        v = _cell(col, "messages")
        assert isinstance(v, str) and v.endswith("@example.com"), f"{col}={v!r}"
    # a JSON-array column (to_emailS) must NOT be seeded a scalar email
    from multi_agent.runtime.backend_skeleton import _SEED_OMIT
    assert _cell("to_emails", "messages") is _SEED_OMIT


def test_ordinary_counts_are_small_and_believable():
    # the headline regression: an inbox folder must not ship unread_count in the thousands
    for col in ("unread_count", "comment_count", "reply_count", "quantity", "total", "item_count"):
        for i in range(6):
            v = _seed_number(col, i)
            assert 0 <= v < 100, f"{col} seed {v} not believable"


def test_engagement_metrics_may_be_large():
    big = max(_seed_number("view_count", i) for i in range(6))
    assert big > 100  # views/likes/subscribers can be hundreds–thousands


def test_rating_is_one_to_five_and_year_is_recent():
    assert all(1 <= _seed_number("rating", i) <= 5 for i in range(8))
    assert all(2015 <= _seed_number("release_year", i) <= 2026 for i in range(8))


def test_numbers_are_integers():
    # the column may be Integer-typed; a float would coerce/truncate or error on insert
    for col in ("price", "amount", "unread_count", "duration_seconds", "rating", "view_count"):
        assert all(isinstance(_seed_number(col, i), int) for i in range(4)), col


def test_is_person_name_helper():
    assert _is_person_name("from_name", "messages") is True
    assert _is_person_name("name", "contacts") is True
    assert _is_person_name("name", "folders") is False
    assert _is_person_name("subject", "messages") is False


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
