r"""#867: a mutator that read the store back deadlocked the run, forever, in silence.

The first link of #862→#866's chain, and the one every earlier ticket had to leave open.

`JsonStore.update()` runs **caller-supplied `mutator(view)` while holding the file lock**, and
`_file_lock()` was:

    with open(lock_path, "a+") as lock_file:          # <- CREATES the .lock
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)   # <- blocks, no LOCK_NB, no timeout

`flock` is per **open file description**, so a second `_file_lock()` on the same store in the same
thread opens a NEW fd and blocks against the lock that thread already holds. `self._lock` is an
`RLock` and does not stop it. The wait is unbounded.

★ **The hazard was known and enforced nowhere.** `milestone_registry._reindex` carries the warning
verbatim — *"never call back into `self._store` / `self._all()` here (JsonStore.update already
holds the file lock; re-entering it self-deadlocks on a second flock fd)"*. One function observes
the rule; the rule binds every mutator in the codebase, including ones that live nowhere near it.

**It matches the corpus exactly.** 7 runs (r19, r35, r38, r42, r44, r136, r140) have
`shared/hubs/milestones.json` **absent while the `.lock` exists** — `open()` created the lock,
`flock` blocked before anything was written — with **no exception** and a run that looks idle.
#864 established what an unwritten roadmap costs: `start_kickoff` runs inside the loop over it, so
the kickoff meeting never opens and backend/frontend/verifier never wake.

★ It is also why **smoke #21's note says the reproduction tests all pass** and the bug *"needs a
production-only condition the tests can't capture"*. A test mutator does not re-enter.

**Re-entering is safe once detected** — the outer frame holds the exclusive lock, so the inner
critical section is protected. What it must not be is silent: the mutator is still a latent bug
(it reads a half-written state), so it is reported once per store with the caller's stack.
"""
import logging
import pathlib
import tempfile

import pytest

from env_generator.llm_generator.multi_agent.runtime.json_store import JsonStore


def _store():
    return JsonStore(pathlib.Path(tempfile.mkdtemp()) / "x.json")


def test_a_plain_update_still_works():
    """Non-vacuity: the common path must be untouched."""
    st = _store()
    st.update(lambda m: m.set("a", 1, "t"), change_info={"agent": "t"})
    assert st.value() == {"a": 1}


def test_a_reentrant_mutator_completes_instead_of_hanging():
    """★ The defect. Before #867 this call never returned — the test would time out, which is why
    it could not have been written before the guard existed."""
    st = _store()

    def mut(m):
        m.set("a", 1, "t")
        st.value()              # the re-entry
        return m

    st.update(mut, change_info={"agent": "t"})
    assert st.value() == {"a": 1}


def test_the_write_actually_lands():
    """The corpus signature is `.lock` present, `.json` absent. The point of the fix is that the
    file appears."""
    st = _store()
    st.update(lambda m: (m.set("k", "v", "t"), st.value())[0], change_info={"agent": "t"})
    assert st.file_path.exists(), "the store was taken and never written — #862's signature"
    assert st.value() == {"k": "v"}


def test_the_reentry_is_reported_with_a_stack(caplog):
    """★ Not silent. The mutator is still a latent bug — it reads a half-written state — so the
    guard has to name the caller, or the deadlock is merely traded for a wrong read."""
    st = _store()
    with caplog.at_level(logging.ERROR):
        st.update(lambda m: (m.set("a", 1, "t"), st.value())[0], change_info={"agent": "t"})
    msgs = [r.getMessage() for r in caplog.records if "RE-ENTRANT" in r.getMessage()]
    assert msgs, [r.getMessage() for r in caplog.records]
    assert "mutator(view)" in msgs[0] or "update" in msgs[0], msgs[0]
    assert "x.json" in msgs[0]


def test_it_says_it_once_per_store(caplog):
    """A store is written on nearly every hub operation; a per-call error would drown the log —
    #845's defect."""
    st = _store()
    with caplog.at_level(logging.ERROR):
        for _ in range(3):
            st.update(lambda m: (m.set("a", 1, "t"), st.value())[0], change_info={"agent": "t"})
    assert sum("RE-ENTRANT" in r.getMessage() for r in caplog.records) == 1


def test_the_depth_unwinds():
    """A leaked depth would make every later acquisition skip the real lock — trading a deadlock
    for a lost mutual exclusion, which is far worse."""
    st = _store()
    st.update(lambda m: (m.set("a", 1, "t"), st.value())[0], change_info={"agent": "t"})
    assert getattr(st, "_flock_depth_867", 0) == 0
    st.update(lambda m: m.set("b", 2, "t"), change_info={"agent": "t"})
    assert getattr(st, "_flock_depth_867", 0) == 0
    assert st.value() == {"a": 1, "b": 2}


def test_the_depth_unwinds_even_when_the_mutator_raises():
    st = _store()
    with pytest.raises(ValueError):
        st.update(lambda m: (_ for _ in ()).throw(ValueError("boom")),
                  change_info={"agent": "t"})
    assert getattr(st, "_flock_depth_867", 0) == 0
    st.update(lambda m: m.set("ok", 1, "t"), change_info={"agent": "t"})
    assert st.value() == {"ok": 1}


def test_two_stores_on_one_file_still_serialise():
    """★ The guard is per INSTANCE, deliberately. Two JsonStore objects (or two processes) on the
    same path must still take the real flock — the fix is for self-re-entry only, and weakening
    cross-instance exclusion would corrupt the store rather than hang it."""
    p = pathlib.Path(tempfile.mkdtemp()) / "x.json"
    a, b = JsonStore(p), JsonStore(p)
    a.update(lambda m: m.set("a", 1, "t"), change_info={"agent": "t"})
    b.update(lambda m: m.set("b", 2, "t"), change_info={"agent": "t"})
    assert a.value() == {"a": 1, "b": 2}
    assert getattr(a, "_flock_depth_867", 0) == 0 and getattr(b, "_flock_depth_867", 0) == 0


def test_the_documented_hazard_is_still_documented():
    """Non-vacuity for the premise: if `_reindex`'s warning is ever removed, this ticket's story
    should be re-read rather than assumed."""
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import milestone_registry as mr
    assert "self-deadlocks on a second flock fd" in inspect.getsource(mr)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
