# O14 Chunk-1 eventhub caller-threading — Design Notes (workflow `wj7nevajo` REJECT)

**Status:** REJECT (0 blockers + 2 refutes, strict 2-refute threshold).
Plan author returned `ship_decision: DEFER` honoring REJECT. Winner
candidate (B) was **STRUCTURALLY SOUND** — JSONSTORE_READER_BACKWARD_COMPAT
review verified the 30+ change_info sites in tree and confirmed pure-
additive widening breaks nothing. The blockers are quality concerns,
not correctness defects.

DEFER counter consecutive: 2 (Phase 3 mechanism + this O14 chunk1).
One more triggers /loop stop condition.

## Winner B (verified structurally sound)

**Scope**: Bottom-of-stack landing for o14 caller-identity thread:
- `runtime/eventhub.py` — add `caller: Optional[str] = None` keyword-only
  kwarg to 6 mutation methods at confirmed line numbers:
  - `subscribe@217`
  - `unsubscribe@260`
  - `unsubscribe_all@282`
  - `mark_read@445`
  - `mark_delivered@461`
  - `mark_all_read@485`
- Thread caller through into each existing `change_info` dict as
  `last_caller` key (non-overwriting; preserves `'agent'` + `'system'`
  keys).
- `runtime/json_store.py` — widen `update()` / `_bump_meta()` to
  optionally persist `meta['last_caller']` when `change_info`
  contains it. Default behavior unchanged (when no caller threaded,
  on-disk shape is byte-identical to today).

**All 7 callsite families + Phase 4.1 gate deferred to follow-up PRs.**

## Refutes (both fixable in a re-attempt)

### Refute 1 — TEST_COUNT_DELTA (concern severity)

Winner spec drafted 3 tests covering 6 mutation methods. The other 5
methods (unsubscribe / unsubscribe_all / mark_read / mark_delivered /
mark_all_read) have ZERO direct test coverage of the caller kwarg.

**Fix in next attempt** — ship ~10 tests:

| # | Test | Asserts |
|---|---|---|
| 1 | `test_caller_default_is_byte_identical_subscribe` | `subscribe(...)` without caller produces same `_meta` as today |
| 2 | `test_caller_default_is_byte_identical_unsubscribe` | same for `unsubscribe` |
| 3 | `test_caller_default_is_byte_identical_unsubscribe_all` | same for `unsubscribe_all` |
| 4 | `test_caller_default_is_byte_identical_mark_read` | same for `mark_read` |
| 5 | `test_caller_default_is_byte_identical_mark_delivered` | same for `mark_delivered` |
| 6 | `test_caller_default_is_byte_identical_mark_all_read` | same for `mark_all_read` |
| 7 | `test_caller_persists_in_change_info_each_method` | passing `caller='orchestrator'` yields `meta['last_caller'] == 'orchestrator'` on each method |
| 8 | `test_last_modified_by_preserved_each_method` | the do-not-overwrite contract — `meta['last_modified_by']` stays = agent arg even when caller is threaded |
| 9 | `test_jsonstore_roundtrip_preserves_last_caller` | write via `JsonStore.update` with `change_info={'agent':'a','last_caller':'c'}`, reopen file, assert `_meta['last_caller'] == 'c'` |
| 10 | `test_keyword_only_marker_rejects_positional` | `subscribe('agent', '*', '*', None, 'low', 'live', 'caller-as-positional')` raises `TypeError` (defense against positional-arg collision) |
| 11 | `test_caller_none_is_empty_actor_fallthrough` | the Phase 4.1 convention: caller=None is treated as "no identity claimed", future gate must fall through |

### Refute 2 — GATE_FALLTHROUGH_SAFETY (convention-only)

The `caller=None` fallthrough convention currently lives only in the
new kwarg's docstring. A future Phase 4.1 author who writes
`if caller != agent: raise PermissionError` WITHOUT a leading
`if caller is None: return` guard would break all 14 already-shipped
gate sites.

**Fix in next attempt** — codify the convention in code, not docstring:

Option A (lightest) — add a one-liner explicit empty-actor coerce at
each entry:
```python
def subscribe(self, agent, ..., *, caller: Optional[str] = None):
    # caller=None is the empty-actor convention: no identity claimed,
    # fall through to the existing actor-derived path. Phase 4.1+ gates
    # MUST treat None as fall-through, matching the empty-actor idiom
    # used by all 14 shipped gates (cf. _role_gate.require_allowed_actor).
    caller = (caller or "").strip().lower()  # "" sentinel; aligned w/ schema_hub
```

Option B — a `_normalize_caller(caller)` helper in `_role_gate.py` that
every new kwarg uses + tests assert it.

Either lands the convention enforceably.

## What was already verified safe by the workflow

- **BACKWARD_COMPAT** (refuted=true but with no defect — review
  explicitly confirms the change is byte-identical for every existing
  caller).
- **JSONSTORE_READER_BACKWARD_COMPAT** (refuted=true but verified safe
  — only consumer is `update()` itself at `json_store.py:161-162`
  which uses `.get('agent') or .get('system')` and discards everything
  else; the 30+ other sites all pass `change_info=` but no reader
  schema-validates it).
- **NO_PROD_BEHAVIOR_CHANGE** (refuted=true with confirmation — no
  control flow changes; pure signature widening + optional persistence).
- **GATE_FALLTHROUGH_SAFETY** (nit severity, addressed by Option A/B
  above).

## Per-line implementation pin (ready to apply once test coverage is filled in)

```python
# eventhub.py
def subscribe(self, agent, source_hub='*', event_type='*', filter=None,
              priority_floor='low', delivery='live', *,
              caller: Optional[str] = None) -> dict:
    # ... existing body unchanged ...
    self._subscriptions.update(
        lambda m: m.set(sub_id, sub, agent),
        change_info={
            'agent': agent,
            **({'last_caller': caller} if caller else {}),  # additive, omit when None
        },
    )

# json_store.py update()
def update(self, fn, *, change_info: Optional[dict] = None):
    agent = str(change_info.get('agent') or change_info.get('system') or '') if change_info else ''
    last_caller = str(change_info.get('last_caller') or '') if change_info else ''
    # ... existing m mutation ...
    self._bump_meta(raw, agent, last_caller=last_caller)

def _bump_meta(self, raw, agent, *, last_caller: str = ''):
    raw.setdefault('_meta', {})
    raw['_meta']['version'] = raw['_meta'].get('version', 0) + 1
    raw['_meta']['last_modified_by'] = agent or raw['_meta'].get('last_modified_by', 'unknown')
    raw['_meta']['last_modified_at'] = time.time()
    if last_caller:  # only write when non-empty — preserves byte-identical on-disk when no caller threaded
        raw['_meta']['last_caller'] = last_caller
```

## What this unblocks once landed

- **Phase 4.1 EventHub identity gate** can ship as a separate one-line
  flip per method at phase>=4.1: `caller = (caller or '').strip().lower(); if caller and caller != agent: raise PermissionError(...)`.
- 6 callsite-family follow-up PRs (one per family, each reversible)
  thread agent identity through the production callers
  (hub_tools / communication_tools / reasoning / agent_spawn_service /
  live_monitor_server HTTP shims / step_pipeline helpers).

## Workflow stats

- 14 agents, 366k tokens, ~8 min wall-time.
- 3 parallel discovery agents (prior-defer-plan / eventhub-state /
  phase-4-1-need).
- 4 candidates (A full / B chunk1 / C chunk1+2 / D DEFER).
- Judge picked Candidate B (smallest reasonable SHIP).
- 5-lens adversarial: 0 blockers + 2 refutes (both fixable concerns).
- Full output: `/tmp/claude-1052/.../tasks/wj7nevajo.output`.

## DEFER context

This is consecutive DEFER #2 (Phase 3 mechanism + O14 chunk1). One
more triggers /loop's "stop after 3 consecutive REJECT" rule. The
next iteration should either re-attempt one of these with the fixes
baked in (high SHIP confidence) OR pause autonomous loop for user
direction.
