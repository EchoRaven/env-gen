r"""#1202so: use orjson where it exists, and be exactly the old code where it does not.

After `#1202sj` and `#1202sk` the store's remaining cost was serialisation, and stdlib's is
the floor of what Python can do. Measured on tiktok-r125's real 6.4MB eventhub_events.json,
serialised the way this module does it (one dumps per top-level key):

    json.dumps    72.2 ms          orjson.dumps    7.3 ms      9.9x
    json.loads    35.5 ms          orjson.loads   27.9 ms      1.3x

One `JsonStore.update` on that store: 247.6ms this morning, 126.7ms after #1202sj/#1202sk,
103.9ms now.

OPTIONAL BY CONSTRUCTION, and that is the whole safety argument: orjson is not a declared
dependency of this framework, so the stdlib path stays exactly what it was and is what runs
when the import fails. Every test below runs BOTH paths — a test that only exercises the
machine it was written on would prove nothing about the one that lacks the library.

Two differences, neither of which changes what a file MEANS: orjson writes non-ASCII as UTF-8
rather than \uXXXX escapes, and renders a datetime as ISO-8601 itself instead of routing it
through `default=str`. Verified across all 1,073 corpus hub files, both paths, zero
round-trip differences.

This is the answer to a deferral, not a new idea. The remaining cost was a re-parse inside
`update`, and caching it needs "no caller mutates nested state it got from the store" to hold
across 158 `update()` call sites and 211 `.value()` readers, with silent corruption of the
run's memory as the failure mode. Making the work cheaper needs no invariant at all.
"""
import datetime
import json

import pytest

from env_generator.llm_generator.multi_agent.runtime import json_store as js
from env_generator.llm_generator.multi_agent.runtime.json_store import JsonStore


@pytest.fixture(params=["orjson", "stdlib"])
def encoder(request, monkeypatch):
    """Run every case on both paths, whichever one this machine happens to have."""
    if request.param == "stdlib":
        monkeypatch.setattr(js, "_orjson", None)
    elif js._orjson is None:
        pytest.skip("orjson is not installed here")
    return request.param


@pytest.mark.parametrize("data", [
    {},
    {"a": 1},
    {"nested": {"deep": [1, None, True, {"x": 2}]}},
    {"k": 'quotes " and \\ backslash'},
    {"unicode": "中文 and emoji 🎬"},
    {"big": "y" * 5000},
])
def test_it_round_trips_on_both_paths(encoder, data):
    assert json.loads(js._serialize_store_1202sj(data)) == data


def test_the_two_paths_agree_on_ordinary_data(monkeypatch):
    if js._orjson is None:
        pytest.skip("orjson is not installed here")
    data = {"n": {"deep": [1, None, True]}, "k": "中文", "s": "plain"}
    fast = json.loads(js._serialize_store_1202sj(data))
    monkeypatch.setattr(js, "_orjson", None)
    slow = json.loads(js._serialize_store_1202sj(data))
    assert fast == slow


def test_a_datetime_survives_as_a_string_either_way(encoder):
    out = json.loads(js._serialize_store_1202sj({"when": datetime.datetime(2026, 1, 2)}))
    assert isinstance(out["when"], str) and out["when"].startswith("2026-01-02")


def test_a_value_neither_encoder_understands_still_writes(encoder):
    out = json.loads(js._serialize_store_1202sj({"obj": object(), "n": 1}))
    assert out["n"] == 1 and isinstance(out["obj"], str)


def test_non_string_keys_still_go_through_json(encoder):
    assert json.loads(js._serialize_store_1202sj({1: "x"})) == {"1": "x"}


def test_one_line_per_key_survives_the_faster_encoder(encoder):
    """The forensic property #1202sj exists for: `grep` over a hub file finds one match per
    record. A faster encoder must not quietly take it away."""
    out = js._serialize_store_1202sj({"e1": {"t": "a"}, "e2": {"t": "b"}})
    assert len([l for l in out.splitlines() if l.startswith('"e')]) == 2


# --- through the store itself ---------------------------------------------------------

def test_a_store_written_and_read_back_on_both_paths(encoder, tmp_path):
    s = JsonStore(tmp_path / "x.json")
    s.update(lambda m: m.set("k1", {"v": 1, "text": "中文"}, "a"), change_info=None)
    s.update(lambda m: m.set("k2", {"v": [1, 2, None]}, "a"), change_info=None)
    again = JsonStore(tmp_path / "x.json")
    assert again.get("k1") == {"v": 1, "text": "中文"}
    assert again.get("k2") == {"v": [1, 2, None]}
    assert again.get_version() == 2


def test_a_file_written_by_one_path_reads_on_the_other(tmp_path, monkeypatch):
    """A run that starts with orjson and resumes without it (or the reverse) must not find
    its own hubs unreadable."""
    if js._orjson is None:
        pytest.skip("orjson is not installed here")
    path = tmp_path / "x.json"
    JsonStore(path).update(lambda m: m.set("k", {"u": "中文", "n": 1}, "a"), change_info=None)
    monkeypatch.setattr(js, "_orjson", None)
    assert JsonStore(path).get("k") == {"u": "中文", "n": 1}


def test_a_corrupt_file_still_fails_the_way_this_module_expects(encoder, tmp_path):
    """#1202an's loss-reporting path keys off the stdlib parse failing; a second parser must
    not swallow it into a different shape."""
    path = tmp_path / "x.json"
    path.write_text("{not json at all")
    s = JsonStore(path)
    assert s.get("anything") is None        # best-effort, as before
    assert getattr(s, "_load_failed_1202an", False) is True


def test_the_fallback_is_what_runs_without_the_library(monkeypatch, tmp_path):
    """The safety argument in one assertion: with the import gone, nothing changes."""
    monkeypatch.setattr(js, "_orjson", None)
    s = JsonStore(tmp_path / "x.json")
    s.update(lambda m: m.set("k", {"v": 1}, "a"), change_info=None)
    assert JsonStore(tmp_path / "x.json").get("k") == {"v": 1}
