r"""#1203m6: the biggest breaking-change flag never reached the task title at all.

`response_key_changed` fires 862 times across the modern runs -- more than twice
`type_changed_fields`' 332 -- and the payload records only `True`, discarding
`old_schema["response_key"]` and `new_schema["response_key"]`.
`_breaking_title_detail_1202sr` has no bit for it either, so 114 of the 441 modern
`Fix breaking change` tasks (26%, in 24 of 39 runs) carry NO detail in the title, and seven
groups are byte-identical titles repeated inside one run -- the "22 identical rows" problem
#1202sr was built to remove, still live on this flag. Attribution checked on
r156/r185/r152/r183: every detail-less record there is `response_key_changed` (86) or
`path_changed` (9), nothing else.

Composition matters here: #1203m5 and #1203m6 both write into `detect_breaking_change`'s
payload and both render into the same task body, so the last test asserts they coexist
(#1203l9's lesson -- patches sharing a function need a composition test).
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from env_generator.llm_generator.multi_agent.runtime.hub_registry import HubRegistry
from env_generator.llm_generator.multi_agent.runtime.registryhub import (
    _breaking_task_title_1202sr, _shape_change_sentence_1203m6)


def _hub(tmp):
    return HubRegistry(Path(tmp)).hubs.registryhub


def test_the_payload_keeps_both_response_keys(tmp_path):
    out = _hub(tmp_path).detect_breaking_change({"response_key": "posts"},
                                                {"response_key": "items"})
    assert out["response_key_changed"] is True
    assert out["response_key_change_1203m6"] == "posts -> items"


def test_a_key_appearing_or_vanishing_is_spelled_out(tmp_path):
    rh = _hub(tmp_path)
    assert rh.detect_breaking_change({}, {"response_key": "items"}
                                     )["response_key_change_1203m6"] == "(none) -> items"
    assert rh.detect_breaking_change({"response_key": "posts"}, {}
                                     )["response_key_change_1203m6"] == "posts -> (none)"


def test_the_payload_keeps_both_paths(tmp_path):
    out = _hub(tmp_path).detect_breaking_change({"path": "/api/a"}, {"path": "/api/b"})
    assert out["path_changed"] is True
    assert out["path_change_1203m6"] == "/api/a -> /api/b"


def test_an_unchanged_shape_records_nothing(tmp_path):
    out = _hub(tmp_path).detect_breaking_change({"response_key": "posts", "path": "/api/a"},
                                                {"response_key": "posts", "path": "/api/a"})
    assert out["response_key_change_1203m6"] == "" and out["path_change_1203m6"] == ""
    assert _shape_change_sentence_1203m6(out) == ""


def test_the_title_now_tells_two_of_them_apart(tmp_path):
    """The 114 detail-less titles are this: no bit at all for the flag that fired."""
    rh = _hub(tmp_path)
    a = rh.detect_breaking_change({"response_key": "posts"}, {"response_key": "items"})
    b = rh.detect_breaking_change({"response_key": "posts"}, {"response_key": "results"})
    ta = _breaking_task_title_1202sr("GET /api/me", a)
    tb = _breaking_task_title_1202sr("GET /api/me", b)
    assert ta != tb, "two different changes still produce one indistinguishable row"
    assert "posts -> items" in ta and "posts -> results" in tb


def test_a_legacy_record_still_gets_a_bit_without_inventing_values():
    """A record written before this landed has only the boolean. Say that, claim no more."""
    got = _breaking_task_title_1202sr(
        "GET /api/me", {"is_breaking": True, "response_key_changed": True,
                        "path_changed": True})
    assert "response key changed" in got and "path changed" in got
    assert "->" not in got


def test_the_sentence_never_raises():
    for junk in (None, "x", 7, [], {"response_key_change_1203m6": None}):
        assert _shape_change_sentence_1203m6(junk) == ""


def test_m5_and_m6_compose_in_the_task_a_lane_receives(tmp_path):
    """Both halves in one body, values before the payload dump. #1203l9."""
    with tempfile.TemporaryDirectory() as td:
        hubs = HubRegistry(Path(td)).hubs
        # Two things learned by driving the real object rather than assuming:
        #   * `update_schema` carries only request/response, so a response_key move arrives
        #     by RE-REGISTRATION -- which is also how the corpus produces its 862.
        #   * the key has to be `item` -> `items`. #1202zw/#46 COERCE any other business
        #     `/api/` key to the canonical envelope on the first registration, so a fixture
        #     using `posts` silently becomes `items` on both sides and tests nothing. That
        #     coercion exempts exactly `item`/`items`, and single-vs-collection is a real
        #     change a consumer breaks on.
        hubs.registryhub.register_endpoint(
            "GET", "/api/feed",
            schema={"response": {"created_at": "datetime"}, "response_key": "item"},
            provider="backend", agent="backend")
        hubs.registryhub.register_consumer(
            "GET /api/feed", "app/frontend/src/services/api.js", "frontend")
        hubs.registryhub.register_endpoint(
            "GET", "/api/feed",
            schema={"response": {"created_at": "string?"}, "response_key": "items"},
            provider="backend", agent="backend")

        tasks = [t for t in hubs.workhub.snapshot()["tasks"].values()
                 if (t.get("metadata", {}) or {}).get("source") == "registryhub_breaking_change"]
        assert tasks, "the breaking change no longer reaches the consumer"
        desc = " ".join(str(t.get("description") or "") for t in tasks)
        assert "datetime -> str?" in desc, "#1203m5's half went missing"
        assert "item -> items" in desc, "#1203m6's half went missing"
        assert desc.index("item -> items") < desc.index("'is_breaking'")
