"""Advisory: warn when another test run is already in flight on this work tree.

WHY (2026-09-05): two Claude sessions ran `pytest tests/` against this same work tree
concurrently. Three full runs produced 20 / 3 / 32 failures whose failure sets were
PAIRWISE DISJOINT — zero tests failed in all three — because concurrent runs contend on
temp paths, on files the tests write into the repo, and on CPU. Four rounds of failure
attribution were built on those numbers and every one had to be retracted. Run alone:
14781 passed, 0 failed.

`scripts/suite.sh` takes an exclusive flock so this cannot happen. But the other session
invokes bare `pytest`, and a convention only one side follows is not a convention — so the
warning has to live where EVERY run passes, which is here.

Deliberately ADVISORY, never blocking: a test suite that refuses to start is a worse
failure mode than one that prints a warning, and a stale lock must never wedge CI.
"""
from __future__ import annotations

import os
from pathlib import Path

_LOCK = Path(__file__).resolve().parents[2] / ".suite.lock"
_INFO = Path(__file__).resolve().parents[2] / ".suite.lock.info"


def _holder() -> str | None:
    """Return a description of the other run holding the lock, or None.

    Never raises and never leaves the lock held: it probes with a non-blocking
    acquire and releases immediately.
    """
    try:
        import fcntl
    except Exception:
        return None
    if not _LOCK.exists():
        return None
    fd = None
    try:
        fd = os.open(_LOCK, os.O_RDWR)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            try:
                return _INFO.read_text(encoding="utf-8").strip() or "(no holder record)"
            except Exception:
                return "(no holder record)"
        fcntl.flock(fd, fcntl.LOCK_UN)   # we were only probing
        return None
    except Exception:
        return None
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except Exception:
                pass


def pytest_configure(config):
    # The ENTIRE body is guarded: an advisory must never be able to stop a test run.
    # The first draft called config.get_terminal_writer(), which `hasattr` reports as
    # present but which asserts `terminalreporter is not None` -- the reporter is not
    # registered yet at configure time -- and that took pytest down with INTERNALERROR.
    # Checking that an attribute EXISTS is not checking that calling it WORKS.
    try:
        if os.environ.get("ENVGEN_SUITE_LOCK_HELD") == "1":
            return                  # this run IS the lock holder (scripts/suite.sh)
        held = _holder()
        if not held:
            return
        print("\n" + "=" * 78)
        print("ANOTHER TEST RUN IS ALREADY IN FLIGHT ON THIS WORK TREE.")
        print("Concurrent runs produce disjoint, meaningless failure sets (2026-09-05:")
        print("20 / 3 / 32 failures, pairwise intersection ZERO). Do not trust this")
        print("run's failures until you have re-run it alone.")
        print("")
        for ln in held.splitlines():
            print(f"  holder: {ln}")
        print("")
        print("Use  scripts/suite.sh  (exclusive)  or  SUITE_WAIT=1 scripts/suite.sh  (queue).")
        print("=" * 78 + "\n")
    except Exception:
        pass
