r"""#1202an: one transient corruption used to destroy a whole hub, silently.

`_load_raw` returns `{}` when a hub file cannot be parsed, and `update()` then writes that `{}`
back — so every key the store held is gone, permanently, with only a WARNING about the read.
The code's own comment predicted it two lines below the failure and left it there:

    "If this fires + the next update() saves an empty pages dict, the meeting page vanishes."

Demonstrated end to end: write {keep_me}, truncate the file, call update() — the file is now
{new_key} and keep_me does not exist anywhere.

It is rare and it is real. Across 30+ netflix runs the load failed twice: r19's
`eventhub_inboxes.json` truncated at char 147456 (144 KB exactly, a page boundary) and r11's
simply absent. `eventhub_inboxes.json` is the shared inbox every lane reads.

★ What this does NOT do is refuse the write. The store would then never load again and every
lane would wedge on it. The run carries on with an empty store — but the original bytes are
copied aside first, and the loss is announced at the moment it becomes permanent, not only when
the read failed. A read failure alone reads as a hiccup; "this file is being rewritten from
nothing" does not.

The writer itself was already correct — temp file, fsync, os.replace — so this is about
surviving a corruption, not about causing fewer.
"""

import json
import logging
import sys
import tempfile
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

from multi_agent.runtime.json_store import JsonStore  # noqa: E402


def _store_with_data(tmp):
    f = tmp / "hub.json"
    s = JsonStore(f)
    s.update(lambda m: m.set("keep_me", {"important": True}, "test"))
    return s, f


def test_the_original_bytes_are_kept(tmp_path):
    s, f = _store_with_data(tmp_path)
    f.write_text('{"keep_me": {"impor', encoding="utf-8")
    s.update(lambda m: m.set("new_key", 1, "test"))
    saved = [p for p in tmp_path.iterdir() if "corrupt" in p.name]
    assert len(saved) == 1
    assert saved[0].read_text(encoding="utf-8") == '{"keep_me": {"impor'


def test_the_permanent_loss_is_announced_at_the_write(caplog):
    """The read failure alone reads as a hiccup; the rewrite is when data dies."""
    tmp = Path(tempfile.mkdtemp())
    s, f = _store_with_data(tmp)
    f.write_text("{not json", encoding="utf-8")
    with caplog.at_level(logging.ERROR):
        s.update(lambda m: m.set("new_key", 1, "test"))
    assert "now gone from the" in caplog.text
    assert "#1202an" in caplog.text


def test_the_run_is_not_wedged(tmp_path):
    """Refusing the write would leave a store that can never load again."""
    s, f = _store_with_data(tmp_path)
    f.write_text("{not json", encoding="utf-8")
    s.update(lambda m: m.set("new_key", 1, "test"))
    assert json.loads(f.read_text(encoding="utf-8"))["new_key"] == 1


def test_a_healthy_store_is_untouched(tmp_path, caplog):
    s, f = _store_with_data(tmp_path)
    with caplog.at_level(logging.WARNING):
        s.update(lambda m: m.set("second", 2, "test"))
    data = json.loads(f.read_text(encoding="utf-8"))
    assert data["keep_me"]["important"] is True and data["second"] == 2
    assert "#1202an" not in caplog.text
    assert not [p for p in tmp_path.iterdir() if "corrupt" in p.name]


def test_a_missing_file_is_not_treated_as_corruption(tmp_path, caplog):
    """r11's failure was ENOENT. An absent store is legitimately empty, not damaged."""
    s = JsonStore(tmp_path / "never_written.json")
    with caplog.at_level(logging.ERROR):
        assert s.value() == {}
    assert "#1202an" not in caplog.text


def test_quarantine_does_not_overwrite_an_earlier_copy(tmp_path):
    """Two corruptions in one process must not lose the first set of bytes."""
    s, f = _store_with_data(tmp_path)
    f.write_text("{first", encoding="utf-8")
    s.update(lambda m: m.set("a", 1, "test"))
    saved = [p for p in tmp_path.iterdir() if "corrupt" in p.name]
    assert saved and saved[0].read_text(encoding="utf-8") == "{first"
