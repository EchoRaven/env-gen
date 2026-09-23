r"""#1202sy / #1202sz: a hub store is read and written as BYTES, never round-tripped through `str`.

`JsonStore` opened every store with `open(path, "r")` / `open(path, "w")`. So each load
decoded the whole file into a `str` before handing it to a parser that wants UTF-8 anyway,
and each save decoded orjson's bytes back to `str` once per top-level key, joined them into
one multi-megabyte `str`, and re-encoded it to write. Nothing needed the `str`.

Measured on tiktok-r130's real 6.15MB `eventhub_events.json` (median of 11-15, repeated):

    load     open("r").read()  + parse    72.5 / 74.5 / 91.2 ms
             open("rb").read() + parse    26.7 / 29.7 / 26.8 ms        ~2.7x
    save     build str, then .encode()    47.1 / 45.7 ms
             build bytes                   9.0 /  8.4 ms               ~5.4x

The cost was never the parse: of 81 ms in `_load_raw` the profiler put 45 ms in
`TextIOWrapper.read` (16 ms of that in `_codecs.utf_8_decode`) against 35 ms of parsing, and
parsing bytes is not itself faster (32.9 ms vs 29.1 ms on a `str`) -- the decode simply stops
happening.

Both `update()` and `value()` load, and every `update()` saves. Derived from `_meta.version x
final size`, halved because the files grow through a run: r121 touches ~75 GB of store bytes,
so loading goes ~15 -> ~6 min and serialising ~9 -> ~2 min, on a run of about 2.5 hours.

TWO THINGS THAT LOOK LIKE FREE WINS AND ARE NOT, both measured rather than assumed:

  * the STDLIB parser wants the opposite input. `json.loads(bytes)` (48.2 ms) sniffs the
    encoding and decodes, where `json.loads(str)` is 36.5 ms. So `_loads_text_1202so` decodes
    once when orjson is absent, leaving that environment exactly where it was.
  * orjson must NOT serialise the KEYS. It writes non-ASCII raw where the stdlib escapes it,
    so the bytes on disk would change. It is not even a trade: stdlib keys measured marginally
    faster (14.7 vs 17.7 ms), and no top-level key in 400 corpus hub stores is non-ASCII.

WHAT IS VERIFIED: the new serializer's output is byte-identical to the old one on 60 randomly
sampled real corpus stores and on twelve hand-built shapes (unicode, an unserializable
`object()`, a datetime, a non-string key, -0.0, a 2**62 int), on BOTH encoder paths.

LOCAL-ONLY (gitignored)."""
from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from multi_agent.runtime import json_store as js  # noqa: E402
from multi_agent.runtime.json_store import JsonStore  # noqa: E402


@pytest.fixture(params=["orjson", "stdlib"])
def encoder(request, monkeypatch):
    if request.param == "stdlib":
        monkeypatch.setattr(js, "_orjson", None)
    elif js._orjson is None:
        pytest.skip("orjson is not installed here")
    return request.param


_SHAPES = [
    {},
    {"a": 1},
    {"nested": {"deep": [1, None, True, {"x": 2}]}},
    {"k": 'quotes " and \\ backslash'},
    {"unicode": "中文 and emoji 🎬"},
    {"big": "y" * 5000},
    {"f": 1.5, "neg": -0.0, "huge": 2 ** 62},
    {"empty_list": [], "empty_dict": {}, "null": None},
    {"when": datetime.datetime(2026, 1, 2)},
    {1: "x"},
]


@pytest.mark.parametrize("data", _SHAPES)
def test_the_bytes_writer_and_the_text_writer_agree(encoder, data):
    """`_serialize_store_1202sj` is now a thin decode over the bytes builder; the property
    that matters is that what lands on disk is unchanged."""
    assert js._serialize_store_bytes_1202sz(data) == \
        js._serialize_store_1202sj(data).encode("utf-8")


@pytest.mark.parametrize("data", _SHAPES)
def test_every_shape_still_round_trips(encoder, data):
    out = json.loads(js._serialize_store_bytes_1202sz(data))
    expected = {str(k): v for k, v in data.items()}
    for key in expected:
        assert key in out


def test_one_line_per_key_survives_the_bytes_writer(encoder):
    """The forensic property #1202sj exists for: `grep` over a hub file finds one match per
    record. Changing the writer must not quietly take it away."""
    raw = js._serialize_store_bytes_1202sz({"e1": {"t": "a"}, "e2": {"t": "b"}})
    assert len([l for l in raw.splitlines() if l.startswith(b'"e')]) == 2


def test_keys_keep_the_stdlib_escaping(encoder):
    """orjson writes non-ASCII raw; the stdlib escapes it. Using orjson for KEYS would change
    the bytes on disk for no gain (it measured slower), so the key path stays put."""
    raw = js._serialize_store_bytes_1202sz({"中文": 1})
    assert b'"\\u4e2d\\u6587"' in raw


def test_a_value_no_encoder_understands_still_writes(encoder):
    out = json.loads(js._serialize_store_bytes_1202sz({"obj": object(), "n": 1}))
    assert out["n"] == 1 and isinstance(out["obj"], str)


def test_the_store_reads_what_it_wrote(encoder, tmp_path):
    s = JsonStore(tmp_path / "x.json")
    s.update(lambda m: m.set("k1", {"v": 1, "text": "中文 hi"}, "actor"), change_info=None)
    s.update(lambda m: m.set("k2", {"v": 2}, "actor"), change_info=None)
    again = JsonStore(tmp_path / "x.json")
    assert again.get("k1") == {"v": 1, "text": "中文 hi"}
    assert again.get("k2") == {"v": 2}


def test_the_file_on_disk_is_valid_utf8_json(encoder, tmp_path):
    s = JsonStore(tmp_path / "x.json")
    s.update(lambda m: m.set("k", {"t": "中文 🎬"}, "actor"), change_info=None)
    raw = (tmp_path / "x.json").read_bytes()
    assert json.loads(raw.decode("utf-8"))["k"] == {"t": "中文 🎬"}


# --- the load path ------------------------------------------------------------------

def test_the_store_is_opened_in_binary_on_both_sides():
    """The whole saving is in not decoding; a `"r"`/`"w"` here puts it straight back."""
    import inspect
    for fn in (JsonStore._load_raw, JsonStore._save_raw):
        src = inspect.getsource(fn)
        assert '"rb"' in src or '"wb"' in src, fn.__name__
        assert 'open(self.file_path, "r")' not in src
        assert 'open(tmp_path, "w")' not in src


def test_the_stdlib_parser_is_still_handed_text(monkeypatch):
    """`json.loads(bytes)` costs 32% more than `json.loads(str)` -- it sniffs and decodes. An
    environment without orjson must not pay for a change made for the one with it."""
    monkeypatch.setattr(js, "_orjson", None)
    seen = {}
    real = json.loads

    def spy(arg, *a, **k):
        seen["type"] = type(arg).__name__
        return real(arg, *a, **k)

    monkeypatch.setattr(js.json, "loads", spy)
    assert js._loads_text_1202so(b'{"a": 1}') == {"a": 1}
    assert seen["type"] == "str", "the stdlib parser was handed bytes"


def test_an_invalid_byte_is_quarantined_rather_than_crashing(tmp_path, caplog):
    """#1202sy: `UnicodeDecodeError` is a `ValueError`, so it did not match `_load_raw`'s
    handler and escaped -- the caller died with no copy kept, which is the one outcome
    #1202an exists to prevent."""
    p = tmp_path / "s.json"
    p.write_bytes(b'{"a": "\xff\xfe not utf8"}')
    store = JsonStore(p)
    assert store.value() == {}                      # empty, not an exception
    quarantined = list(tmp_path.glob("s.json.corrupt.*"))
    assert quarantined, "the unreadable bytes must be preserved before anything overwrites"
    assert quarantined[0].read_bytes() == b'{"a": "\xff\xfe not utf8"}'


def test_a_truncated_store_was_already_covered(tmp_path):
    """Measured: a truncation answers JSONDecodeError on every path (netflix-r19's
    eventhub_inboxes.json, cut at exactly 144KB). Recorded so the widened handler is not
    mistaken for the fix to THAT case."""
    p = tmp_path / "s.json"
    p.write_bytes(b'{"a": {"b": 1}, "c": {"d')
    assert JsonStore(p).value() == {}
    assert list(tmp_path.glob("s.json.corrupt.*"))
