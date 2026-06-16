# Cutover 9: CRDT Scaffolding Purge

**Branch:** `haibotong-cutover-9-crdt-purge` (off `haibotong-0521-pipeline-web-tools`)
**Date:** 2026-05-24

## What

Finished the CRDT strip Cutover 5 started. Replaced `CRDTStore(LWWMap)` with
`JsonStore` (atomic JSON KV with file lock + monotonic version counter); deleted
`crdt_store.py`, `crdt_types.py`, `crdt_validation.py`, `crdt_observer_stub.py`
(~1137 LoC total). Renamed `crdt_dir` -> `hub_dir` everywhere; renamed
`shared/crdt/` -> `shared/hubs/` with one-shot auto-migration on `HubRegistry`
init. Existing on-disk LWWMap-format JSONs read transparently via a legacy
unwrap path; the first write persists in the new flat shape.

## Why

Cutover 5 deleted the `CRDTWorkspace` orchestrator but left the hub storage
layer wearing CRDT clothes: every hub still constructed `CRDTStore(crdt_dir /
"foo.json", LWWMap)`, every write stamped a `Timestamp.now(agent)` that nothing
read, and the on-disk directory was still `shared/crdt/`. The CRDT API
exercised at every call site was just `set(k, v, ts=ignored)` / `value()` /
`get(k)` -- i.e., a stamped JSON KV. Removing the dead scaffolding makes the
code match what it actually does.

## Commit history

- `6335d0f4` Cutover 9: record pre-flight baseline (regressions 7 OK, discover 361 OK)
- `4cb4ed90` Add JsonStore: atomic JSON KV with file lock + monotonic version
- `bc7f38f9` JsonStore: add update() compat shim, legacy LWWMap reader, version counter
- `2670483c` APIHub: migrate CRDTStore(LWWMap) -> JsonStore, drop Timestamp.now(), rename crdt_dir -> hub_dir
- `99f3a48f` EventHub: migrate CRDTStore(LWWMap) -> JsonStore, drop Timestamp.now()
- `9d15c0b8` CodeHub: migrate to JsonStore, drop Timestamp, rename crdt_dir -> hub_dir
- `d6ca3225` WorkHub: migrate to JsonStore, drop Timestamp, rename crdt_dir -> hub_dir
- `aa963447` HubRegistry: rename shared/crdt -> shared/hubs with auto-migration
- `f168cf40` test: use JsonStore single-key get() in codehub tests
- `ed5581cb` Delete crdt_store/crdt_types/crdt_validation/crdt_observer_stub; clean runtime/__init__.py
- `<this commit>` Add Cutover 9 migration log

## Test deltas

- Regressions: 7 OK -> 7 OK
- Discover: 361 OK -> 393 OK (+32 new tests for JsonStore + migration locators + directory migration)

## Deleted modules (1137 LoC)

- `runtime/crdt_store.py` (163 LoC)
- `runtime/crdt_types.py` (304 LoC)
- `runtime/crdt_validation.py` (603 LoC -- was never imported outside its own file)
- `runtime/crdt_observer_stub.py` (67 LoC)

## New module

- `runtime/json_store.py` (~150 LoC) -- `JsonStore` + `_MapView` proxy + legacy LWWMap reader

## On-disk migration

`HubRegistry._resolve_hub_dir(base_dir)`:
- If `shared/hubs/` exists -> use it
- If only `shared/crdt/` exists -> `os.rename` it to `shared/hubs/` (single-process safe)
- Otherwise -> create fresh `shared/hubs/`

Existing JSON files are read in their legacy LWWMap shape by `JsonStore._load_raw`,
which detects `{"type": "LWWMap", "entries": {...}}` and unwraps to a flat dict.
The first write persists in the new shape.

## Verification

- `grep -rnE "from .crdt_|CRDTStore|LWWMap" agent/ --include="*.py" | grep -v json_store` -> empty
- Zero Claude co-author trailers across the branch
- Both baselines green
