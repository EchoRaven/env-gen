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
import time
import traceback
from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)

_META_KEY = "_meta"


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


def _debug_emit(record: Dict[str, Any]) -> None:
    try:
        with open(_DEBUG_LOG_PATH, "a") as f:
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
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.file_path.with_suffix(self.file_path.suffix + ".lock")
        with open(lock_path, "a+") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _load_raw(self) -> Dict[str, Any]:
        if not self.file_path.exists():
            if _debug_active(self.file_path):
                _debug_emit({
                    "ts": time.time(), "pid": os.getpid(),
                    "file": str(self.file_path),
                    "op": "load_raw_no_file",
                })
            return {}
        try:
            with open(self.file_path, "r") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            # Round 8h Stage 2 follow-up: smoke #21 suspect path. If
            # this fires + the next ``update()`` saves an empty pages
            # dict, the meeting page vanishes. Log loud + diagnostic.
            logger.warning(f"JsonStore: failed to load {self.file_path}: {e}")
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
                })
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
            raw = self._load_raw()
            data = {k: v for k, v in raw.items() if k != _META_KEY}
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
                    })
            self._save_raw(new_raw)
        return new_data

    def get_version(self) -> int:
        with self._lock, self._file_lock():
            raw = self._load_raw()
        return int((raw.get(_META_KEY) or {}).get("version", 0))


__all__ = ["JsonStore"]
