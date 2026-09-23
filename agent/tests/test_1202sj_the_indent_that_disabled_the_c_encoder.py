r"""#1202sj: `indent=2` silently put every hub write on the pure-Python JSON encoder.

`json.dump(..., indent=2)` cannot use the C encoder — CPython selects `c_make_encoder` only
when `indent is None`. Profiling ONE `JsonStore.update` against tiktok-r125's real 6.4MB
eventhub_events.json put 93% of the call inside `_save_raw`, and almost all of that inside
`_iterencode`, the Python encoder's inner loop. The store was not slow because it is big; it
was slow because of one keyword argument.

Measured on that file:

    indent=2        167.0 ms    6.43 MB    178,937 lines
    no indent        79.9 ms    5.26 MB          1 line
    per key          69.4 ms    5.26 MB      5,004 lines

Dropping the indent entirely is simpler and puts the whole store on ONE line, which breaks
`grep` over a hub file — a forensic move this project makes constantly; #673 and #693 are both
built on reading these files across runs, and so is this session's own measurement work. One
line per top-level key keeps that for free, and is the fastest of the three here.

Verified across every hub file in the corpus: 1,073 files, ZERO round-trip differences,
950 MB -> 786 MB (-17%), serialisation 2.3x faster.
"""
import json

import pytest

from env_generator.llm_generator.multi_agent.runtime.json_store import (
    JsonStore, _serialize_store_1202sj as serialize)


# --- it still says exactly the same thing ---------------------------------------------

@pytest.mark.parametrize("data", [
    {},
    {"a": 1},
    {"a": {"b": [1, 2, None, True]}},
    {"k": 'quotes " and \\ backslash'},
    {"unicode": "中文 and emoji 🎬"},
    {"nested": {"deep": {"deeper": {"x": [{"y": 1}]}}}},
])
def test_it_round_trips(data):
    assert json.loads(serialize(data)) == data


def test_a_value_json_cannot_encode_still_falls_back_to_str():
    out = json.loads(serialize({"x": object()}))
    assert isinstance(out["x"], str) and "object" in out["x"]


def test_non_string_keys_go_through_json_itself():
    """Assembling `1: {...}` by hand emits INVALID JSON; json stringifies such keys."""
    assert json.loads(serialize({1: "x", "a": "y"})) == {"1": "x", "a": "y"}
    assert json.loads(serialize({True: 1})) == {"true": 1}


# --- the two properties the change exists for -----------------------------------------

def test_one_line_per_top_level_key():
    """The forensic property: `grep` over a hub file still finds one match per record."""
    out = serialize({"e1": {"t": "a"}, "e2": {"t": "b"}, "e3": {"t": "c"}})
    assert out.count("\n") == 4          # { + three keys ... } -> 4 newlines
    assert len([l for l in out.splitlines() if l.startswith('"e')]) == 3


def test_it_does_not_use_the_slow_encoder():
    """Nothing may reintroduce `indent`, which is what put every write on _iterencode."""
    import inspect

    from env_generator.llm_generator.multi_agent.runtime import json_store

    import ast
    import textwrap

    # Parsed, not grepped: the docstrings here quote `indent=2` as the thing being removed,
    # and a substring check finds its own explanation -- the pgrep-matches-itself shape.
    def _kwargs(fn):
        tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
        return {kw.arg for node in ast.walk(tree) if isinstance(node, ast.Call)
                for kw in node.keywords if kw.arg}

    assert "indent" not in _kwargs(json_store._serialize_store_1202sj), \
        "an indent= argument is back on the store's writer"
    assert "indent" not in _kwargs(json_store.JsonStore._save_raw)
    assert "_serialize_store_1202sj(" in inspect.getsource(json_store.JsonStore._save_raw)


# --- and the store still works end to end ---------------------------------------------

def test_a_store_written_this_way_reads_back(tmp_path):
    s = JsonStore(tmp_path / "x.json")
    s.update(lambda m: m.set("k1", {"v": 1, "text": "hi"}, "actor"), change_info=None)
    s.update(lambda m: m.set("k2", {"v": 2}, "actor"), change_info=None)
    again = JsonStore(tmp_path / "x.json")
    assert again.get("k1") == {"v": 1, "text": "hi"}
    assert again.get("k2") == {"v": 2}


def test_the_file_on_disk_is_valid_json(tmp_path):
    s = JsonStore(tmp_path / "x.json")
    s.update(lambda m: m.set("k", {"a": [1, {"b": None}]}, "actor"), change_info=None)
    raw = json.loads((tmp_path / "x.json").read_text())
    assert raw["k"] == {"a": [1, {"b": None}]}
    assert "_meta" in raw and raw["_meta"]["version"] >= 1


def test_the_version_still_counts_writes(tmp_path):
    """#693's instrument must survive a change to how the bytes are produced."""
    s = JsonStore(tmp_path / "x.json")
    for i in range(4):
        s.update(lambda m, i=i: m.set("k%d" % i, {"i": i}, "actor"), change_info=None)
    assert s.get_version() == 4


# --- #1202sk: `default=` is paid per call, and the per-key writer makes 5,002 of them ------

def test_a_value_json_can_encode_takes_the_fast_path():
    """Whole-object dumps pays for `default=` once (40.1ms either way on the 6.4MB store).
    Per key it is paid 5,002 times: 68.5ms with it against 43.1ms without, 1.6x. Almost every
    value is plain JSON, so the common path must not carry it."""
    import ast
    import inspect
    import textwrap

    from env_generator.llm_generator.multi_agent.runtime import json_store

    tree = ast.parse(textwrap.dedent(inspect.getsource(json_store._serialize_store_1202sj)))
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "dumps"]
    plain = [c for c in calls if not c.keywords]
    assert plain, "every dumps() carries a keyword; the fast path is gone"


def test_the_slow_path_still_catches_what_json_cannot_encode():
    import datetime

    out = json.loads(serialize({"when": datetime.datetime(2026, 9, 23), "n": 1}))
    assert out["n"] == 1
    assert isinstance(out["when"], str) and "2026-09-23" in out["when"]


def test_one_unencodable_value_does_not_poison_its_neighbours():
    out = json.loads(serialize({"ok": [1, 2], "bad": object(), "also_ok": {"a": None}}))
    assert out["ok"] == [1, 2] and out["also_ok"] == {"a": None}
    assert isinstance(out["bad"], str)


def test_a_store_holding_an_unencodable_value_still_writes(tmp_path):
    """End to end: the fallback has to work through JsonStore, not just the helper."""
    import datetime

    s = JsonStore(tmp_path / "x.json")
    s.update(lambda m: m.set("k", {"at": datetime.datetime(2026, 1, 2)}, "actor"),
             change_info=None)
    assert "2026-01-02" in JsonStore(tmp_path / "x.json").get("k")["at"]
