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
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator, Dict

from .message_format import warn_once_1201

# The verbs that create or destroy containers. `build`, `ps`, `logs`, `config`, `images`,
# `pull` and `version` are absent on purpose -- see the module docstring.
_LIFECYCLE_OPS_1202HN = frozenset({"up", "down", "stop", "start", "restart", "rm", "kill"})

_LOCK_NAME_1202HN = ".compose.lock"


# #1202kz: what this PROCESS last did to a compose project, so a "not running" report can
# tell a reader whether it is an anomaly or the expected consequence of our own teardown.
#
# Measured over 21 days of logs: `is NOT RUNNING` is emitted 3852 times, and classifying each
# against this process's own preceding lifecycle verb gives 1899 (49.3%) after our own `down`,
# 525 (13.6%) before anything was ever started, and 1428 (37.1%) after an `up` -- the only
# genuinely anomalous group. All 3852 carry the same alarmed wording, so the real ones sit
# 2:1 under noise. The corpus cycles hard enough for that to matter: 2318 `up` against 2541
# `down` across 99 runs (netflix-r30 alone: 138 up / 143 down).
#
# In-process only, deliberately. RunHub drives the SAME project from its own subprocess (see
# #1202hn), so silence here means "this process did not do it" -- never "nobody did". The
# wording must not claim more than that.
_LAST_LIFECYCLE_1202KZ: Dict[str, Any] = {}


def record_lifecycle_1202kz(compose_file: Any, verb: Any) -> None:
    """Remember that THIS process just ran `verb` against `compose_file`. Never raises."""
    try:
        v = str(verb or "").strip().split()[0].lower()
        if v in _LIFECYCLE_OPS_1202HN:
            _LAST_LIFECYCLE_1202KZ[str(compose_file)] = (v, time.time())
    except Exception:
        pass


def last_lifecycle_1202kz(compose_file: Any):
    """``(verb, age_seconds)`` for this process's last lifecycle op, or ``None``."""
    try:
        rec = _LAST_LIFECYCLE_1202KZ.get(str(compose_file))
        if not rec:
            return None
        return rec[0], max(0.0, time.time() - float(rec[1]))
    except Exception:
        return None


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


def stack_identity_1202ne(compose_file: Any, timeout_s: float = 20.0):
    """#1202ne: which containers ARE this project's stack right now, and since when.

    A frozenset of ``"<container id> <StartedAt>"``, empty when nothing is running, or ``None``
    when it cannot be read. `down`/`up`, `--force-recreate` and `restart` each change a member
    (new id or new start time); an `up -d` over an unchanged stack changes none, because it
    disturbed nothing. Read-only: `ps` and `inspect` are not lifecycle verbs and take no lock.

    Why a snapshot and not the lock or #1202kz's record: the lane's `docker_up` tool spawns
    compose from its own worktree with neither, and RunHub runs in its own subprocess. The
    containers are the one place every one of those writers leaves a mark.
    """
    import subprocess
    try:
        from .container_runtime import runtime_bin as _rb
        _bin = _rb()
    except Exception:
        _bin = "docker"
    try:
        cf = Path(str(compose_file))
        ps = subprocess.run([_bin, "compose", "-f", str(cf), "ps", "-q"], cwd=str(cf.parent),
                            capture_output=True, text=True, timeout=timeout_s)
        if ps.returncode != 0:
            return None
        ids = [ln.strip() for ln in (ps.stdout or "").splitlines() if ln.strip()]
        if not ids:
            return frozenset()
        ins = subprocess.run([_bin, "inspect", "-f", "{{.Id}} {{.State.StartedAt}}", *ids],
                             capture_output=True, text=True, timeout=timeout_s)
        if ins.returncode != 0:
            # a container listed a moment ago is already gone: the stack is changing right now
            return frozenset({"(vanished during inspect)"})
        return frozenset(ln.strip() for ln in (ins.stdout or "").splitlines() if ln.strip())
    except Exception as _e:
        warn_once_1201("stack_identity_1202ne",
                       "cannot read the stack's container identity; a browser walk that "
                       "overlaps a stack recycle will be judged as if the app were blank", _e)
        return None


def stack_age_s_1202qz(compose_file: Any, timeout_s: float = 20.0):
    """Seconds since the YOUNGEST container of this stack started; None when unreadable.

    Reads `stack_identity_1202ne`'s own `"<id> <StartedAt>"` rows rather than shelling out
    again, so there is one place that knows what the stack's identity looks like.

    Why the youngest: a recreate replaces containers one at a time, and what matters to a
    caller about to judge the app is how long ago the LAST thing came up.
    """
    from datetime import datetime, timezone
    ident = stack_identity_1202ne(compose_file, timeout_s=timeout_s)
    if not ident:
        return None
    newest = None
    for row in ident:
        parts = str(row).split(None, 1)
        if len(parts) != 2:
            continue
        stamp = parts[1].strip()
        try:                                   # docker emits RFC3339 with nanoseconds
            if stamp.endswith("Z"):
                stamp = stamp[:-1] + "+00:00"
            head, _, rest = stamp.partition(".")
            if rest:
                frac, sign, off = rest.partition("+")
                if not sign:
                    frac, sign, off = rest.partition("-")
                stamp = head + "." + frac[:6] + sign + off
            started = datetime.fromisoformat(stamp)
        except Exception:
            continue
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        if newest is None or started > newest:
            newest = started
    if newest is None:
        return None
    return max(0.0, (datetime.now(timezone.utc) - newest).total_seconds())


# #1202nx: A STACK LEASE — "someone is using this running app; do not tear it down".
#
# #1202hn serialises compose lifecycle verbs against each other; nothing stopped a validation
# from running `down -v` under a consumer that needs the stack UP for minutes. tiktok-r126 M1:
# the test-user squad (12 browser agents) ran from 15:32; validation ran `down -v` at 15:34:21,
# 15:36:50, 15:38:25 and 15:40:24; the squad filed "P0: Backend API ... becomes unreachable
# during auth flow" at 15:35:04 and "Configured API base localhost:8005 is unreachable" at
# 15:38:42 — phantom P0s routed to the backend lane, and 12 paid agents testing a stack that kept
# vanishing (and whose database `-v` wiped). #1202ne discards a browser walk AFTER the fact; this
# keeps the teardown from happening while the lease is held.
#
# In-process on purpose: the squad, the browser walk, the visual capture, run_validation and the
# lane docker tools all run inside the generator process. Bounded: a teardown waits at most
# ENVGEN_STACK_LEASE_WAIT_SEC (default 900) and then proceeds, audibly — a lease can never wedge.
_STACK_LEASES_1202NX: Dict[str, Dict[str, float]] = {}
_STACK_LEASES_LOCK_1202NX = threading.Lock()   # holders and waiters run on different threads


def _lease_key_1202nx(project_dir: Any) -> str:
    try:
        return str(Path(str(project_dir)).resolve())
    except Exception:
        return str(project_dir)


@contextmanager
def stack_lease_1202nx(project_dir: Any, holder: str, ttl_s: float = 3600.0) -> Iterator[None]:
    """Hold a lease on this project's running stack for the duration of the block."""
    key = _lease_key_1202nx(project_dir)
    token = "%s#%s" % (holder, id(object()))
    with _STACK_LEASES_LOCK_1202NX:
        _STACK_LEASES_1202NX.setdefault(key, {})[token] = time.time() + max(1.0, float(ttl_s))
    try:
        yield
    finally:
        with _STACK_LEASES_LOCK_1202NX:
            _STACK_LEASES_1202NX.get(key, {}).pop(token, None)


def active_stack_leases_1202nx(project_dir: Any) -> list:
    now = time.time()
    with _STACK_LEASES_LOCK_1202NX:
        held = _STACK_LEASES_1202NX.get(_lease_key_1202nx(project_dir)) or {}
        for tok in [t for t, exp in held.items() if exp <= now]:
            held.pop(tok, None)        # an expired lease is a crashed holder, not a user
        return sorted(t.split("#", 1)[0] for t in held)


def wait_for_stack_leases_1202nx(project_dir: Any, who: str, timeout_s: Any = None,
                                 poll_s: float = 2.0, logger: Any = None) -> bool:
    """Block (bounded) until nobody holds a lease on this stack. True when free."""
    try:
        limit = float(timeout_s if timeout_s is not None
                      else (os.environ.get("ENVGEN_STACK_LEASE_WAIT_SEC") or 900))
    except (TypeError, ValueError):
        limit = 900.0
    start = time.time()
    announced = False
    while True:
        holders = active_stack_leases_1202nx(project_dir)
        if not holders:
            return True
        waited = time.time() - start
        if not announced:
            announced = True
            msg = ("#1202nx %s waits to tear the stack down: in use by %s"
                   % (who, ", ".join(holders)))
            try:
                import logging as _logging
                (logger or _logging.getLogger("compose_mutex")).warning(msg)
            except Exception:
                pass
        if waited >= limit:
            warn_once_1201("stack_lease_wait_1202nx",
                           "%s waited %.0fs for the stack lease held by %s and is tearing the "
                           "stack down anyway (a lease must never wedge a run)"
                           % (who, waited, ", ".join(holders)), None)
            return False
        time.sleep(poll_s)
