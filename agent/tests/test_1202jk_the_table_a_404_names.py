"""#1202jk: a 404 note must name the table whose id the path carries.

r111 recorded 40 failed steps, every one a 404 on `/api/videos/1/...`, and #1202id's note
told the lane to look at the WRONG table while contradicting itself doing it:

    POST /api/videos/1/like -> 404 {"detail":"parent resource not found"}
    note: TABLE `likes` HAS 6 LIVE ROW(S) (a seeded id is 1) — the table is populated,
          so the id this step names is the thing that does not exist.

`likes` id 1 both "is seeded" and "does not exist" in one sentence, and the response says
**parent** outright. The table to name is `videos`, whose id the path carries.

(Those 40 sit in `last_failure_1202fa.failed_steps`, which #1202fa preserves. By r111's END
every one of those steps answered 200/201 and all 30 real chains were `passing` — the run
failed on the VISUAL gate, with `validation:business_chain` recorded success. The note was
wrong when it was emitted; it did not decide that run's outcome.)

The second half is the verdict itself. On a nested path the 404 comes from the handler's own
parent lookup, so the failing request settles nothing about the parent — yet the sentence was
printed either way. Only a read taken AT THE MOMENT OF FAILURE separates "wrong id" from
"broken handler", so that is what #1202jk does.
"""
import sys
import pathlib

_AGENT = pathlib.Path(__file__).resolve().parents[1]
if str(_AGENT) not in sys.path:
    sys.path.insert(0, str(_AGENT))

from env_generator.llm_generator.multi_agent.runtime.chain_executor import (  # noqa: E402
    _template_resource_1202id, _seed_shape_note_1202id)


def test_a_nested_action_names_the_parent_not_the_thing_it_creates():
    # r111's five failing shapes, all of them a write UNDER a video.
    for path in ("/api/videos/{video_id}/like",
                 "/api/videos/{video_id}/save",
                 "/api/videos/{video_id}/comments"):
        assert _template_resource_1202id({"path": path}) == "videos", path


def test_the_deepest_id_wins_when_the_path_carries_two():
    # DELETE /api/videos/1/comments/5 addresses comment 5, not video 1.
    assert _template_resource_1202id(
        {"path": "/api/videos/{video_id}/comments/{comment_id}"}) == "comments"


def test_a_flat_detail_route_is_unchanged():
    # #1202id's own working example. The old rule was already right here and must stay.
    assert _template_resource_1202id({"path": "/api/transit-stops/{id}"}) == "transit-stops"
    assert _template_resource_1202id({"path": "/api/videos/{id}"}) == "videos"


def test_a_collection_write_with_no_id_falls_back_to_its_own_table():
    # No `{param}` means no id to be missing; the resource IS the last static segment.
    assert _template_resource_1202id({"path": "/api/videos"}) == "videos"
    assert _template_resource_1202id({"path": "/api/videos/"}) == "videos"


def test_the_note_reaches_the_lane_with_the_parent_table(tmp_path):
    """Reachability, not presence: the corrected table must survive into the emitted text.

    #1202jk changed a helper; what a lane READS is `_seed_shape_note_1202id`, and it is
    guarded by three early returns. This pins the whole path with r111's real counts.
    """
    import json

    (tmp_path / "shared").mkdir()
    (tmp_path / "shared" / "seed_live_counts_1202dj.json").write_text(json.dumps({
        "at": __import__("time").time(),
        "counts": {"videos": 39, "likes": 6, "saves": 6, "comments": 295},
    }))
    note = _seed_shape_note_1202id(
        "POST", "/api/videos/1/like", tmp_path,
        {"videos": 101, "likes": 1},
        [{"method": "POST", "path": "/api/videos/{video_id}/like"}],
    )
    assert "`videos`" in note and "39" in note, note
    assert "`likes`" not in note, note
    # and it hands over an id that actually works, instead of the id that just 404'd
    assert "101" in note, note


# --- the parent probe: ask instead of assuming --------------------------------------

import json                                                            # noqa: E402
import time                                                            # noqa: E402

import pytest                                                          # noqa: E402

from env_generator.llm_generator.multi_agent.runtime import chain_executor as CE  # noqa: E402

_EPS = [{"method": "POST", "path": "/api/videos/{video_id}/like"},
        {"method": "GET", "path": "/api/transit-stops/{id}"}]


@pytest.fixture
def r111(tmp_path):
    """r111's measured counts: `videos` 39 rows, and the chain naming video 1."""
    (tmp_path / "shared").mkdir()
    (tmp_path / "shared" / "seed_live_counts_1202dj.json").write_text(json.dumps(
        {"at": time.time(), "counts": {"videos": 39, "likes": 6, "transit-stops": 4}}))
    return tmp_path


def _note(monkeypatch, r111, status, method="POST", path="/api/videos/1/like"):
    seen = []

    def _fake_http(m, url, token=None, body=None):
        seen.append((m, url))
        return {"status": status}

    monkeypatch.setattr(CE, "_http", _fake_http)
    n = CE._seed_shape_note_1202id(method, path, r111, {"videos": 101}, _EPS,
                                   base="http://app", token="t")
    return n, seen


def test_a_parent_that_answers_200_moves_the_blame_to_the_handler(monkeypatch, r111):
    """The case the old text could not express, and never checked for."""
    n, seen = _note(monkeypatch, r111, 200)
    assert seen == [("GET", "http://app/api/videos/1")], seen
    assert "PARENT EXISTS" in n and "Fix this endpoint" in n, n
    assert "does not exist" not in n, n


def test_a_parent_that_404s_keeps_the_original_verdict(monkeypatch, r111):
    n, _ = _note(monkeypatch, r111, 404)
    assert "`videos` HAS 39 LIVE ROW(S)" in n, n
    assert "does not exist" in n and "101" in n, n


def test_an_unreachable_parent_states_both_branches_instead_of_guessing(monkeypatch, r111):
    n, _ = _note(monkeypatch, r111, 503)
    assert "EITHER a wrong id OR this handler's lookup" in n, n
    assert "does not exist" not in n, n


def test_a_flat_by_id_404_is_its_own_proof_and_is_never_probed(monkeypatch, r111):
    """The failing request IS the id check there — a probe would only repeat it."""
    n, seen = _note(monkeypatch, r111, 200,
                    method="GET", path="/api/transit-stops/7")
    assert seen == [], seen
    assert "does not exist" in n, n
