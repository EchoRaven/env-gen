"""#1203ke: "create not attributed to the user", said of a row that is.

The check returned on the FIRST of four owner-shaped names present in the response, and
`author_id` precedes `user_id`. The projector defaults exactly ONE owner column
(`valid.setdefault("user_id", _fw_owner_val(...))`), so a comments table carrying both is
created attributed via `user_id` with `author_id` null — and the sentence was false.

Measured over the modern era: 188 projected POST handlers, 185 project a single owner-shaped
column and 3 project both (r168 /api/comments, r180 /api/videos/{video_id}/comments, r175
/api/posts/{post_id}/comments). All three default `user_id` only, so all three false-fail —
into the DELIVERY-time test-user report, where `broken` makes the verdict ISSUES.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.test_user_validation import (  # noqa: E402
    owner_attribution_1203ke as OA)


# r168's shape, verbatim in the fields that matter: the projected handler defaults user_id
# and the table also carries author_id, which nothing fills.
_R168 = {"item": {"id": 7, "video_id": 3, "user_id": 5, "author_id": None, "text": "hi"}}


def test_a_row_attributed_by_the_other_column_passes_1203ke():
    ok, note = OA(_R168, "comments")
    assert ok is True, note
    assert "user_id=5" in note, note
    # the null sibling is SAID, not dropped — it may matter if reads scope by it
    assert "author_id" in note and "null" in note, note
    assert "_created_appears" in note, (
        "name the check that decides the remaining risk, or the note invites a guess", note)


def test_the_old_first_name_wins_reading_is_gone_1203ke():
    """NON-VACUITY: the same object under the old rule failed. If this ever passes while the
    test above fails, the fix was reverted rather than refined."""
    first_present = next(k for k in ("author_id", "user_id", "owner_id", "created_by")
                         if k in _R168["item"])
    assert first_present == "author_id", "the fixture must reproduce the ordering that broke"
    assert _R168["item"][first_present] is None


def test_a_row_attributed_to_nobody_still_fails_1203ke():
    ok, note = OA({"item": {"id": 7, "user_id": None, "author_id": None}}, "comments")
    assert ok is False, note
    assert "not attributed to the user" in note, note
    # name BOTH, so the lane is not sent after one column while the other is equally empty
    assert "author_id" in note and "user_id" in note, note


def test_a_single_null_owner_column_still_fails_1203ke():
    ok, note = OA({"item": {"id": 7, "user_id": ""}}, "videos")
    assert ok is False and "user_id" in note, note


def test_a_resource_with_no_owner_column_is_not_judged_1203ke():
    ok, note = OA({"item": {"id": 7, "title": "x"}}, "sounds")
    assert ok is True and note == "created", note


def test_it_unwraps_the_usual_envelopes_1203ke():
    for key in ("item", "data", "result"):
        ok, note = OA({key: {"id": 1, "user_id": 9}}, "r")
        assert ok is True and "user_id=9" in note, (key, note)
    # and a bare object, with no envelope
    ok, note = OA({"id": 1, "user_id": 9}, "r")
    assert ok is True and "user_id=9" in note, note


def test_a_non_dict_payload_is_not_a_failure_1203ke():
    for junk in (None, [], "", 7, ["user_id"]):
        ok, note = OA(junk, "r")
        assert ok is True, (junk, note)
