"""#1202hn -- one compose lifecycle operation at a time, per generated project.

tiktok-web-r105 produced a delivery blocker out of nothing but a race. Inside nine seconds
RunHub's `run_start` and `validation_runner` each ran `docker compose up -d --remove-orphans`
against the same project; one removed a container the other had just created, RunHub's run
recorded `aborted` with `Error response from daemon: No such container`, and
`deliverability_no_successful_run` failed the gate. The stack itself was healthy -- seven
seconds later the run read live seed counts off it (`videos: 28, comments: 295, users: 9`).
Neither caller had any mutual exclusion; each simply spawned its own subprocess.

The lock is a POSIX file lock on `<project>/.compose.lock`, so it holds across threads AND
processes, and it is per project directory: this machine runs 119 containers belonging to
other environments, and serializing every generation against every other one would be a much
worse cure than the disease.

Only the container-LIFECYCLE verbs are serialized. `build` is deliberately excluded -- it took
28s in that same window and is bounded at 900s, so holding the lock across it would trade this
race for RunHub timeouts; `ps`/`logs`/`config` observe and cannot race.

The wait is bounded and its expiry is AUDIBLE, then proceeds: a lock able to wedge a run is
worse than the race it prevents (#1201), and a silent pass-through would make the fallback
indistinguishable from success (#883).
"""
from __future__ import annotations

import errno
import fcntl
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator

from .message_format import warn_once_1201

# The verbs that create or destroy containers. `build`, `ps`, `logs`, `config`, `images`,
# `pull` and `version` are absent on purpose -- see the module docstring.
_LIFECYCLE_OPS_1202HN = frozenset({"up", "down", "stop", "start", "restart", "rm", "kill"})

_LOCK_NAME_1202HN = ".compose.lock"


def is_lifecycle_op_1202hn(args: Iterable[Any]) -> bool:
    """True when this argv runs a container-lifecycle verb.

    The verb is whichever known op appears first; callers pass argv in several shapes
    (`["up", "-d"]` from one site, a full `["docker", "compose", "-f", ..., "up", "-d"]` from
    another), so this scans rather than indexing a fixed position -- indexing is what would
    make a caller's arg style silently disable the lock.
    """
    for a in (args or []):
        tok = str(a).strip().lower()
        if tok in _LIFECYCLE_OPS_1202HN:
            return True
        if tok in ("build", "ps", "logs", "config", "images", "pull", "version", "events"):
            return False
    return False


@contextmanager
def compose_mutex_1202hn(cwd: Any, op: str = "", timeout_s: float = 300.0) -> Iterator[bool]:
    """Hold the project's compose lock for the duration of the block.

    Yields True when the lock was actually held, False when the bounded wait expired and the
    caller proceeded anyway -- so a caller that wants to log the difference can, and nothing
    reads as "locked" when it was not.
    """
    fd = None
    held = False
    try:
        d = Path(str(cwd))
        d.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(d / _LOCK_NAME_1202HN), os.O_CREAT | os.O_RDWR, 0o644)
        deadline = time.time() + max(0.0, float(timeout_s))
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                held = True
                break
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN):
                    raise
                if time.time() >= deadline:
                    warn_once_1201(
                        "compose_mutex.timeout_1202hn",
                        "the compose lock (#1202hn) -- another component has been holding "
                        "this project's compose lifecycle for %.0fs, so `%s` is proceeding "
                        "unserialized and may hit the `No such container` race r105 hit"
                        % (float(timeout_s), op or "?"),
                        exc)
                    break
                time.sleep(0.05)
        yield held
    except Exception as _e1202hn:
        # Never let the guard itself stop a run; say so rather than pretending it held.
        warn_once_1201("compose_mutex.unavailable_1202hn",
                       "the compose lock (#1202hn) -- compose lifecycle operations run "
                       "unserialized, which is the pre-#1202hn behaviour",
                       _e1202hn)
        yield False
    finally:
        if fd is not None:
            try:
                if held:
                    fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)
