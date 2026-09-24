"""#263 — a by-id path must never be filled with an id belonging to another resource.

r55 (opus-4.7) reached a WORKING app and then aborted on business_chain_failing alone,
with 20 of 28 chains red. Every one of them failed the same way:

    POST /auth/register            -> 201
    GET  /api/v1/feed/foryou       -> 200   (a list of videos)
    GET  /api/v1/videos/${first_video_id} -> 404 {"detail":"video not found"}

``first_video_id`` was never saved by any step, so resolution fell through to the global
``last_id`` — the id of the row created most recently, i.e. the USER from /auth/register.
The tell is arithmetic: the feed chain (1 register) asked for video 3, the like chain
(2 registers) for 5, the save chain for 6 — consecutive USER ids.

The two existing rungs both miss here: the feed response is keyed ``items`` so it is not
filed under ``videos``, and the resource's bare collection ``/api/v1/videos`` does not
exist (this app exposes ``/feed/foryou`` instead), so list-recovery has nothing to call.

A foreign id on a by-id path is guaranteed to 404. That is worse than leaving the chain
unresolved: it looks exactly like an application bug, and r55 spent its entire 88-minute
convergence budget on it. Prefer an id drawn from a prior response that actually contained
a LIST of objects — what a human reads the feed for — and only then the global last_id.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from env_generator.llm_generator.multi_agent.runtime.chain_executor import (  # noqa: E402
    _ids_from_list_payload,
    _pick_id_for_resource,
)


FEED = {"items": [{"id": 17, "caption": "a"}, {"id": 18, "caption": "b"}]}
USER = {"id": 3, "email": "c@t.io"}


def test_ids_are_harvested_from_a_list_payload():
    assert _ids_from_list_payload(FEED) == [17, 18]


def test_bare_list_payload():
    assert _ids_from_list_payload([{"id": 4}, {"id": 5}]) == [4, 5]


def test_singular_object_is_not_a_list_source():
    """The /auth/register response is exactly this — it must never be a candidate."""
    assert _ids_from_list_payload(USER) == []


def test_nested_collection_under_any_key():
    for key in ("items", "videos", "data", "results", "records"):
        assert _ids_from_list_payload({key: [{"id": 9}]}) == [9], key


def test_r55_regression_prefers_the_feed_id_over_the_user_id():
    """The exact r55 sequence: register (user 3), feed (videos 17,18), then videos/{id}."""
    seen = [("/auth/register", USER), ("/api/v1/feed/foryou", FEED)]
    got = _pick_id_for_resource("videos", seen, last_id=3)
    assert got == 17, got


def test_same_resource_path_wins_over_a_more_recent_list():
    """A list whose PATH names the resource beats a merely-more-recent one."""
    seen = [("/api/v1/videos", {"items": [{"id": 100}]}),
            ("/api/v1/comments", {"items": [{"id": 200}]})]
    assert _pick_id_for_resource("videos", seen, last_id=9) == 100


def test_most_recent_list_wins_when_no_path_matches():
    seen = [("/api/v1/sounds", {"items": [{"id": 50}]}),
            ("/api/v1/feed/foryou", {"items": [{"id": 60}]})]
    assert _pick_id_for_resource("videos", seen, last_id=9) == 60


def test_falls_back_to_last_id_when_no_list_was_ever_seen():
    seen = [("/auth/register", USER)]
    assert _pick_id_for_resource("videos", seen, last_id=3) == 3


def test_string_and_uuid_ids_survive():
    seen = [("/api/v1/videos", {"items": [{"id": "b3f1-uuid"}]})]
    assert _pick_id_for_resource("videos", seen, last_id=1) == "b3f1-uuid"


def test_objects_without_ids_are_ignored():
    seen = [("/api/v1/videos", {"items": [{"caption": "no id"}]}),
            ("/api/v1/feed", {"items": [{"id": 7}]})]
    assert _pick_id_for_resource("videos", seen, last_id=1) == 7


def test_alternate_id_key_names():
    assert _ids_from_list_payload({"items": [{"video_id": 42}]}) == [42]
    assert _ids_from_list_payload({"items": [{"uuid": "u1"}]}) == ["u1"]
