r"""#869: #867 guarded a store against itself; two handles on one file still hung.

Item 198 listed *"a second `JsonStore` instance for the same file in the same thread"* as out of
that scan's reach and out of #867's protection. It is not hypothetical — the pair exists:

    registryhub.py:239      JsonStore(hub_dir / "registryhub_verification_chains.json")
    chain_executor.py:3178  JsonStore(project_dir / CHAINS_STORE_RELPATH)     # the same file

**There is no store cache anywhere** — 46 construction sites, each building its own handle — so any
module that reaches for a hub file directly gets a second one. `flock` is per open file
description, so instance B blocks on instance A's lock in the same thread exactly as a second fd
on one instance did, and #867's instance-keyed depth reads 0 for B.

The guard is now keyed on **(resolved path, thread id)**. Cross-thread and cross-process
exclusion is deliberately untouched: another thread still takes the real `flock` and still waits,
which is the mutual exclusion the store depends on. Only same-thread nesting is short-circuited,
and same-thread nesting can never be anything but a hang.

★ Worth separating from #867's overclaim (item 198): this ticket, like that one, is a **safety
net**. Two handles on one file is a real and current condition; a *nesting* path between them is
not demonstrated. What is demonstrated is that if one ever appears, it no longer costs the run —
and that the class of "reaches for a hub file directly" is one line of code away in 46 places.
"""
import pathlib
import tempfile
import threading

import pytest

from env_generator.llm_generator.multi_agent.runtime import json_store as js
from env_generator.llm_generator.multi_agent.runtime.json_store import JsonStore


def _path():
    return pathlib.Path(tempfile.mkdtemp()) / "x.json"


def test_two_handles_nested_in_one_thread_complete():
    """★ The defect. Before #869 this never returned."""
    p = _path()
    a, b = JsonStore(p), JsonStore(p)
    a.update(lambda m: (m.set("k", 1, "t"), b.value())[0], change_info={"agent": "t"})
    assert a.value() == {"k": 1}
    assert p.exists(), "the store was taken and never written — #862's signature"


def test_the_depth_map_drains():
    """A leaked entry would make every later acquisition on that path skip the real lock —
    trading a hang for lost mutual exclusion, which is worse."""
    p = _path()
    a, b = JsonStore(p), JsonStore(p)
    a.update(lambda m: (m.set("k", 1, "t"), b.value())[0], change_info={"agent": "t"})
    assert not js._FLOCK_DEPTH_869, js._FLOCK_DEPTH_869


def test_it_drains_when_the_mutator_raises():
    p = _path()
    a, b = JsonStore(p), JsonStore(p)
    with pytest.raises(ValueError):
        a.update(lambda m: (_ for _ in ()).throw(ValueError("boom")), change_info={"agent": "t"})
    assert not js._FLOCK_DEPTH_869, js._FLOCK_DEPTH_869
    a.update(lambda m: m.set("ok", 1, "t"), change_info={"agent": "t"})
    assert a.value() == {"ok": 1}


def test_the_key_is_the_resolved_path_not_the_instance():
    """Two different objects must share one depth entry, or the guard is #867 again."""
    p = _path()
    a, b = JsonStore(p), JsonStore(p)
    seen = {}

    def mut(m):
        seen["depth_keys"] = list(js._FLOCK_DEPTH_869)
        b.value()
        seen["after"] = list(js._FLOCK_DEPTH_869)
        return m

    a.update(mut, change_info={"agent": "t"})
    assert len(seen["depth_keys"]) == 1
    assert seen["after"] == seen["depth_keys"], "the nested handle created a second entry"


def test_a_different_file_is_a_different_key():
    """Non-vacuity for the key: nesting across two DIFFERENT stores is normal and must still take
    both real locks rather than being silently short-circuited."""
    pa, pb = _path(), _path()
    a, b = JsonStore(pa), JsonStore(pb)
    a.update(lambda m: (m.set("k", 1, "t"), b.update(
        lambda n: n.set("j", 2, "t"), change_info={"agent": "t"}))[0], change_info={"agent": "t"})
    assert a.value() == {"k": 1} and b.value() == {"j": 2}
    assert not js._FLOCK_DEPTH_869


def test_another_thread_still_takes_the_real_lock():
    """★ The property that must NOT be weakened. Short-circuiting across threads would turn a hang
    into store corruption. The second thread must block until the first releases, then see the
    first thread's write."""
    p = _path()
    a, b = JsonStore(p), JsonStore(p)
    started, order = threading.Event(), []

    def outer(m):
        m.set("first", 1, "t")
        started.set()
        t.join(timeout=5)
        order.append("outer-done")
        return m

    def worker():
        started.wait(5)
        b.update(lambda m: m.set("second", 2, "t"), change_info={"agent": "t"})
        order.append("worker-done")

    t = threading.Thread(target=worker)
    t.start()
    a.update(outer, change_info={"agent": "t"})
    t.join(timeout=5)
    assert not t.is_alive(), "the worker never completed — cross-thread exclusion broke"
    assert a.value() == {"first": 1, "second": 2}, a.value()
    assert not js._FLOCK_DEPTH_869


def test_the_two_real_handles_on_one_file_still_exist():
    """Non-vacuity for the premise. If a store cache is ever introduced, this ticket's motivation
    changes and the note should be re-read rather than assumed."""
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import chain_executor as ce
    src = inspect.getsource(ce)
    assert "JsonStore(Path(project_dir) / CHAINS_STORE_RELPATH)" in src
    assert 'CHAINS_STORE_RELPATH = Path("shared") / "hubs"' in src


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
