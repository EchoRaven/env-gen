# Cutover 9: CRDT Scaffolding Purge

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish what Cutover 5 ("final purge") started — eliminate the `CRDTStore`/`LWWMap`/`Timestamp`/`crdt_dir` surface that the hubs still drag along even though no CRDT merge semantics are used anywhere.

**Architecture:** Replace `CRDTStore(LWWMap)` with a plain `JsonStore` (atomic JSON KV with file lock + monotonic version counter). Drop the `Timestamp.now(agent)` stamping at hub call sites — the store records its own `_meta` on write. Rename `crdt_dir` → `hub_dir` in every constructor + caller. Move on-disk JSON from `shared/crdt/` → `shared/hubs/` with a one-shot auto-migration on `HubRegistry` init. Delete `crdt_store.py`, `crdt_types.py`, `crdt_validation.py`, `crdt_observer_stub.py`.

**Tech Stack:** Python 3.11 (`dt` conda env at `/home/haibotong/miniconda3/envs/dt/bin/python`), unittest, `fcntl` file locking, atomic `os.replace` writes.

---

## Context for Worker

### Why this cutover exists

The four hubs were originally built on CRDT primitives (`LWWMap`, `LWWRegister`, `GCounter`, `ORSet`) for multi-process concurrent edits. Across Cutovers 1–5, the runtime stopped relying on those merge semantics (CodeHub uses real git, WorkHub/APIHub/EventHub are single-writer-per-agent via file locks). Cutover 5 deleted the `CRDTWorkspace` orchestrator but left the storage layer wearing CRDT clothes: every hub still constructs `CRDTStore(crdt_dir / "foo.json", LWWMap)`, every write stamps a `Timestamp.now(agent)` that nothing reads, and the on-disk directory is still `shared/crdt/`. Roughly **1137 lines** across `crdt_store.py` (163), `crdt_types.py` (304), `crdt_validation.py` (603), `crdt_observer_stub.py` (67) are scaffolding for behavior that no longer exists.

### What the call sites actually need from a store

Grepping the four hub files (`apihub.py`, `eventhub.py`, `hubs/codehub/`, `hubs/workhub/`), only these `CRDTStore` methods are used:

```
store.update(lambda m: m.set(key, value, ts))       # write one key
store.update(lambda m: m.delete(key, ts))           # delete one key
store.update(lambda m: m, change_info={...})        # touch (for ensure_documents)
store.value()                                       # full dict
store.get().get(key)                                # single read
store.get_version()                                 # monotonic int
```

No `.merge()`, no `.observe()`, no `.poll()`, no `.has_changes_since()`, no `.get_changes_since()` at any call site outside `crdt_store.py` itself. The `ts` argument is created from `Timestamp.now(agent)` and immediately handed to the store, where it's stored but never compared (no concurrent writer arrives with a competing timestamp, because file-lock serialization means writes are linear).

### Replacement contract

`JsonStore(file_path: Path)` exposes:
- `set(key: str, value: Any, agent: str = "") -> None`
- `delete(key: str, agent: str = "") -> None`
- `value() -> Dict[str, Any]` — top-level dict, never includes `_meta`
- `get(key: str) -> Optional[Any]` — single value, None if missing
- `update(mutator: Callable[[dict], dict], change_info: dict | None = None) -> dict` — back-compat for the existing `update(lambda m: m.set(k, v, ts))` call sites; the mutator receives a `_LegacyMapView` proxy whose `.set()` and `.delete()` ignore the third `ts` arg
- `get_version() -> int` — monotonic counter persisted in `_meta`

On-disk format:
```json
{
  "_meta": {"version": 7, "last_modified_by": "design", "last_modified_at": 1716552000.0},
  "endpoint:GET:/api/feed": { ... },
  "endpoint:POST:/api/feed": { ... }
}
```

Legacy LWWMap read compat (`_load` detects `"type": "LWWMap"`):
```json
{
  "type": "LWWMap",
  "entries": {
    "endpoint:GET:/api/feed": {"type": "LWWRegister", "value": {...}, "timestamp": {...}}
  }
}
```
…is unwrapped to `{<key>: <value>, ...}` (drop timestamps). The first write then persists in the new flat shape — no separate migration step needed.

### Directory migration

`shared/crdt/` → `shared/hubs/`. `HubRegistry.__init__` checks both: if only `shared/crdt/` exists, copy its `.json` files into `shared/hubs/` once (rename is fine since we hold the only process handle). If both exist, prefer `shared/hubs/`. New deployments start clean in `shared/hubs/`.

### Files that import CRDT today (8 live + 4 dead)

Live imports (must be migrated):
- `runtime/apihub.py` — 13 `CRDTStore(...)` constructors + ~12 `Timestamp.now()` call sites
- `runtime/eventhub.py` — 4 `CRDTStore(...)` constructors + ~6 `Timestamp.now()` call sites
- `runtime/hubs/codehub/stores.py` — 8 `CRDTStore(...)` constructors
- `runtime/hubs/codehub/service.py` — `from ...crdt_types import Timestamp` (1 site)
- `runtime/hubs/workhub/stores.py` — N `CRDTStore(...)` constructors (verify count)
- `runtime/hubs/workhub/service.py` — `Timestamp.now()` usages (verify)
- `runtime/hub_registry.py` — `self._store_dir = self.base_dir / "shared" / "crdt"` (1 site, plus comments)
- `runtime/__init__.py` — re-exports `CRDTStore`, `LWWMap`, `Timestamp`, observer stubs

Dead modules (to delete in Task 9):
- `runtime/crdt_store.py` (163 lines)
- `runtime/crdt_types.py` (304 lines)
- `runtime/crdt_validation.py` (603 lines — never imported outside its own file)
- `runtime/crdt_observer_stub.py` (67 lines — only re-exported by `runtime/__init__.py`)

Test files referencing CRDT types (must be cleaned in Task 9):
- `agent/tests/test_codehub_merge.py` — uses `Timestamp.now("test")` in 2 places
- `agent/tests/test_workhub_completeness.py` — uses `Timestamp.now("orch")` in 2 places

### Conventions to follow (carried across cutovers)

- No `Co-Authored-By: Claude` trailer on commits — the user has been explicit
- No emojis in code output or rendered prompts
- Python interpreter: `/home/haibotong/miniconda3/envs/dt/bin/python`
- Default git branch is `master` (not `main`)
- Worktree path convention: `repo_root/worktrees/<agent_id>` (NOT `workspaces/`)
- `GitOps._run` is `_run(*args, check=, cwd=)` returning a `CompletedProcess`
- TDD: write failing test → confirm failure → minimal impl → confirm pass → commit
- Bite-sized commits — one logical change per commit
- Don't push until Task 10
- Both baselines must stay green after every task: `python agent/tests/run_regressions.py` (currently 7 OK) and `python -m unittest discover agent/tests -p 'test_*.py'` (currently 361 OK after Cutover 8)

---

## File Structure

**New files:**
- `agent/env_generator/llm_generator/multi_agent/runtime/json_store.py` — replacement for `crdt_store.py` + `crdt_types.py` combined surface (~120 LoC target)
- `agent/tests/test_json_store.py` — TDD tests for `JsonStore`

**Modified files:**
- `agent/env_generator/llm_generator/multi_agent/runtime/apihub.py` — drop `from .crdt_store import CRDTStore` + `from .crdt_types import LWWMap, Timestamp`; replace store constructors and drop `Timestamp.now()` calls
- `agent/env_generator/llm_generator/multi_agent/runtime/eventhub.py` — same pattern
- `agent/env_generator/llm_generator/multi_agent/runtime/hubs/codehub/stores.py` — swap `CRDTStore(crdt_dir / "x.json", LWWMap)` → `JsonStore(hub_dir / "x.json")` and rename `crdt_dir` param to `hub_dir`
- `agent/env_generator/llm_generator/multi_agent/runtime/hubs/codehub/service.py` — drop `Timestamp` import, drop `crdt_dir` constructor param (rename to `hub_dir`)
- `agent/env_generator/llm_generator/multi_agent/runtime/hubs/workhub/stores.py` — same as codehub stores
- `agent/env_generator/llm_generator/multi_agent/runtime/hubs/workhub/service.py` — drop Timestamp + rename crdt_dir
- `agent/env_generator/llm_generator/multi_agent/runtime/hub_registry.py` — `shared/crdt/` → `shared/hubs/` with one-shot migration on init; update docstrings
- `agent/env_generator/llm_generator/multi_agent/runtime/__init__.py` — drop CRDT re-exports + observer stub re-exports
- `agent/tests/test_codehub_merge.py` — replace `Timestamp.now("test")` with `time.time()` (the third arg is ignored by `JsonStore.update`'s legacy mutator proxy anyway)
- `agent/tests/test_workhub_completeness.py` — same

**Deleted files (Task 9):**
- `agent/env_generator/llm_generator/multi_agent/runtime/crdt_store.py`
- `agent/env_generator/llm_generator/multi_agent/runtime/crdt_types.py`
- `agent/env_generator/llm_generator/multi_agent/runtime/crdt_validation.py`
- `agent/env_generator/llm_generator/multi_agent/runtime/crdt_observer_stub.py`

---

## Task 1: Worktree setup + baseline capture

**Files:**
- Create: `docs/superpowers/cutover-9-baseline.md`

- [ ] **Step 1: Verify worktree is on the right branch and clean**

```bash
cd /data/common/haibotong/env-gen/.worktrees/haibotong-cutover-9-crdt-purge
git status
git log --oneline -3
```

Expected: clean working tree, HEAD on `haibotong-cutover-9-crdt-purge` branched from `haibotong-0521-pipeline-web-tools` at SHA `9f3f71c8` (Cutover 8 merged).

(If the worktree does not exist yet, create it from the repo root with:
`git worktree add -b haibotong-cutover-9-crdt-purge .worktrees/haibotong-cutover-9-crdt-purge haibotong-0521-pipeline-web-tools`)

- [ ] **Step 2: Run baseline regression suite**

```bash
cd /data/common/haibotong/env-gen/.worktrees/haibotong-cutover-9-crdt-purge
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
```

Expected: `7 tests, OK`.

- [ ] **Step 3: Run baseline discover suite**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: `Ran 361 tests in <time>s` and `OK`. If anything fails, STOP and report — do not proceed.

- [ ] **Step 4: Inventory live CRDT call sites for later verification**

```bash
grep -rnE "from .crdt_(store|types|validation|observer_stub) import|import .crdt_(store|types|validation|observer_stub)" agent/env_generator/llm_generator/multi_agent/runtime/ --include="*.py" | sort > /tmp/cutover9_imports_before.txt
wc -l /tmp/cutover9_imports_before.txt
```

Expected: ~12–14 import lines. Save this as part of the baseline note.

- [ ] **Step 5: Write the baseline note**

Create `docs/superpowers/cutover-9-baseline.md` with this content:

```markdown
# Cutover 9 Baseline (CRDT Scaffolding Purge)

Captured before any code changes on branch `haibotong-cutover-9-crdt-purge`.

## Test counts
- `agent/tests/run_regressions.py`: 7 OK
- `python -m unittest discover agent/tests -p 'test_*.py'`: 361 OK

## CRDT imports inventory (must be empty by end of Task 9)
<paste contents of /tmp/cutover9_imports_before.txt here>

## Live CRDT-importing files (8)
- runtime/apihub.py
- runtime/eventhub.py
- runtime/hubs/codehub/stores.py
- runtime/hubs/codehub/service.py
- runtime/hubs/workhub/stores.py
- runtime/hubs/workhub/service.py
- runtime/hub_registry.py
- runtime/__init__.py

## Dead modules to delete (4 / 1137 LoC)
- runtime/crdt_store.py        (163 LoC)
- runtime/crdt_types.py        (304 LoC)
- runtime/crdt_validation.py   (603 LoC)
- runtime/crdt_observer_stub.py (67 LoC)

## Tests touching CRDT types (2)
- agent/tests/test_codehub_merge.py        — Timestamp.now("test") x2
- agent/tests/test_workhub_completeness.py — Timestamp.now("orch") x2
```

- [ ] **Step 6: Commit the baseline note**

```bash
git add docs/superpowers/cutover-9-baseline.md
git commit -m "Cutover 9: record pre-flight baseline (regressions 7 OK, discover 361 OK)"
```

Expected: clean commit, no Claude trailer (verify with `git log -1 --format=%B | grep -c Claude` → 0).

---

## Task 2: Build `JsonStore` module (core API, no legacy compat yet)

**Files:**
- Create: `agent/env_generator/llm_generator/multi_agent/runtime/json_store.py`
- Test: `agent/tests/test_json_store.py`

- [ ] **Step 1: Write failing test for set + value + get**

Create `agent/tests/test_json_store.py`:

```python
"""Tests for the JsonStore replacement for CRDTStore + LWWMap."""

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

# Add the agent package to path (matches the pattern used by other tests).
THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.json_store import JsonStore  # noqa: E402


class JsonStoreBasicTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp(prefix="jsonstore_")
        self.path = Path(self.tmpdir) / "store.json"

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_empty_store_returns_empty_value(self) -> None:
        store = JsonStore(self.path)
        self.assertEqual(store.value(), {})
        self.assertIsNone(store.get("missing"))

    def test_set_then_value_returns_inserted_pair(self) -> None:
        store = JsonStore(self.path)
        store.set("alpha", {"x": 1}, agent="orch")
        self.assertEqual(store.value(), {"alpha": {"x": 1}})
        self.assertEqual(store.get("alpha"), {"x": 1})

    def test_set_persists_across_instances(self) -> None:
        store1 = JsonStore(self.path)
        store1.set("alpha", {"x": 1}, agent="orch")
        store2 = JsonStore(self.path)
        self.assertEqual(store2.value(), {"alpha": {"x": 1}})

    def test_delete_removes_key(self) -> None:
        store = JsonStore(self.path)
        store.set("alpha", 1)
        store.set("beta", 2)
        store.delete("alpha")
        self.assertEqual(store.value(), {"beta": 2})
        self.assertIsNone(store.get("alpha"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify the test fails (module does not exist yet)**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_json_store -v 2>&1 | tail -10
```

Expected: ImportError on `from multi_agent.runtime.json_store import JsonStore`.

- [ ] **Step 3: Create minimal `JsonStore` with set/value/get/delete**

Create `agent/env_generator/llm_generator/multi_agent/runtime/json_store.py`:

```python
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
from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)

_META_KEY = "_meta"


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
            return {}
        try:
            with open(self.file_path, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"JsonStore: failed to load {self.file_path}: {e}")
            return {}

    def _save_raw(self, data: Dict[str, Any]) -> None:
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.file_path.with_suffix(self.file_path.suffix + f".{os.getpid()}.tmp")
        with open(tmp_path, "w") as f:
            json.dump(data, f, indent=2, default=str)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, self.file_path)

    def _bump_meta(self, raw: Dict[str, Any], agent: str) -> None:
        meta = raw.get(_META_KEY) or {"version": 0}
        meta["version"] = int(meta.get("version", 0)) + 1
        meta["last_modified_by"] = agent or meta.get("last_modified_by", "")
        meta["last_modified_at"] = time.time()
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

    def get_version(self) -> int:
        with self._lock, self._file_lock():
            raw = self._load_raw()
        return int((raw.get(_META_KEY) or {}).get("version", 0))


__all__ = ["JsonStore"]
```

- [ ] **Step 4: Verify the 4 tests pass**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_json_store -v 2>&1 | tail -10
```

Expected: `Ran 4 tests in <time>s` + `OK`.

- [ ] **Step 5: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/runtime/json_store.py agent/tests/test_json_store.py
git commit -m "Add JsonStore: atomic JSON KV with file lock + monotonic version"
```

---

## Task 3: Add `update()` back-compat shim + `get_version` + legacy LWWMap reader

`apihub`/`eventhub`/etc. all call `store.update(lambda m: m.set(k, v, ts))` and `store.update(lambda m: m, change_info={...})`. To avoid rewriting every call site in this task, `JsonStore.update` takes a mutator that receives a `_MapView` proxy whose `.set(k, v, ts=None)` and `.delete(k, ts=None)` ignore `ts`. Plus we need the legacy LWWMap-format on-disk reader so existing `shared/crdt/` JSONs load cleanly.

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/runtime/json_store.py`
- Modify: `agent/tests/test_json_store.py`

- [ ] **Step 1: Append failing tests for update() + legacy read + version**

Append to `agent/tests/test_json_store.py`:

```python
class JsonStoreUpdateCompatTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp(prefix="jsonstore_")
        self.path = Path(self.tmpdir) / "store.json"

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_update_with_set_third_arg_ignored(self) -> None:
        store = JsonStore(self.path)
        store.update(lambda m: m.set("alpha", {"x": 1}, "ignored_ts_arg"))
        self.assertEqual(store.value(), {"alpha": {"x": 1}})

    def test_update_with_delete(self) -> None:
        store = JsonStore(self.path)
        store.set("alpha", 1)
        store.update(lambda m: m.delete("alpha", "ignored_ts_arg"))
        self.assertEqual(store.value(), {})

    def test_update_identity_mutator_touches_meta(self) -> None:
        store = JsonStore(self.path)
        v0 = store.get_version()
        store.update(lambda m: m, change_info={"system": "ensure"})
        self.assertGreater(store.get_version(), v0)

    def test_update_returns_post_write_snapshot(self) -> None:
        store = JsonStore(self.path)
        snap = store.update(lambda m: m.set("alpha", 7))
        self.assertEqual(snap, {"alpha": 7})

    def test_version_increments_per_write(self) -> None:
        store = JsonStore(self.path)
        self.assertEqual(store.get_version(), 0)
        store.set("a", 1)
        self.assertEqual(store.get_version(), 1)
        store.set("b", 2)
        self.assertEqual(store.get_version(), 2)
        store.delete("a")
        self.assertEqual(store.get_version(), 3)


class JsonStoreLegacyLWWMapReadTests(unittest.TestCase):
    """Existing shared/crdt/ files were written by CRDTStore(LWWMap); the new
    JsonStore must read them transparently and persist in the new flat shape
    on the first write."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp(prefix="jsonstore_legacy_")
        self.path = Path(self.tmpdir) / "store.json"

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_legacy(self) -> None:
        legacy = {
            "type": "LWWMap",
            "entries": {
                "alpha": {
                    "type": "LWWRegister",
                    "value": {"x": 1},
                    "timestamp": {"wall_time": 1.0, "logical": 0, "node_id": "old"},
                },
                "beta": {
                    "type": "LWWRegister",
                    "value": 42,
                    "timestamp": {"wall_time": 2.0, "logical": 0, "node_id": "old"},
                },
            },
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(legacy))

    def test_legacy_file_reads_as_flat_dict(self) -> None:
        self._write_legacy()
        store = JsonStore(self.path)
        self.assertEqual(store.value(), {"alpha": {"x": 1}, "beta": 42})
        self.assertEqual(store.get("alpha"), {"x": 1})

    def test_legacy_file_drops_lww_register_timestamps_on_first_write(self) -> None:
        self._write_legacy()
        store = JsonStore(self.path)
        store.set("gamma", 99, agent="orch")
        on_disk = json.loads(self.path.read_text())
        self.assertNotIn("type", on_disk)
        self.assertNotIn("entries", on_disk)
        self.assertEqual(on_disk.get("alpha"), {"x": 1})
        self.assertEqual(on_disk.get("beta"), 42)
        self.assertEqual(on_disk.get("gamma"), 99)
        self.assertIn("_meta", on_disk)
        self.assertEqual(on_disk["_meta"]["last_modified_by"], "orch")

    def test_legacy_lwwmap_entry_with_null_value_is_filtered(self) -> None:
        # CRDTStore used set(key, None, ts) for deletes; legacy reader must
        # drop entries whose value is None.
        legacy = {
            "type": "LWWMap",
            "entries": {
                "alpha": {"type": "LWWRegister", "value": None,
                          "timestamp": {"wall_time": 1.0, "logical": 0, "node_id": "x"}},
                "beta": {"type": "LWWRegister", "value": "live",
                         "timestamp": {"wall_time": 2.0, "logical": 0, "node_id": "x"}},
            },
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(legacy))
        store = JsonStore(self.path)
        self.assertEqual(store.value(), {"beta": "live"})
```

- [ ] **Step 2: Verify the new tests fail**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_json_store -v 2>&1 | tail -20
```

Expected: failures on `update`/legacy/version tests; first 4 still pass.

- [ ] **Step 3: Extend `JsonStore` with `_MapView`, `update`, legacy reader**

Replace `_load_raw` and add `_MapView` + `update` in `agent/env_generator/llm_generator/multi_agent/runtime/json_store.py`.

Insert this class above `JsonStore` (just under the imports, after `_META_KEY = "_meta"`):

```python
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
```

Replace `_load_raw` to unwrap legacy LWWMap files on read:

```python
    def _load_raw(self) -> Dict[str, Any]:
        if not self.file_path.exists():
            return {}
        try:
            with open(self.file_path, "r") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"JsonStore: failed to load {self.file_path}: {e}")
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
```

Add `update` to the `JsonStore` class (place after `delete`, before `get_version`):

```python
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
            if change_info:
                agent = str(change_info.get("agent") or change_info.get("system") or "")
            new_raw = {_META_KEY: raw.get(_META_KEY, {"version": 0}), **new_data}
            self._bump_meta(new_raw, agent)
            self._save_raw(new_raw)
        return new_data
```

Update `__all__`:

```python
__all__ = ["JsonStore"]
```

- [ ] **Step 4: Verify all 12 `JsonStore` tests pass**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_json_store -v 2>&1 | tail -20
```

Expected: `Ran 12 tests in <time>s` + `OK`.

- [ ] **Step 5: Run both baselines to confirm no other tests regressed**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 7 OK / 373 OK (was 361 + 12 new = 373).

- [ ] **Step 6: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/runtime/json_store.py agent/tests/test_json_store.py
git commit -m "JsonStore: add update() compat shim, legacy LWWMap reader, version counter"
```

---

## Task 4: Migrate `APIHub` to `JsonStore`

Drop `from .crdt_store import CRDTStore` + `from .crdt_types import LWWMap, Timestamp`. Replace each `CRDTStore(crdt_dir / "x.json", LWWMap)` with `JsonStore(hub_dir / "x.json")`. Drop every `ts = Timestamp.now(agent)` line; pass `agent` (or a literal `""`) as the third arg in `m.set(...)` calls so the existing `.update(lambda m: m.set(k, v, ts))` pattern continues to compile against the `_MapView` proxy. Rename the constructor parameter from `crdt_dir` to `hub_dir`.

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/runtime/apihub.py`

- [ ] **Step 1: Write failing locator test**

Create `agent/tests/test_cutover9_apihub_migration.py`:

```python
"""Source-level checks that apihub.py no longer imports CRDT scaffolding."""

import re
import sys
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent

APIHUB_PATH = (
    AGENT_DIR / "env_generator" / "llm_generator" / "multi_agent" / "runtime" / "apihub.py"
)


class APIHubMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.src = APIHUB_PATH.read_text()

    def test_no_crdt_imports(self) -> None:
        self.assertNotRegex(self.src, r"from \.crdt_store import")
        self.assertNotRegex(self.src, r"from \.crdt_types import")
        self.assertNotIn("CRDTStore", self.src)
        self.assertNotIn("LWWMap", self.src)
        self.assertNotIn("Timestamp", self.src)

    def test_uses_jsonstore(self) -> None:
        self.assertIn("from .json_store import JsonStore", self.src)
        # At least 13 JsonStore constructions (one per former CRDTStore).
        self.assertGreaterEqual(self.src.count("JsonStore("), 13)

    def test_constructor_uses_hub_dir(self) -> None:
        self.assertRegex(self.src, r"def __init__\(self, hub_dir")
        self.assertNotRegex(self.src, r"def __init__\(self, crdt_dir")

    def test_self_hub_dir_attribute(self) -> None:
        self.assertIn("self.hub_dir", self.src)
        self.assertNotIn("self.crdt_dir", self.src)

    def test_no_timestamp_now_calls(self) -> None:
        self.assertNotIn("Timestamp.now(", self.src)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify the test fails**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_cutover9_apihub_migration -v 2>&1 | tail -15
```

Expected: failures on every assertion.

- [ ] **Step 3: Edit `apihub.py`**

In `agent/env_generator/llm_generator/multi_agent/runtime/apihub.py`:

(a) Replace the import block (lines 8–9) — remove `from .crdt_store import CRDTStore` and `from .crdt_types import LWWMap, Timestamp`, add `from .json_store import JsonStore`.

(b) Rename the constructor:

OLD:
```python
    def __init__(self, crdt_dir: Path, eventhub: "EventHub | None" = None,
                 workhub: "WorkHub | None" = None):
        self.crdt_dir = Path(crdt_dir)
```

NEW:
```python
    def __init__(self, hub_dir: Path, eventhub: "EventHub | None" = None,
                 workhub: "WorkHub | None" = None):
        self.hub_dir = Path(hub_dir)
```

(c) Rewrite the 13 store constructors. Pattern — for each of the 13 lines under `self.crdt_dir = Path(crdt_dir)`:

OLD: `self._projects = CRDTStore(self.crdt_dir / "apihub_projects.json", LWWMap)`
NEW: `self._projects = JsonStore(self.hub_dir / "apihub_projects.json")`

Apply to: `_projects`, `_endpoints`, `_schemas`, `_examples`, `_mocks`, `_contract_tests`, `_providers`, `_consumers`, `_api_reviews`, `_breaking_changes`, `_tables`, `_table_consumers`, `_table_breaking_changes`.

(d) Remove every `ts = Timestamp.now(...)` line. Then for every `m.set(key, value, ts)` call, replace `ts` with the original agent string used to build the timestamp. For example:

OLD:
```python
ts = Timestamp.now(agent or "apihub")
self._endpoints.update(lambda m: m.set(endpoint_id, endpoint, ts))
```

NEW:
```python
self._endpoints.update(
    lambda m: m.set(endpoint_id, endpoint, agent or "apihub"),
    change_info={"agent": agent or "apihub"},
)
```

Use this exact pattern (lambda passes the agent string as the 3rd arg, which `_MapView.set` ignores; `change_info` stamps `_meta.last_modified_by` via `JsonStore.update`).

Apply to ALL `Timestamp.now(...)` usages in the file (use `grep -n "Timestamp.now" agent/env_generator/llm_generator/multi_agent/runtime/apihub.py` to enumerate; the user's earlier probe identified ~12 sites).

If a site uses `ts` for any purpose other than `.set(..., ts)` — STOP and inspect; that would be a behavior change requiring real attention. (No such site exists at probe time, but verify.)

- [ ] **Step 4: Verify the migration test passes**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_cutover9_apihub_migration -v 2>&1 | tail -10
```

Expected: `Ran 5 tests in <time>s` + `OK`.

- [ ] **Step 5: Run both baselines (catch APIHub behavior regressions)**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 7 OK / 378 OK (was 373 + 5 new). If anything fails, the migration broke a real call — diagnose before committing.

- [ ] **Step 6: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/runtime/apihub.py agent/tests/test_cutover9_apihub_migration.py
git commit -m "APIHub: migrate CRDTStore(LWWMap) -> JsonStore, drop Timestamp.now(), rename crdt_dir -> hub_dir"
```

---

## Task 5: Migrate `EventHub` to `JsonStore`

Same pattern as Task 4. EventHub has 4 stores (`_events`, `_threads`, `_subscriptions`, `_inboxes`) and ~6 `Timestamp.now()` sites.

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/runtime/eventhub.py`

- [ ] **Step 1: Write failing locator test**

Create `agent/tests/test_cutover9_eventhub_migration.py`:

```python
"""Source-level checks that eventhub.py no longer imports CRDT scaffolding."""

import sys
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent

EVENTHUB_PATH = (
    AGENT_DIR / "env_generator" / "llm_generator" / "multi_agent" / "runtime" / "eventhub.py"
)


class EventHubMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.src = EVENTHUB_PATH.read_text()

    def test_no_crdt_imports(self) -> None:
        self.assertNotRegex(self.src, r"from \.crdt_store import")
        self.assertNotRegex(self.src, r"from \.crdt_types import")
        self.assertNotIn("CRDTStore", self.src)
        self.assertNotIn("LWWMap", self.src)
        self.assertNotIn("Timestamp", self.src)

    def test_uses_jsonstore(self) -> None:
        self.assertIn("from .json_store import JsonStore", self.src)
        self.assertGreaterEqual(self.src.count("JsonStore("), 4)

    def test_constructor_uses_hub_dir(self) -> None:
        self.assertRegex(self.src, r"def __init__\(self, hub_dir")
        self.assertNotRegex(self.src, r"def __init__\(self, crdt_dir")

    def test_no_timestamp_now_calls(self) -> None:
        self.assertNotIn("Timestamp.now(", self.src)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify the test fails**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_cutover9_eventhub_migration -v 2>&1 | tail -10
```

Expected: failures.

- [ ] **Step 3: Edit `eventhub.py`**

Apply the same surgery as Task 4: drop CRDT imports, add `from .json_store import JsonStore`, rename `crdt_dir` → `hub_dir`, replace 4 `CRDTStore(self.crdt_dir / "X.json", LWWMap)` with `JsonStore(self.hub_dir / "X.json")`, eliminate every `ts = Timestamp.now(agent)` line, inline the agent string into the `m.set(...)` lambda's 3rd arg, add `change_info={"agent": agent}` to each `.update(...)` call.

Specifically replace these 4 store constructors:
```python
self._events = JsonStore(self.hub_dir / "eventhub_events.json")
self._threads = JsonStore(self.hub_dir / "eventhub_threads.json")
self._subscriptions = JsonStore(self.hub_dir / "eventhub_subscriptions.json")
self._inboxes = JsonStore(self.hub_dir / "eventhub_inboxes.json")
```

Drop the 6 `Timestamp.now(...)` sites (lines around 67, 149, 184, 226, 253, 275 per earlier probe — re-grep before editing). Pattern: every `ts = Timestamp.now(X)` followed by `.update(lambda m: m.set(k, v, ts))` becomes `.update(lambda m: m.set(k, v, X), change_info={"agent": X})`.

- [ ] **Step 4: Verify the migration test passes**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_cutover9_eventhub_migration -v 2>&1 | tail -10
```

Expected: `Ran 4 tests in <time>s` + `OK`.

- [ ] **Step 5: Run both baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 7 OK / 382 OK (was 378 + 4 new).

- [ ] **Step 6: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/runtime/eventhub.py agent/tests/test_cutover9_eventhub_migration.py
git commit -m "EventHub: migrate CRDTStore(LWWMap) -> JsonStore, drop Timestamp.now()"
```

---

## Task 6: Migrate `CodeHub` (`stores.py` + `service.py`) to `JsonStore`

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/runtime/hubs/codehub/stores.py`
- Modify: `agent/env_generator/llm_generator/multi_agent/runtime/hubs/codehub/service.py`

- [ ] **Step 1: Write failing locator test**

Create `agent/tests/test_cutover9_codehub_migration.py`:

```python
import sys
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent

STORES_PATH = (
    AGENT_DIR
    / "env_generator" / "llm_generator" / "multi_agent" / "runtime"
    / "hubs" / "codehub" / "stores.py"
)
SERVICE_PATH = (
    AGENT_DIR
    / "env_generator" / "llm_generator" / "multi_agent" / "runtime"
    / "hubs" / "codehub" / "service.py"
)


class CodeHubMigrationTests(unittest.TestCase):
    def test_stores_uses_jsonstore(self) -> None:
        src = STORES_PATH.read_text()
        self.assertIn("from ...json_store import JsonStore", src)
        self.assertNotIn("CRDTStore", src)
        self.assertNotIn("LWWMap", src)
        self.assertGreaterEqual(src.count("JsonStore("), 8)

    def test_stores_uses_hub_dir_parameter(self) -> None:
        src = STORES_PATH.read_text()
        self.assertRegex(src, r"def create\(cls, hub_dir")
        self.assertNotIn("crdt_dir", src)

    def test_service_drops_timestamp_import(self) -> None:
        src = SERVICE_PATH.read_text()
        self.assertNotRegex(src, r"from \.\.\.crdt_types import")
        self.assertNotIn("Timestamp", src)

    def test_service_uses_hub_dir_parameter(self) -> None:
        src = SERVICE_PATH.read_text()
        self.assertRegex(src, r"def __init__\(self, repo_root: Path, hub_dir")
        self.assertNotIn("crdt_dir", src)
        self.assertNotIn("self.crdt_dir", src)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify the test fails**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_cutover9_codehub_migration -v 2>&1 | tail -10
```

- [ ] **Step 3: Edit `hubs/codehub/stores.py`**

Replace the file with:

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ...json_store import JsonStore


@dataclass
class CodeHubStores:
    repos: JsonStore
    branches: JsonStore
    commits: JsonStore
    pull_requests: JsonStore
    review_threads: JsonStore
    code_reviews: JsonStore
    checks: JsonStore
    releases: JsonStore

    @classmethod
    def create(cls, hub_dir: Path) -> "CodeHubStores":
        hub_dir = Path(hub_dir)
        return cls(
            repos=JsonStore(hub_dir / "codehub_repos.json"),
            branches=JsonStore(hub_dir / "codehub_branches.json"),
            commits=JsonStore(hub_dir / "codehub_commits.json"),
            pull_requests=JsonStore(hub_dir / "codehub_pull_requests.json"),
            review_threads=JsonStore(hub_dir / "codehub_review_threads.json"),
            code_reviews=JsonStore(hub_dir / "codehub_code_reviews.json"),
            checks=JsonStore(hub_dir / "codehub_checks.json"),
            releases=JsonStore(hub_dir / "codehub_releases.json"),
        )

    def ensure_documents(self) -> None:
        for store in [
            self.repos, self.branches, self.commits, self.pull_requests,
            self.review_threads, self.code_reviews, self.checks, self.releases,
        ]:
            store.update(lambda m: m, change_info={"system": "ensure_codehub_document"})

    def versions(self) -> dict:
        return {
            "codehub_repos": self.repos.get_version(),
            "codehub_branches": self.branches.get_version(),
            "codehub_commits": self.commits.get_version(),
            "codehub_pull_requests": self.pull_requests.get_version(),
            "codehub_review_threads": self.review_threads.get_version(),
            "codehub_code_reviews": self.code_reviews.get_version(),
            "codehub_checks": self.checks.get_version(),
            "codehub_releases": self.releases.get_version(),
        }

    def snapshot(self) -> dict:
        return {
            "repos": self.repos.value(),
            "branches": self.branches.value(),
            "commits": self.commits.value(),
            "pull_requests": self.pull_requests.value(),
            "review_threads": self.review_threads.value(),
            "code_reviews": self.code_reviews.value(),
            "checks": self.checks.value(),
            "releases": self.releases.value(),
        }
```

- [ ] **Step 4: Edit `hubs/codehub/service.py`**

(a) Remove the `from ...crdt_types import Timestamp` import (was line 8).

(b) Rename the constructor:

OLD:
```python
def __init__(self, repo_root: Path, crdt_dir: Path, eventhub: EventHub | None = None):
    self.repo_root = Path(repo_root)
    self.crdt_dir = Path(crdt_dir)
    ...
    self.stores = CodeHubStores.create(self.crdt_dir)
```

NEW:
```python
def __init__(self, repo_root: Path, hub_dir: Path, eventhub: EventHub | None = None):
    self.repo_root = Path(repo_root)
    self.hub_dir = Path(hub_dir)
    ...
    self.stores = CodeHubStores.create(self.hub_dir)
```

(c) `grep -n "Timestamp" agent/env_generator/llm_generator/multi_agent/runtime/hubs/codehub/service.py` to find any remaining `Timestamp.now(...)` sites. For each, apply the same pattern as Task 4: drop the `ts =` line, inline the agent string into the `.set(..., agent)` lambda's 3rd arg, add `change_info={"agent": agent}` to `.update(...)`.

(d) Update the docstring at the `merge_pull_request` site (line ~690 per the earlier probe) — the line `Returns a dict with ``sha`` and the CRDT commit metadata.` — change "CRDT commit metadata" to "commit metadata".

(e) Update the comment at line ~258 `# No real git repo — fall back to CRDT metadata` to `# No real git repo — fall back to stored metadata`.

- [ ] **Step 5: Verify the migration test passes**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_cutover9_codehub_migration -v 2>&1 | tail -10
```

Expected: `Ran 4 tests in <time>s` + `OK`.

- [ ] **Step 6: Run both baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 7 OK / 386 OK (was 382 + 4 new). If `test_codehub_*` tests fail, inspect — they likely pass `crdt_dir=` as a keyword arg and need to be updated to `hub_dir=` in Task 9 (don't fix here; note and continue if the failures are clearly the keyword rename).

If failures look unrelated to the rename, STOP and diagnose.

- [ ] **Step 7: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/runtime/hubs/codehub/stores.py agent/env_generator/llm_generator/multi_agent/runtime/hubs/codehub/service.py agent/tests/test_cutover9_codehub_migration.py
git commit -m "CodeHub: migrate to JsonStore, drop Timestamp, rename crdt_dir -> hub_dir"
```

---

## Task 7: Migrate `WorkHub` (`stores.py` + `service.py`) to `JsonStore`

Mirrors Task 6 for WorkHub. The exact list of `WorkHubStores` fields must be read from `runtime/hubs/workhub/stores.py` (do NOT hardcode the count — re-grep). The Timestamp usage in `runtime/hubs/workhub/service.py` must be enumerated with `grep -n Timestamp <path>` before editing.

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/runtime/hubs/workhub/stores.py`
- Modify: `agent/env_generator/llm_generator/multi_agent/runtime/hubs/workhub/service.py`

- [ ] **Step 1: Inspect current WorkHub stores + Timestamp usage**

```bash
grep -nE "CRDTStore\(|Timestamp" agent/env_generator/llm_generator/multi_agent/runtime/hubs/workhub/stores.py agent/env_generator/llm_generator/multi_agent/runtime/hubs/workhub/service.py | head -40
```

Record the store field names and the Timestamp.now call sites. You will mirror them in Step 3.

- [ ] **Step 2: Write failing locator test**

Create `agent/tests/test_cutover9_workhub_migration.py`:

```python
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent

STORES_PATH = (
    AGENT_DIR
    / "env_generator" / "llm_generator" / "multi_agent" / "runtime"
    / "hubs" / "workhub" / "stores.py"
)
SERVICE_PATH = (
    AGENT_DIR
    / "env_generator" / "llm_generator" / "multi_agent" / "runtime"
    / "hubs" / "workhub" / "service.py"
)


class WorkHubMigrationTests(unittest.TestCase):
    def test_stores_uses_jsonstore(self) -> None:
        src = STORES_PATH.read_text()
        self.assertIn("from ...json_store import JsonStore", src)
        self.assertNotIn("CRDTStore", src)
        self.assertNotIn("LWWMap", src)

    def test_stores_uses_hub_dir_parameter(self) -> None:
        src = STORES_PATH.read_text()
        self.assertRegex(src, r"def create\(cls, hub_dir")
        self.assertNotIn("crdt_dir", src)

    def test_service_drops_timestamp_import(self) -> None:
        src = SERVICE_PATH.read_text()
        self.assertNotRegex(src, r"from \.\.\.crdt_types import")
        self.assertNotIn("Timestamp", src)

    def test_service_uses_hub_dir_parameter(self) -> None:
        src = SERVICE_PATH.read_text()
        # WorkHub signature is `__init__(self, hub_dir, eventhub=...)` after this cutover.
        self.assertRegex(src, r"def __init__\(self, hub_dir")
        self.assertNotIn("crdt_dir", src)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Edit `hubs/workhub/stores.py`**

Apply the same pattern Task 6 used on `codehub/stores.py`:

- Replace `from ...crdt_store import CRDTStore` + `from ...crdt_types import LWWMap` with `from ...json_store import JsonStore`
- Change every dataclass field from `CRDTStore` to `JsonStore`
- Rename the `create(cls, crdt_dir: Path)` classmethod parameter to `create(cls, hub_dir: Path)`
- Replace every `CRDTStore(crdt_dir / "X.json", LWWMap)` with `JsonStore(hub_dir / "X.json")` (same key suffix)
- `ensure_documents` and `versions` and `snapshot` keep their structure; only their internal references change (`crdt_dir` → `hub_dir`)

- [ ] **Step 4: Edit `hubs/workhub/service.py`**

- Drop the `from ...crdt_types import Timestamp` import
- Rename `crdt_dir` → `hub_dir` in the constructor signature and body
- For every `ts = Timestamp.now(agent)` followed by `.update(lambda m: m.set(k, v, ts))`: drop the `ts =` line, inline `agent` as the third arg, add `change_info={"agent": agent}` to `.update(...)`

- [ ] **Step 5: Verify migration test passes**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_cutover9_workhub_migration -v 2>&1 | tail -10
```

Expected: 4 tests OK.

- [ ] **Step 6: Run both baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 7 OK / 390 OK (was 386 + 4 new). `test_workhub_completeness.py` may fail because it calls `Timestamp.now("orch")` — note that and continue (Task 9 will fix it).

- [ ] **Step 7: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/runtime/hubs/workhub/stores.py agent/env_generator/llm_generator/multi_agent/runtime/hubs/workhub/service.py agent/tests/test_cutover9_workhub_migration.py
git commit -m "WorkHub: migrate to JsonStore, drop Timestamp, rename crdt_dir -> hub_dir"
```

---

## Task 8: Rename `shared/crdt/` → `shared/hubs/` in `HubRegistry` with one-shot migration

**Files:**
- Modify: `agent/env_generator/llm_generator/multi_agent/runtime/hub_registry.py`

- [ ] **Step 1: Write failing test for directory migration**

Create `agent/tests/test_cutover9_dir_migration.py`:

```python
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402


class DirMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="hubdir_"))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_new_install_uses_shared_hubs(self) -> None:
        reg = HubRegistry(self.tmp)
        self.assertEqual(reg._store_dir, self.tmp / "shared" / "hubs")
        self.assertTrue((self.tmp / "shared" / "hubs").exists())
        self.assertFalse((self.tmp / "shared" / "crdt").exists())

    def test_existing_shared_crdt_is_auto_migrated(self) -> None:
        legacy = self.tmp / "shared" / "crdt"
        legacy.mkdir(parents=True)
        (legacy / "apihub_endpoints.json").write_text(json.dumps({"existing": "value"}))
        (legacy / "eventhub_events.json").write_text(json.dumps({"e": 1}))

        reg = HubRegistry(self.tmp)

        new_dir = self.tmp / "shared" / "hubs"
        self.assertTrue(new_dir.exists())
        self.assertTrue((new_dir / "apihub_endpoints.json").exists())
        self.assertTrue((new_dir / "eventhub_events.json").exists())
        self.assertEqual(reg._store_dir, new_dir)
        moved = json.loads((new_dir / "apihub_endpoints.json").read_text())
        self.assertEqual(moved, {"existing": "value"})

    def test_both_dirs_present_prefers_shared_hubs(self) -> None:
        (self.tmp / "shared" / "hubs").mkdir(parents=True)
        (self.tmp / "shared" / "hubs" / "marker_new.json").write_text("{}")
        (self.tmp / "shared" / "crdt").mkdir(parents=True)
        (self.tmp / "shared" / "crdt" / "marker_old.json").write_text("{}")

        reg = HubRegistry(self.tmp)

        self.assertEqual(reg._store_dir, self.tmp / "shared" / "hubs")
        # Pre-existing new file is preserved; old file is NOT copied over.
        self.assertTrue((self.tmp / "shared" / "hubs" / "marker_new.json").exists())
        self.assertFalse((self.tmp / "shared" / "hubs" / "marker_old.json").exists())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify the test fails**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_cutover9_dir_migration -v 2>&1 | tail -10
```

Expected: failures (path is still `shared/crdt`).

- [ ] **Step 3: Edit `runtime/hub_registry.py`**

Replace lines 30–48 with:

```python
    Disk layout: per-base-dir JSON files live under ``shared/hubs/`` (renamed
    from ``shared/crdt/`` in Cutover 9). Existing ``shared/crdt/`` directories
    are auto-migrated on first init.
    """

    def __init__(self, base_dir: Path, message_bus: Any = None):
        from .apihub import APIHub
        from .codehub import CodeHub
        from .eventhub import EventHub
        from .workhub import WorkHub

        self.base_dir = Path(base_dir)
        self._store_dir = self._resolve_hub_dir(self.base_dir)
        self._store_dir.mkdir(parents=True, exist_ok=True)

        self.eventhub = EventHub(self._store_dir)
        self.codehub = CodeHub(self.base_dir, self._store_dir, eventhub=self.eventhub)
        self.workhub = WorkHub(self._store_dir, eventhub=self.eventhub)
        self.apihub = APIHub(self._store_dir, eventhub=self.eventhub)
        self.apihub.attach_workhub(self.workhub)
        self.codehub.attach_workhub(self.workhub)
        self.codehub.attach_apihub(self.apihub)

        self.bridge: Optional[Any] = None
        if message_bus is not None:
            from .hubs.eventhub.bridge import MessageBusBridge
            self.bridge = MessageBusBridge(message_bus, self.eventhub)
            self.eventhub.attach_bridge(self.bridge)

    @staticmethod
    def _resolve_hub_dir(base_dir: Path) -> Path:
        """Return shared/hubs/, migrating from shared/crdt/ if needed."""
        new_dir = base_dir / "shared" / "hubs"
        old_dir = base_dir / "shared" / "crdt"
        if old_dir.exists() and not new_dir.exists():
            new_dir.parent.mkdir(parents=True, exist_ok=True)
            old_dir.rename(new_dir)
        return new_dir
```

- [ ] **Step 4: Verify the 3 migration tests pass**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest agent.tests.test_cutover9_dir_migration -v 2>&1 | tail -10
```

Expected: 3 tests OK.

- [ ] **Step 5: Run both baselines**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 7 OK / 393 OK (was 390 + 3 new). Same possible exception as Task 7 — if `test_workhub_completeness.py` / `test_codehub_merge.py` fail due to `Timestamp` import, note and continue (Task 9 fixes them).

- [ ] **Step 6: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/runtime/hub_registry.py agent/tests/test_cutover9_dir_migration.py
git commit -m "HubRegistry: rename shared/crdt -> shared/hubs with auto-migration"
```

---

## Task 9: Delete dead CRDT modules + clean up `__init__.py` + fix Timestamp test sites

**Files:**
- Delete: `agent/env_generator/llm_generator/multi_agent/runtime/crdt_store.py`
- Delete: `agent/env_generator/llm_generator/multi_agent/runtime/crdt_types.py`
- Delete: `agent/env_generator/llm_generator/multi_agent/runtime/crdt_validation.py`
- Delete: `agent/env_generator/llm_generator/multi_agent/runtime/crdt_observer_stub.py`
- Modify: `agent/env_generator/llm_generator/multi_agent/runtime/__init__.py`
- Modify: `agent/tests/test_codehub_merge.py`
- Modify: `agent/tests/test_workhub_completeness.py`

- [ ] **Step 1: Confirm there are no remaining CRDT imports outside the to-be-deleted modules and the two test files**

```bash
grep -rnE "crdt_store|crdt_types|crdt_validation|crdt_observer_stub|CRDTStore|LWWMap|GCounter|ORSet|LWWRegister|Timestamp" agent/ --include="*.py" | grep -vE "crdt_store\.py|crdt_types\.py|crdt_validation\.py|crdt_observer_stub\.py|test_codehub_merge\.py|test_workhub_completeness\.py"
```

Expected: empty output. If anything appears, that's a forgotten call site from Tasks 4–7 — fix it before continuing.

(Permitted exception: `__init__.py` will still have the re-exports until Step 5 of this task; if it's the only remaining hit, proceed.)

- [ ] **Step 2: Fix `test_codehub_merge.py`**

In `agent/tests/test_codehub_merge.py`:

- Replace `from multi_agent.runtime.crdt_types import Timestamp` with nothing (remove the import). If `Timestamp` is the only thing on a line like `__import__("multi_agent.runtime.crdt_types", fromlist=["Timestamp"]).Timestamp.now("test")`, replace the whole `Timestamp.now("test")` expression with the string `"test"` (the third arg of `m.set(...)` is just an agent string now).
- The 2 sites the earlier probe found:
  - Line ~117: `__import__("multi_agent.runtime.crdt_types", fromlist=["Timestamp"]).Timestamp.now("test")` → `"test"`
  - Lines ~232, 238: `from multi_agent.runtime.crdt_types import Timestamp` (delete), `Timestamp.now("test")` → `"test"`

- [ ] **Step 3: Fix `test_workhub_completeness.py`**

In `agent/tests/test_workhub_completeness.py`:

- Lines ~206, 278: `from multi_agent.runtime.crdt_types import Timestamp` (delete the line)
- Lines ~207, 279: `ts = Timestamp.now("orch")` → `ts = "orch"` (the variable is still named `ts` for minimal diff; that's fine since the JsonStore call sites no longer interpret it)

- [ ] **Step 4: Run both baselines to confirm tests pass without crdt_types**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 7 OK / 393 OK (unchanged). If anything still imports CRDT, fix before deletion.

- [ ] **Step 5: Clean up `runtime/__init__.py`**

Replace `agent/env_generator/llm_generator/multi_agent/runtime/__init__.py` with:

```python
"""
Runtime Module — post-Cutover 9 (CRDT scaffolding purged).

HubRegistry is the single runtime handle; JsonStore is the persistence primitive.

New code should import from:
  multi_agent.runtime.hub_registry  (HubRegistry)
  multi_agent.runtime.json_store    (JsonStore)
"""

from .hub_registry import HubRegistry  # noqa: F401
from .json_store import JsonStore  # noqa: F401

__all__ = ["HubRegistry", "JsonStore"]
```

- [ ] **Step 6: Delete the four dead modules**

```bash
git rm agent/env_generator/llm_generator/multi_agent/runtime/crdt_store.py
git rm agent/env_generator/llm_generator/multi_agent/runtime/crdt_types.py
git rm agent/env_generator/llm_generator/multi_agent/runtime/crdt_validation.py
git rm agent/env_generator/llm_generator/multi_agent/runtime/crdt_observer_stub.py
```

- [ ] **Step 7: Run both baselines one more time**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 7 OK / 393 OK. If anything fails with `ImportError`, find the leftover importer and fix.

- [ ] **Step 8: Verify the grep returns clean**

```bash
grep -rnE "from .crdt_|from \.\.crdt_|from \.\.\.crdt_|CRDTStore|LWWMap|GCounter|ORSet|LWWRegister" agent/ --include="*.py" | grep -v "json_store"
```

Expected: no matches. (A few comments mentioning "CRDT" in docstrings explaining history are acceptable.)

- [ ] **Step 9: Commit**

```bash
git add agent/env_generator/llm_generator/multi_agent/runtime/__init__.py agent/tests/test_codehub_merge.py agent/tests/test_workhub_completeness.py
git commit -m "Delete crdt_store/crdt_types/crdt_validation/crdt_observer_stub; clean runtime/__init__.py"
```

(Note: the four `git rm` calls from Step 6 are staged together with the `git add` lines from this step — they form one commit covering all the deletions and the consequent cleanups.)

---

## Task 10: Migration log + push

**Files:**
- Create: `docs/superpowers/migration-logs/10-crdt-scaffolding-purge.md`

- [ ] **Step 1: Run final baselines one more time**

```bash
/home/haibotong/miniconda3/envs/dt/bin/python agent/tests/run_regressions.py
/home/haibotong/miniconda3/envs/dt/bin/python -m unittest discover agent/tests -p 'test_*.py' 2>&1 | tail -3
```

Expected: 7 OK / 393 OK. If anything fails, STOP — do not push.

- [ ] **Step 2: Verify zero Claude trailers across the branch's commits**

```bash
git log haibotong-0521-pipeline-web-tools..HEAD --format=%B | grep -c "Co-Authored-By: Claude" || true
```

Expected: `0`. If nonzero, STOP and rewrite history with `git rebase` (interactive isn't allowed — use `git filter-branch --msg-filter "sed '/Co-Authored-By: Claude/d'"`).

- [ ] **Step 3: Write the migration log**

Create `docs/superpowers/migration-logs/10-crdt-scaffolding-purge.md`:

```markdown
# Cutover 9: CRDT Scaffolding Purge

**Branch:** `haibotong-cutover-9-crdt-purge` (off `haibotong-0521-pipeline-web-tools`)
**Date:** 2026-05-24

## What

Finished the CRDT strip Cutover 5 started. Replaced `CRDTStore(LWWMap)` with
`JsonStore` (atomic JSON KV with file lock + monotonic version counter); deleted
`crdt_store.py`, `crdt_types.py`, `crdt_validation.py`, `crdt_observer_stub.py`
(~1137 LoC total). Renamed `crdt_dir` → `hub_dir` everywhere; renamed
`shared/crdt/` → `shared/hubs/` with one-shot auto-migration on `HubRegistry`
init. Existing on-disk LWWMap-format JSONs read transparently via a legacy
unwrap path; the first write persists in the new flat shape.

## Why

Cutover 5 deleted the `CRDTWorkspace` orchestrator but left the hub storage
layer wearing CRDT clothes: every hub still constructed `CRDTStore(crdt_dir /
"foo.json", LWWMap)`, every write stamped a `Timestamp.now(agent)` that nothing
read, and the on-disk directory was still `shared/crdt/`. The CRDT API
exercised at every call site was just `set(k, v, ts=ignored)` / `value()` /
`get(k)` — i.e., a stamped JSON KV. Removing the dead scaffolding makes the
code match what it actually does.

## Commit history

- `<sha>` Cutover 9: record pre-flight baseline (regressions 7 OK, discover 361 OK)
- `<sha>` Add JsonStore: atomic JSON KV with file lock + monotonic version
- `<sha>` JsonStore: add update() compat shim, legacy LWWMap reader, version counter
- `<sha>` APIHub: migrate CRDTStore(LWWMap) -> JsonStore, drop Timestamp.now(), rename crdt_dir -> hub_dir
- `<sha>` EventHub: migrate CRDTStore(LWWMap) -> JsonStore, drop Timestamp.now()
- `<sha>` CodeHub: migrate to JsonStore, drop Timestamp, rename crdt_dir -> hub_dir
- `<sha>` WorkHub: migrate to JsonStore, drop Timestamp, rename crdt_dir -> hub_dir
- `<sha>` HubRegistry: rename shared/crdt -> shared/hubs with auto-migration
- `<sha>` Delete crdt_store/crdt_types/crdt_validation/crdt_observer_stub; clean runtime/__init__.py
- `<sha>` Add Cutover 9 migration log

(Fill in actual SHAs with `git log --oneline haibotong-0521-pipeline-web-tools..HEAD`.)

## Test deltas

- Regressions: 7 OK → 7 OK
- Discover: 361 OK → 393 OK (+32 new tests for JsonStore + migration locators + directory migration)

## Deleted modules (1137 LoC)

- `runtime/crdt_store.py` (163 LoC)
- `runtime/crdt_types.py` (304 LoC)
- `runtime/crdt_validation.py` (603 LoC — was never imported outside its own file)
- `runtime/crdt_observer_stub.py` (67 LoC)

## New module

- `runtime/json_store.py` (~150 LoC) — `JsonStore` + `_MapView` proxy + legacy LWWMap reader

## On-disk migration

`HubRegistry._resolve_hub_dir(base_dir)`:
- If `shared/hubs/` exists → use it
- If only `shared/crdt/` exists → `os.rename` it to `shared/hubs/` (single-process safe)
- Otherwise → create fresh `shared/hubs/`

Existing JSON files are read in their legacy LWWMap shape by `JsonStore._load_raw`,
which detects `{"type": "LWWMap", "entries": {...}}` and unwraps to a flat dict.
The first write persists in the new shape.

## Verification

- `grep -rnE "from .crdt_|CRDTStore|LWWMap" agent/ --include="*.py" | grep -v json_store` → empty
- Zero Claude co-author trailers across the branch
- Both baselines green
```

- [ ] **Step 4: Commit the migration log**

```bash
git add docs/superpowers/migration-logs/10-crdt-scaffolding-purge.md
git commit -m "Add Cutover 9 migration log"
```

- [ ] **Step 5: Push to red-env-gen**

```bash
git push red-env-gen haibotong-cutover-9-crdt-purge 2>&1 | tail -5
```

Expected: a "new branch" message + the PR-compare URL.

- [ ] **Step 6: Report**

Print final report: branch name, commit count, test deltas, push URL. Do NOT merge into parent — that's the parent-session step that happens after this subagent returns.

---

## Self-Review

**1. Spec coverage:**
- Replace CRDT storage with simpler JsonStore — Tasks 2, 3 ✓
- Migrate all 4 hubs (APIHub, EventHub, CodeHub, WorkHub) — Tasks 4, 5, 6, 7 ✓
- Rename `crdt_dir` → `hub_dir` everywhere — Tasks 4, 5, 6, 7, 8 ✓
- Rename `shared/crdt/` → `shared/hubs/` with auto-migration — Task 8 ✓
- Delete dead modules (`crdt_store.py`, `crdt_types.py`, `crdt_validation.py`, `crdt_observer_stub.py`) — Task 9 ✓
- Fix tests that imported Timestamp — Task 9 ✓
- Clean up `runtime/__init__.py` re-exports — Task 9 ✓
- Migration log + push — Task 10 ✓

**2. Placeholder scan:** No "TBD" / "implement later" / unfilled-in code. Every code-changing step has actual code.

**3. Type consistency:**
- `JsonStore` API: `set(key, value, agent="")`, `delete(key, agent="")`, `value() -> dict`, `get(key) -> Optional`, `update(mutator, change_info=None) -> dict`, `get_version() -> int` — same names used in every callsite I describe ✓
- `_MapView` proxy methods: `.set(k, v, _ts=None)`, `.delete(k, _ts=None)`, `.get(k)`, `.value()` — match what call sites do (`m.set(k, v, ts)` works because third arg becomes `_ts`) ✓
- `CodeHubStores.create(cls, hub_dir)`, `WorkHubStores.create(cls, hub_dir)` — same arg name ✓
- `CodeHub.__init__(repo_root, hub_dir, eventhub=...)`, `WorkHub.__init__(hub_dir, eventhub=...)`, `APIHub.__init__(hub_dir, eventhub=..., workhub=...)`, `EventHub.__init__(hub_dir)` — all use `hub_dir` ✓
- `HubRegistry._resolve_hub_dir(base_dir) -> Path` — used once in `__init__` ✓

**4. Cross-cutting concerns:**
- No Claude trailer — checked in Tasks 1, 10 ✓
- Both baselines green at every task boundary — explicit step ✓
- TDD: every code-change task starts with a failing test → confirm fail → impl → confirm pass ✓
- Migration is backward-read-compatible (legacy LWWMap JSON unwrapped on load) — Task 3 ✓
- One-shot dir rename is single-process safe (uses `os.rename`, not copy+delete) — Task 8 ✓
