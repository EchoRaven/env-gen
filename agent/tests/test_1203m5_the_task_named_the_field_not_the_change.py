r"""#1203m5: the P0 said WHICH field changed type and never said to what.

`_record_breaking_change` files "Fix breaking change in <endpoint>: type changed created_at"
and its body is the raw payload -- seven boolean flags that are all False on a type change,
plus the field NAMES -- then the consumer files. `detect_breaking_change` holds BOTH types on
the line where it decides (`old_response[key]`, `new_response[key]`) and discarded them.

MEASURED: 441 `Fix breaking change` tasks in 33 of the 39 modern runs (r177 alone 54);
`type changed` names `id` 58 times and `created_at` 48. The cost is re-derivation the
orchestrator did by hand -- r168 and r177 cancel five as false positives with the reason
spelled out: "endpoint schema now declares created_at as `string?` which matches JSON/runtime
frontend-safe timestamp consumption".

Naming it is the whole fix. Calling `datetime -> str` non-breaking is NOT done: #1202om chose
its alias map deliberately, `str -> str?` adds a null, and a field that stopped being a
timestamp is a real change. The lane gets the pair and makes the call.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from env_generator.llm_generator.multi_agent.runtime.hub_registry import HubRegistry
from env_generator.llm_generator.multi_agent.runtime.registryhub import (
    _type_change_sentence_1203m5)


def _detect(tmp_path, old, new):
    return HubRegistry(Path(tmp_path)).hubs.registryhub.detect_breaking_change(
        {"response": old}, {"response": new})


def test_the_detector_records_both_types(tmp_path):
    out = _detect(tmp_path, {"created_at": "datetime", "sound_id": "int"},
                  {"created_at": "string?", "sound_id": "str"})
    assert out["type_changed_fields"] == ["created_at", "sound_id"]
    assert out["type_changes_1203m5"] == {"created_at": "datetime -> str?",
                                          "sound_id": "int -> str"}


def test_1202om_is_untouched(tmp_path):
    """A spelling change is still not a change, and gets no transition entry either."""
    out = _detect(tmp_path, {"is_read": "bool"}, {"is_read": "boolean"})
    assert out["type_changed_fields"] == []
    assert out["type_changes_1203m5"] == {}
    assert out["is_breaking"] is False


def test_the_canonical_spelling_is_what_is_shown(tmp_path):
    """It must report what the comparison USED, or the pair will not explain the verdict."""
    out = _detect(tmp_path, {"n": "integer"}, {"n": "text"})
    assert out["type_changes_1203m5"] == {"n": "int -> str"}


def test_the_sentence_reads_as_a_sentence():
    got = _type_change_sentence_1203m5(
        {"type_changes_1203m5": {"created_at": "datetime -> str?", "sound_id": "int -> str"}})
    assert got == "`created_at` datetime -> str?, `sound_id` int -> str"


def test_the_sentence_declares_its_cut():
    """#1034: a capped list says it was capped."""
    got = _type_change_sentence_1203m5(
        {"type_changes_1203m5": {("f%d" % i): "int -> str" for i in range(9)}}, cap=6)
    assert "not shown" in got and got.count("int -> str") == 6


def test_the_sentence_is_empty_when_there_is_nothing_to_say():
    assert _type_change_sentence_1203m5({"type_changed_fields": ["x"]}) == ""
    assert _type_change_sentence_1203m5({"type_changes_1203m5": {}}) == ""


def test_the_sentence_never_raises():
    for junk in (None, "x", 7, [], {"type_changes_1203m5": "not a dict"}):
        assert _type_change_sentence_1203m5(junk) == ""


def test_the_filed_task_carries_the_pair():
    """The CALLER: what a lane actually receives in its P0.

    #1139/#1148's lesson -- evidence put in a record with no consumer is half a fix -- so the
    assertion is on the task body, not on the detector's return value.
    """
    with tempfile.TemporaryDirectory() as td:
        hubs = HubRegistry(Path(td)).hubs
        hubs.registryhub.register_endpoint(
            "GET", "/api/feed",
            schema={"response": {"created_at": "datetime", "caption": "str"}},
            provider="backend", agent="backend")
        hubs.registryhub.register_consumer(
            "GET /api/feed", "app/frontend/src/services/api.js", "frontend")
        hubs.registryhub.update_schema(
            "GET /api/feed",
            response={"created_at": "string?", "caption": "str"},
            agent="backend")

        tasks = [t for t in hubs.workhub.snapshot()["tasks"].values()
                 if (t.get("metadata", {}) or {}).get("source") == "registryhub_breaking_change"]
        assert tasks, "the breaking change no longer reaches the consumer at all"
        desc = " ".join(str(t.get("description") or "") for t in tasks)
        assert "datetime -> str?" in desc, \
            "the lane is told WHICH field moved and still not to WHAT"
        assert "`created_at`" in desc
        # the pair comes before the payload dump it used to be buried under
        assert desc.index("datetime -> str?") < desc.index("'is_breaking'")
