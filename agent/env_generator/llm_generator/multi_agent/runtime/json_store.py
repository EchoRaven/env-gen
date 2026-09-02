"""
JsonStore — atomic JSON KV with file lock and monotonic version counter.

Replaces CRDTStore(LWWMap) after Cutover 9. No merge semantics: writes are
linear under file-lock, the LWW Timestamp scaffolding is gone.

On-disk shape:
    {
      "_meta": {"version": N, "last_modified_by": "<agent>", "last_modified_at": <epoch>},
      "<key>": <value>,
      ...
    }
"""

from __future__ import annotations

import fcntl
import json
import logging
import os
import threading
import time
import traceback
from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)

_META_KEY = "_meta"

# #869: (resolved path, thread id) -> nesting depth. Module-level because two JsonStore INSTANCES
# on one file must share it; keyed by thread so cross-thread exclusion is unaffected.
_FLOCK_DEPTH_869: Dict[Any, int] = {}


# Round 8h Stage 2 follow-up — smoke #21 forensic instrumentation.
#
# Smoke #21 (2026-06-03) wedged because the kickoff meeting page
# vanished from ``workhub_pages.json`` between create_meeting (write
# 1) and the orchestrator's "Meeting not found" diagnosis at ~17:23:34
# (write 3). Multi-thread / multi-process / asyncio reproduction
# tests all PASS — the bug needs a production-only condition the
# tests can't capture. This env-gated instrumentation logs every
# JsonStore.update + every silent _load_raw failure so smoke #22 can
# capture the exact write that loses the meeting.
#
# Enable with ENVGEN_DEBUG_JSON_STORE=1 (or =<file_substring> to filter).
# Output: stderr + JSONL line per update to
#   /tmp/envgen_jsonstore_debug-<pid>.log
# Schema per line: {ts, pid, file, op, before_keys, after_keys,
#                   removed, added, agent, caller_traceback}
_DEBUG_ENV = "ENVGEN_DEBUG_JSON_STORE"


def _debug_active(file_path: Path) -> bool:
    """True iff debug instrumentation should fire for this file path."""
    flag = os.environ.get(_DEBUG_ENV, "").strip()
    if not flag:
        return False
    if flag in ("1", "true", "yes", "all"):
        return True
    # Substring match: ENVGEN_DEBUG_JSON_STORE=workhub_documents → fires
    # only on workhub_documents.json.
    return flag in str(file_path)


_DEBUG_LOG_PATH = Path(f"/tmp/envgen_jsonstore_debug-{os.getpid()}.log")


def _debug_log_path_866(file_path: Optional[Path] = None) -> Path:
    """#866: land the forensic log WITH the run, not in /tmp.

    This instrumentation was built for smoke #21 — "the kickoff meeting page vanished from
    workhub_pages.json between write 1 and write 3" — whose reproduction tests all pass and which
    the header still records as needing "a production-only condition the tests can't capture".

    Ten weeks later the same shape is still recurring: 7 corpus runs have `shared/hubs/
    milestones.json` ABSENT while the `.lock` beside it exists, i.e. the store was taken and never
    written, and the run is a total loss (#864 — `start_kickoff` lives inside the loop over the
    roadmap). r136 and r140 are 2026-08-11.

    ★ The instrument was never going to close that. It is off by default, which is a choice, but
    it also wrote to a fixed `/tmp/envgen_jsonstore_debug-<pid>.log` — OUTSIDE the run directory.
    So even switched on, its evidence does not travel with the artifacts that would explain it,
    and whoever finds a dead run three days later has the store, the logs, the captures and the
    agent traces, but not the one file built to answer the question.

    A store's path is `<run>/shared/hubs/<name>.json`, so the run root is derivable — no new
    argument, no caller change. `/tmp` remains the fallback for a store outside a run tree."""
    if file_path is not None:
        try:
            hubs = file_path.parent
            if hubs.name == "hubs" and hubs.parent.name == "shared":
                run_logs = hubs.parent.parent / "logs"
                run_logs.mkdir(parents=True, exist_ok=True)
                return run_logs / "jsonstore_debug.jsonl"
        except Exception:
            pass
    return _DEBUG_LOG_PATH


def _debug_emit(record: Dict[str, Any], file_path: Optional[Path] = None) -> None:
    try:
        with open(_debug_log_path_866(file_path), "a") as f:
            f.write(json.dumps(record, default=str) + "\n")
    except Exception:
        pass  # diagnostic must never break production


class _MapView:
    """Proxy passed to `update()` mutators. Mirrors the LWWMap API the old
    call sites expect (`set(k, v, ts=None)`, `delete(k, ts=None)`), but the
    third arg is ignored — writes are linear under JsonStore's file lock."""

    def __init__(self, data: Dict[str, Any]) -> None:
        self._data = data

    def set(self, key: str, value: Any, _ts: Any = None) -> "_MapView":
        if key == _META_KEY:
            raise ValueError(f"{_META_KEY!r} is reserved")
        if value is None:
            self._data.pop(key, None)
        else:
            self._data[key] = value
        return self

    def delete(self, key: str, _ts: Any = None) -> "_MapView":
        if key == _META_KEY:
            raise ValueError(f"{_META_KEY!r} is reserved")
        self._data.pop(key, None)
        return self

    def get(self, key: str) -> Optional[Any]:
        return self._data.get(key) if key != _META_KEY else None

    def value(self) -> Dict[str, Any]:
        return {k: v for k, v in self._data.items() if k != _META_KEY}


class JsonStore:
    def __init__(self, file_path: Path) -> None:
        self.file_path = Path(file_path)
        self._lock = RLock()

    @contextmanager
    def _file_lock(self):
        """#867: re-entrant for THIS thread, because the alternative is an unbounded hang.

        `flock` is per open file description, so a second `_file_lock()` on the same store in the
        same thread opens a NEW fd and blocks against the lock this thread already holds —
        forever. `self._lock` is an RLock and does not stop it.

        The hazard is known: `milestone_registry._reindex` carries the warning verbatim — *"never
        call back into `self._store` / `self._all()` here (JsonStore.update already holds the file
        lock; re-entering it self-deadlocks on a second flock fd)"*. ★ One function observes the
        rule and **nothing enforces it**. Any mutator anywhere that reads the store back deadlocks
        the run, and `update()` runs caller-supplied `mutator(view)` while holding the lock, so
        the rule binds code that lives nowhere near this file.

        Its signature is exactly what 7 corpus runs show: `open(lock_path, "a+")` CREATES the
        `.lock`, then `flock` blocks before anything is written — `.lock` present, `.json` absent,
        no exception, and a run that appears idle. It is also why smoke #21's note says the
        reproduction tests all pass and the bug "needs a production-only condition the tests can't
        capture": a test mutator does not re-enter.

        Re-entering is SAFE once detected — the outer frame already holds the exclusive lock, so
        the inner critical section is protected. What it must not do is stay silent: the mutator
        doing it is still a latent bug (it reads a half-written state), so it is reported once per
        store with the caller's stack."""
        # #869: key the re-entry guard on (resolved path, thread), not on the instance.
        #
        # #867 stopped a store deadlocking against ITSELF. It could not stop two JsonStore objects
        # on the SAME FILE in the same thread, and that pair exists:
        #
        #     registryhub.py:239      JsonStore(hub_dir / "registryhub_verification_chains.json")
        #     chain_executor.py:3178  JsonStore(project_dir / CHAINS_STORE_RELPATH)   # same file
        #
        # There is no store cache anywhere — 46 construction sites, each building its own — so any
        # module that reaches for a hub file directly gets a second handle. `flock` is per open
        # file description, so instance B in the same thread blocks on instance A's lock exactly
        # as a second fd on one instance did, and #867's instance-keyed depth reads 0 for B.
        #
        # A path key covers both. Cross-THREAD and cross-PROCESS exclusion is untouched: the depth
        # map is keyed by thread id, so another thread still takes the real flock and still waits,
        # which is the mutual exclusion the store depends on. Only same-thread nesting — which can
        # never be anything but a hang — is short-circuited.
        _key_869 = (str(self.file_path.resolve()), threading.get_ident())
        depth = _FLOCK_DEPTH_869.get(_key_869, 0)
        if depth:
            if not getattr(self, "_said_reentry_867", False):
                self._said_reentry_867 = True
                import traceback as _tb
                logger.error(
                    "JsonStore RE-ENTRANT file lock on %s — a mutator called back into the store "
                    "while update() held the lock. Before #867 this DEADLOCKED the run (.lock "
                    "present, file never written, no exception). Proceeding under the outer lock; "
                    "fix the mutator to use only the MapView it is given. Caller:\n%s",
                    self.file_path.name, "".join(_tb.format_stack()[-6:-1]),
                )
            _FLOCK_DEPTH_869[_key_869] = depth + 1
            try:
                yield
            finally:
                _FLOCK_DEPTH_869[_key_869] -= 1
            return
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.file_path.with_suffix(self.file_path.suffix + ".lock")
        with open(lock_path, "a+") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            _FLOCK_DEPTH_869[_key_869] = 1
            try:
                yield
            finally:
                _FLOCK_DEPTH_869.pop(_key_869, None)
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _load_raw(self) -> Dict[str, Any]:
        if not self.file_path.exists():
            if _debug_active(self.file_path):
                _debug_emit({
                    "ts": time.time(), "pid": os.getpid(),
                    "file": str(self.file_path),
                    "op": "load_raw_no_file",
                }, self.file_path)   # #866: land it with the run
            return {}
        try:
            with open(self.file_path, "r") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            # Round 8h Stage 2 follow-up: smoke #21 suspect path. If
            # this fires + the next ``update()`` saves an empty pages
            # dict, the meeting page vanishes. Log loud + diagnostic.
            logger.warning(f"JsonStore: failed to load {self.file_path}: {e}")
            # #1202an: a failed load returns {}, and the next update() writes that {} back —
            # so ONE transient corruption silently destroys the whole store. The comment two
            # lines below predicted exactly this ("the meeting page vanishes") and left it.
            # Demonstrated: write {keep_me}, corrupt the file, update() -> the file is
            # {new_key} and keep_me is gone for good. Measured in the corpus: 2 loads failed
            # across 30+ netflix runs — r19's eventhub_inboxes.json truncated at char 147456
            # (144KB exactly) and r11's missing — rare, and each one is total loss of a hub
            # every lane reads.
            #
            # Quarantine the bytes before anything can overwrite them, and let the run carry
            # on with an empty store. Refusing the write instead would wedge every lane on a
            # hub that can never load again; this way the run survives, the data is on disk to
            # recover from, and the log says which file to look at. `_load_failed_1202an` is
            # what `update` reports on, so the loss is announced at the moment it becomes
            # permanent rather than only here.
            self._load_failed_1202an = True
            try:
                import shutil as _sh1202an
                _q = self.file_path.with_suffix(
                    self.file_path.suffix + f".corrupt.{os.getpid()}.{int(time.time())}")
                if self.file_path.exists() and not _q.exists():
                    _sh1202an.copy2(self.file_path, _q)
                    logger.error(
                        "JsonStore: %s could not be parsed; its bytes are preserved at %s "
                        "before anything overwrites them. Everything it held is missing from "
                        "this process until it is restored (#1202an).",
                        self.file_path.name, _q.name)
            except Exception:
                pass
            if _debug_active(self.file_path):
                try:
                    file_size = self.file_path.stat().st_size
                    with open(self.file_path, "rb") as f:
                        head = f.read(200)
                except Exception:
                    file_size = -1
                    head = b"<unreadable>"
                _debug_emit({
                    "ts": time.time(), "pid": os.getpid(),
                    "file": str(self.file_path),
                    "op": "load_raw_silent_empty",
                    "exc": f"{e.__class__.__name__}: {e}",
                    "file_size": file_size,
                    "head_bytes": head.decode("utf-8", errors="replace")[:200],
                    "traceback": traceback.format_stack(),
                }, self.file_path)   # #866: land it with the run
            return {}
        if isinstance(data, dict) and data.get("type") == "LWWMap":
            return self._unwrap_lwwmap(data)
        return data

    @staticmethod
    def _unwrap_lwwmap(data: Dict[str, Any]) -> Dict[str, Any]:
        flat: Dict[str, Any] = {}
        for key, entry in (data.get("entries") or {}).items():
            if not isinstance(entry, dict):
                continue
            value = entry.get("value")
            if value is None:
                continue
            flat[key] = value
        return flat

    def _save_raw(self, data: Dict[str, Any]) -> None:
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.file_path.with_suffix(self.file_path.suffix + f".{os.getpid()}.tmp")
        with open(tmp_path, "w") as f:
            json.dump(data, f, indent=2, default=str)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, self.file_path)

    def _bump_meta(
        self, raw: Dict[str, Any], agent: str, *, last_caller: str = ""
    ) -> None:
        meta = raw.get(_META_KEY) or {"version": 0}
        meta["version"] = int(meta.get("version", 0)) + 1
        meta["last_modified_by"] = agent or meta.get("last_modified_by", "")
        meta["last_modified_at"] = time.time()
        # O14: persist last_caller only when non-empty so on-disk shape is
        # byte-identical for every callsite that doesn't thread caller yet.
        # `last_modified_by` (the actor) is preserved unchanged — every
        # downstream reader's contract is honored.
        if last_caller:
            meta["last_caller"] = last_caller
        raw[_META_KEY] = meta

    def value(self) -> Dict[str, Any]:
        with self._lock, self._file_lock():
            raw = self._load_raw()
        return {k: v for k, v in raw.items() if k != _META_KEY}

    def get(self, key: str) -> Optional[Any]:
        if key == _META_KEY:
            return None
        return self.value().get(key)

    def set(self, key: str, value: Any, agent: str = "") -> None:
        if key == _META_KEY:
            raise ValueError(f"{_META_KEY!r} is reserved")
        with self._lock, self._file_lock():
            raw = self._load_raw()
            raw[key] = value
            self._bump_meta(raw, agent)
            self._save_raw(raw)

    def delete(self, key: str, agent: str = "") -> None:
        if key == _META_KEY:
            raise ValueError(f"{_META_KEY!r} is reserved")
        with self._lock, self._file_lock():
            raw = self._load_raw()
            if key not in raw:
                return
            raw.pop(key, None)
            self._bump_meta(raw, agent)
            self._save_raw(raw)

    def update(
        self,
        mutator: Callable[["_MapView"], "_MapView"],
        change_info: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        with self._lock, self._file_lock():
            self._load_failed_1202an = False
            raw = self._load_raw()
            data = {k: v for k, v in raw.items() if k != _META_KEY}
            if getattr(self, "_load_failed_1202an", False):
                # #1202an: this write is the moment the loss becomes permanent — the store is
                # about to be rewritten from the {} a failed parse produced. Say it HERE, not
                # only at the read, because the read alone reads as a transient hiccup.
                logger.error(
                    "JsonStore: rewriting %s from an EMPTY state because its previous "
                    "contents could not be parsed — every key it held is now gone from the "
                    "file. The original bytes were copied aside next to it; restore from "
                    "there if anything downstream depended on them (#1202an).",
                    self.file_path.name)
            view = _MapView(data)
            result = mutator(view)
            new_data = result.value() if isinstance(result, _MapView) else dict(result or {})
            agent = ""
            last_caller = ""
            if change_info:
                agent = str(change_info.get("agent") or change_info.get("system") or "")
                last_caller = str(change_info.get("last_caller") or "")
            new_raw = {_META_KEY: raw.get(_META_KEY, {"version": 0}), **new_data}
            self._bump_meta(new_raw, agent, last_caller=last_caller)
            # Round 8h Stage 2 follow-up: smoke #21 instrumentation.
            # Snapshot before+after key sets so a forensic trace of
            # smoke #22's writes can show exactly which update lost
            # the meeting page. Diagnostic-only; gated by
            # ENVGEN_DEBUG_JSON_STORE.
            if _debug_active(self.file_path):
                before_keys = set(data.keys())
                after_keys = set(new_data.keys())
                removed = before_keys - after_keys
                added = after_keys - before_keys
                # Only log writes that are non-trivial (have removals,
                # additions, or are a no-op write that resulted from a
                # silent load_empty). A pure metadata-only mutation on
                # a single key is too noisy.
                if removed or added or not data:
                    _debug_emit({
                        "ts": time.time(), "pid": os.getpid(),
                        "file": str(self.file_path),
                        "op": "update",
                        "agent": agent,
                        "before_keys": sorted(before_keys),
                        "after_keys": sorted(after_keys),
                        "removed": sorted(removed),
                        "added": sorted(added),
                        "before_empty": not data,
                        "traceback": traceback.format_stack()[-6:-1],
                    }, self.file_path)   # #866: land it with the run
            self._save_raw(new_raw)
        return new_data

    def get_version(self) -> int:
        with self._lock, self._file_lock():
            raw = self._load_raw()
        return int((raw.get(_META_KEY) or {}).get("version", 0))


__all__ = ["JsonStore"]
