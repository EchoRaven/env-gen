"""#1202nk: the create probe must not send values the framework's own handlers refuse.

`_probe_body` builds the persistence probe (api_smoke's `business_writes_persist`) and the
test-user journey's creates from the registered request schema. Two of its placeholders are
refused by construction:

* an OWNER column (`profile_id`, `actor_id`, `author_id`, ...) got `1` — another user's id — and
  #566s's IDOR guard answered 403 "profile_id does not belong to the caller". 33 of the 95 failed
  creates across 221 test-user reports.
* a timestamp got "persist-probe". tiktok-r125: `POST /api/feed` with `created_at: "string?"`
  → 400 "invalid input syntax for type timestamp with time zone", on every milestone.

A create that fails on the probe's own body is recorded "write not verified" and skipped, so the
persistence check it feeds silently checks nothing.
"""
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.validation_runner import _probe_body  # noqa: E402

R125_FEED = {"sound_id": "int?", "video_url": "string?", "caption": "string?",
             "like_count": "int?", "created_at": "string?"}


def test_r125_created_at_is_a_timestamp():
    body = _probe_body({"schema": {"request": R125_FEED}})
    assert body["created_at"] == "2026-01-01T00:00:00Z"
    assert body["caption"] == "persist-probe" and body["like_count"] == 1


def test_owner_columns_are_left_to_the_handler():
    body = _probe_body({"schema": {"request": {
        "profile_id": "int", "actor_id": "int", "user_id": "int", "title_id": "int",
        "rating": "int"}}})
    assert "profile_id" not in body and "actor_id" not in body and "user_id" not in body
    assert body["title_id"] == 1 and body["rating"] == 1      # the subject FK stays (#566d)


def test_typed_dates_and_numeric_durations():
    body = _probe_body({"schema": {"request": {
        "due": "date", "starts": "timestamptz", "watch_time": "int", "note": "str"}}})
    assert body["due"] == "2026-01-01"
    assert body["starts"] == "2026-01-01T00:00:00Z"
    assert body["watch_time"] == 1
    assert body["note"] == "persist-probe"
