"""#1203jw: "created X is ABSENT from the list" named two causes and asserted them.

`_created_appears` is a real persistence assertion and the verdict is right to be strict. The
SENTENCE was not: it ended "the write did not persist, or the read is scoped to a different
owner than the write", and a bounded list WINDOW is a third cause the corpus actually has.

Measured over every test-user report on disk — 6 "created X is ABSENT" findings in 4 runs:

    r186  feed       id=36   5 rows, ids 35,34,33,32,31   DESCENDING  -> REAL: 36 belongs at
                                                                        the head and is gone
    r149  comments   id=296  100 rows, ids 1,2,3,4,5,6    ASCENDING   -> the row is almost
          (x2)                                                           certainly on a later
                                                                         page, reported as a
                                                                         persistence defect
    r125  feed/videos        10 rows, 6 ids shown                     -> UNJUDGEABLE, because
          (x2)                                                           the ids were cut
    r120  suggested  id=20   13 rows, unordered                       -> needs eyes

The verdict stays False in every case. Turning a window into a pass would let a genuinely lost
write through on any paginated list — #1202xc's "traded one silence for another". What changes
is that the prose stops naming only causes that are wrong, so the lane is not dispatched to fix
persistence that works, and the id list is no longer silently cut (#1034).
"""
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE)))

from env_generator.llm_generator.multi_agent.runtime.test_user_validation import (  # noqa: E402
    _created_appears,
)


def _rows(ids):
    return [{"id": i} for i in ids]


def test_a_descending_window_missing_its_head_is_still_a_real_finding():
    """r186's shape: the created id belongs at the head of a newest-first list."""
    ok, msg = _created_appears({"items": _rows([35, 34, 33, 32, 31])}, "feed", 36)
    assert ok is False
    assert "the write did not persist" in msg, msg
    assert "WINDOW" not in msg and "ASCENDING" not in msg, msg


def test_a_declared_total_larger_than_the_page_names_the_window():
    """r149's shape, decided by the framework's own list contract rather than a guess."""
    ok, msg = _created_appears(
        {"items": _rows(list(range(1, 101))), "total": 296}, "comments", 296)
    assert ok is False, "a window must not become a pass"
    assert "the list is a WINDOW (total=296 but 100 returned)" in msg, msg
    assert "read the row by id" in msg, msg
    assert "the write did not persist" not in msg, (
        "the sentence still asserts a cause that is wrong here: %s" % msg)


def test_an_ascending_page_of_lower_ids_says_it_may_be_past_the_window():
    """No `total` to lean on, so this is stated as a possibility, not a verdict."""
    ok, msg = _created_appears({"items": _rows([1, 2, 3, 4, 5])}, "comments", 296)
    assert ok is False
    assert "ASCENDING" in msg and "may be past the window" in msg, msg
    # it must still offer the original causes rather than replacing them
    assert "did not persist" in msg, msg


def test_an_ascending_page_holding_a_HIGHER_id_is_not_a_window():
    """The discriminator the first version of this file was missing.

    If the page is ascending but already carries an id ABOVE the created one, the window did
    not cut our row off — it should have been right there. Dropping the "every id is lower"
    half of the test survived a mutation round because every ascending case here happened to
    satisfy it.
    """
    ok, msg = _created_appears({"items": _rows([1, 2, 300])}, "feed", 5)
    assert ok is False
    assert "may be past the window" not in msg, msg
    assert "the write did not persist" in msg, msg


def test_an_empty_list_keeps_the_original_two_causes():
    """Nothing returned is not a window — it is the case #566p wrote the sentence for."""
    ok, msg = _created_appears({"items": []}, "feed", 7)
    assert ok is False
    assert "the write did not persist" in msg, msg
    assert "WINDOW" not in msg and "ASCENDING" not in msg, msg


def test_a_total_equal_to_the_page_is_not_a_window():
    ok, msg = _created_appears({"items": _rows([1, 2, 3]), "total": 3}, "feed", 9)
    assert ok is False
    assert "WINDOW" not in msg, msg


def test_a_descending_page_of_lower_ids_is_not_called_a_window():
    """Order is the discriminator: newest-first means the head is where the row belongs."""
    ok, msg = _created_appears({"items": _rows([5, 4, 3, 2, 1])}, "feed", 296)
    assert ok is False
    assert "ASCENDING" not in msg and "WINDOW" not in msg, msg


def test_the_id_list_declares_what_it_cut():
    """#1034: a count beside a truncated list must say the remainder. r125's two findings are
    unjudgeable today because 10 rows printed 6 ids with no marker."""
    ok, msg = _created_appears({"items": _rows(list(range(1, 11)))}, "feed", 99)
    assert ok is False
    assert "list has 10 row(s)" in msg, msg
    assert "more not shown" in msg, (
        "the id list is still cut without saying so: %s" % msg)


def test_a_short_id_list_gains_no_noise():
    ok, msg = _created_appears({"items": _rows([3, 2, 1])}, "feed", 99)
    assert "more not shown" not in msg, msg
    assert "3; 2; 1" in msg, msg


def test_a_found_row_is_unaffected():
    ok, msg = _created_appears({"items": _rows([1, 2, 3]), "total": 99}, "feed", 2)
    assert ok is True, msg


def test_no_id_captured_stays_advisory():
    ok, msg = _created_appears({"items": _rows([1, 2])}, "feed", None)
    assert ok is True and "listed" in msg, msg


@pytest.mark.parametrize("payload", [None, [], {}, {"items": None}, {"items": "x"},
                                     {"items": _rows([1]), "total": "many"}])
def test_it_never_raises_on_odd_payloads(payload):
    ok, msg = _created_appears(payload, "feed", 5)
    assert isinstance(msg, str) and ok is False, (payload, ok, msg)
