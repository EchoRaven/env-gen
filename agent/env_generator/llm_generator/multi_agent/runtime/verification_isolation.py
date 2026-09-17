"""#1202qe: verification leaves no data behind.

Validation, the browser test-user and the test-user squad all drive the LIVE stack as real
users: they register accounts, post videos, follow, comment and open live streams. Every row
lands in the same `default` tenant the app renders, and nothing removed it. tiktok-r126's
final captures showed it: "Suggested LIVE creators" listed `Verifier Settings`, `Core A` and
`Owner M1` (0 viewers, blank avatars) - 63 users in `default`, most of them the verifier's -
and M3's chain failed on `POST /api/users/1/follow -> 409 duplicate` left by an earlier pass.

A tenant does not isolate them: projected reads do not filter on tenant, a row's tenant is the
column default, and a chain user in another tenant could not read the seed it verifies against.
Deleting "their" rows needs the app's ownership graph, which differs per app and is lane code.

What is generic is the database itself: take a data-only snapshot of the freshly seeded state
before a verification pass and put it back afterwards, in ONE transaction. A restore that fails
rolls back and leaves the data as it was; a snapshot that failed restores nothing.
`ENVGEN_VERIFY_DB_ISOLATION=0` turns it off.
"""
from __future__ import annotations

import os
import re
import subprocess
import threading
from pathlib import Path
from typing import Any, Dict, Optional

_SNAP_DIR = "/tmp"


def enabled_1202qe() -> bool:
    return str(os.environ.get("ENVGEN_VERIFY_DB_ISOLATION", "1")).strip().lower() not in (
        "0", "false", "off", "no")


def compose_for_project_1202qe(project_dir: Any) -> Optional[Path]:
    """The run's compose file, from a project dir (run root or its app/)."""
    try:
        proj = Path(str(project_dir))
    except Exception:
        return None
    for cand in (proj / "docker" / "docker-compose.yml",
                 proj.parent / "docker" / "docker-compose.yml",
                 proj / "docker-compose.yml"):
        if cand.exists():
            return cand
    return None


def _tag(tag: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", str(tag or "verify"))[:40]


def _exec(cid: str, script: str, timeout: int) -> subprocess.CompletedProcess:
    from .container_runtime import runtime_bin
    return subprocess.run([runtime_bin(), "exec", "-i", cid, "sh", "-c", script],
                          capture_output=True, text=True, timeout=timeout)


def _db_cid(compose: Path, timeout: int) -> str:
    from .seed_audit import _db_container_1039
    return _db_container_1039(compose, timeout)


def snapshot_db_1202qe(compose: Any, tag: str, timeout: int = 120) -> Dict[str, Any]:
    """Dump the public schema's DATA inside the database container. {ok, error}."""
    if not enabled_1202qe():
        return {"ok": False, "error": "disabled"}
    try:
        cid = _db_cid(Path(str(compose)), 20)
        if not cid:
            return {"ok": False, "error": "no database container"}
        t = _tag(tag)
        script = (
            f'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --data-only --disable-triggers '
            f'--schema=public -f {_SNAP_DIR}/_fw_snap_{t}.sql && '
            f'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tA -c '
            f'"SELECT string_agg(format(\'%I.%I\', schemaname, tablename), \',\') '
            f'FROM pg_tables WHERE schemaname = \'public\'" > {_SNAP_DIR}/_fw_snap_{t}.tables '
            f'&& test -s {_SNAP_DIR}/_fw_snap_{t}.tables')
        res = _exec(cid, script, timeout)
        if res.returncode != 0:
            return {"ok": False, "error": (res.stderr or res.stdout or "")[-300:]}
        return {"ok": True, "container": cid, "tag": t}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def restore_db_1202qe(compose: Any, tag: str, timeout: int = 180) -> Dict[str, Any]:
    """Truncate every snapshotted table and reload the snapshot, atomically. {ok, error}."""
    if not enabled_1202qe():
        return {"ok": False, "error": "disabled"}
    try:
        cid = _db_cid(Path(str(compose)), 20)
        if not cid:
            return {"ok": False, "error": "no database container"}
        t = _tag(tag)
        snap, tables = f"{_SNAP_DIR}/_fw_snap_{t}.sql", f"{_SNAP_DIR}/_fw_snap_{t}.tables"
        script = (
            f'test -s {snap} && test -s {tables} || exit 3; '
            f'{{ echo "TRUNCATE TABLE $(cat {tables}) RESTART IDENTITY CASCADE;"; cat {snap}; }} '
            f'| psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 '
            f'--single-transaction -q -o /dev/null && rm -f {snap} {tables}')
        res = _exec(cid, script, timeout)
        if res.returncode == 3:
            return {"ok": False, "error": "no snapshot in the container (it was recreated)"}
        if res.returncode != 0:
            return {"ok": False, "error": (res.stderr or res.stdout or "")[-300:]}
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


# Active scopes by database CONTAINER id. Overlapping verifiers (the squad in the background, a
# browser walk, a validation) must not restore under each other: restoring while another is
# mid-flight deletes the accounts and rows it is still using and fails it spuriously. So the
# first scope on a container takes the snapshot, later ones join it, and only the LAST to exit
# restores. A validation's `down -v` makes a new container, hence a new group.
_ACTIVE_1202QE: Dict[str, Dict[str, Any]] = {}
_LOCK_1202QE = threading.Lock()


class isolated_verification_1202qe:
    """`with isolated_verification_1202qe(project_dir, "squad", logger):` - snapshot on entry,
    restore on exit (shared across overlapping scopes). Never raises; says what it did."""

    def __init__(self, project_dir: Any, tag: str, logger: Any = None):
        self.compose = compose_for_project_1202qe(project_dir)
        self.tag, self.logger, self.cid = tag, logger, ""

    def _say(self, level: str, msg: str, *a: Any) -> None:
        try:
            if self.logger is not None:
                getattr(self.logger, level)(msg, *a)
        except Exception:
            pass

    def __enter__(self):
        if self.compose is None or not enabled_1202qe():
            return self
        try:
            self.cid = _db_cid(self.compose, 20)
        except Exception:
            self.cid = ""
        if not self.cid:
            return self
        with _LOCK_1202QE:
            group = _ACTIVE_1202QE.get(self.cid)
            if group is not None:
                group["count"] += 1
                return self
            snap = snapshot_db_1202qe(self.compose, self.tag)
            if not snap.get("ok"):
                self._say("warning", "#1202qe no data snapshot before %s (%s): its test data "
                          "will stay in the app's database", self.tag, snap.get("error"))
                self.cid = ""
                return self
            _ACTIVE_1202QE[self.cid] = {"count": 1, "tag": self.tag}
        return self

    def __exit__(self, *exc: Any) -> bool:
        if not self.cid:
            return False
        with _LOCK_1202QE:
            group = _ACTIVE_1202QE.get(self.cid)
            if group is None:
                return False
            group["count"] -= 1
            if group["count"] > 0:
                return False
            _ACTIVE_1202QE.pop(self.cid, None)
            tag = group["tag"]
        r = restore_db_1202qe(self.compose, tag)
        if not r.get("ok") and "recreated" in str(r.get("error")):
            # The database this scope snapshotted is gone: a validation's `down -v` replaced it
            # with a freshly seeded one. There is nothing of this scope's to restore; writers
            # on the new database hold scopes of their own.
            self._say("info", "#1202qe nothing to restore after %s: its database was recreated "
                      "and re-seeded while it ran", self.tag)
            return False
        if r.get("ok"):
            self._say("info", "#1202qe restored the seeded data after %s: the accounts and "
                      "rows verification created are gone", self.tag)
        else:
            self._say("warning", "#1202qe could not restore the data after %s (%s): its test "
                      "accounts and rows remain visible to the next capture", self.tag,
                      r.get("error"))
        return False
