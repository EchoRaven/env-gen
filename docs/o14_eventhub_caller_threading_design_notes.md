# O14 EventHub caller-threading sweep — Design Notes (workflow `w4wrbq6x5` DEFER)

**Status:** Comprehensive research notes. Workflow `w4wrbq6x5` (17 agents,
544k tokens, 38 min wall-time) produced a detailed plan but deferred
autonomous shipping due to the 10-diff multi-file refactor scope + 2
original BLOCKERS folded into revisions. Phase 4.1 + 4.1b downstream are
blocked on this prep.

The next implementer can apply the workflow's plan directly — every
defect has been mapped to a concrete revision in this doc.

## What O14 is

Thread keyword-only `caller: Optional[str] = None` kwarg through the
EventHub mutation surface so Phase 4.1's subscription identity gate
can compare `caller` (who invoked) vs `agent`/`target` (whose data
got touched) and reject cross-agent mutations.

**Pure prep** — no gate enforcement yet. Phase 4.1 flips the gate
in a separate PR after this lands and bakes for one cycle.

## Why DEFER autonomously

The workflow's initial Candidate A had 2 BLOCKERS:

1. **Closed-by-construction claim broke**: original threading prescription
   used `_request_role(request)` for HTTP shim caller derivation, but
   `_request_role` doesn't exist in the codebase. The plan revised this
   to use the dispatch-site body-injection pattern (mirrors
   `live_monitor_server.py:5432`).

2. **Production-safety defects**: `_request_role()` was claimed to
   return `None` for unauthenticated, but actually returns `"guest"` —
   the proposed `caller=_request_role(request) or agent` fallback was
   broken-by-construction. Plus three "swallow everything except"
   blocks would have hidden PermissionError when Phase 4.1 flips. Plan
   narrowed the except blocks to re-raise PermissionError.

Plus 6 concerns:
- Coverage gap (3 missed callsites: EventHubMarkAllReadTool:1193,
  step_pipeline/helpers.py:170, agent_subscriptions.py:106)
- JsonStore audit metadata gap (caller not actually persisted)
- `change_info` `caller or target` collapse loss
- Family 5 HTTP shim Content-Type assumptions
- Test isolation cross-test state leakage in autouse fixture
- Scope creep on 3 places (`publish_event`, `prune_read_inbox`,
  `subscribe_to_human_messages`)

**Scope**: 10 diffs across 7 callsite families. Autonomous application
risk is non-trivial given:
- JsonStore audit metadata change (could affect downstream readers
  that schema-validate `change_info` dict)
- HTTP shim dispatch pattern change
- 7 callsite families = 7 places to get wrong
- Narrowing existing `except Exception:` blocks is intrusive

The plan is detailed and corrects every defect, but applying 10 diffs
in a single autonomous PR with no operator review is the operative
risk. Phase 4.1 won't ship this session anyway (depends on O14 +
needs adversarial review of the gate semantics).

## Workflow's final plan (concrete, ready to apply)

### Affected files (10 diffs across 7 callsite families)

1. **`runtime/eventhub.py`** — Add `caller: Optional[str] = None` kwarg
   (keyword-only) to: `subscribe`, `unsubscribe`, `unsubscribe_all`,
   `mark_read`, `mark_all_read`, `mark_delivered`. Persist `caller` in
   `change_info` dict passed to `JsonStore.update`. JsonStore positional
   `actor` arg untouched (preserves `_updated_by` semantics for
   downstream readers).

2. **`runtime/json_store.py`** — JsonStore.update internals already
   accept arbitrary `change_info` keys (verified: `json_store.py:161-162`
   only reads `agent`/`system`); add a new optional `last_caller` meta
   field that gets persisted but doesn't change existing reader contracts.

3. **`tools/hub_tools.py:1110-1143`** — Family #1, the 3 EventHub tool
   wrappers (`EventHubSubscribeTool`, `EventHubUnsubscribeTool`,
   `EventHubInboxTool`). Add `caller=self._agent_id` to each
   underlying eventhub call. Also fix `EventHubUnsubscribeTool` (line
   1142) which doesn't currently pass `agent_id` at all.

4. **`tools/communication_tools.py:854`** — Family #2 (the only
   eventhub.mark_read site in this file — bus.subscribe paths are
   separate). Add `caller=self.agent.agent_id`.

5. **`team_runtime/reasoning.py:285`** — Family #3. Add `caller=...`
   based on the local agent identity.

6. **`agent_spawn_service.py:392-393`** — Family #4. Add explicit
   `caller="agent_spawn_service"` sentinel for service-initiated reaping.

7. **`live_monitor_server.py` HTTP shims** — Family #5. Use
   dispatch-site body-injection pattern (mirrors line 5432). Read
   `body.get("caller", "")` and pass through. No `_request_role()`
   function exists; use the body field instead.

8. **`tools/hub_tools.py:1193`** — Coverage gap caught by reviewer:
   `EventHubMarkAllReadTool` missed in initial enumeration.

9. **`step_pipeline/helpers.py:170`** — Coverage gap: hot per-step
   path. High-volume mutation.

10. **`agent_subscriptions.py:106`** — Coverage gap: bootstrap path.

### Test plan

- New `test_o14_caller_threading.py` (~20 tests):
  - For each method (subscribe / unsubscribe / mark_read /
    mark_all_read / mark_delivered): assert (a) `caller=None` (default)
    behaves byte-identically to pre-O14; (b) `caller=<string>` is
    persisted in `change_info`; (c) `caller != target` is permitted
    (no gate enforcement yet — Phase 4.1 adds that).
  - For each callsite family: integration test that exercising the
    tool/HTTP shim/reasoning path now propagates a caller field
    downstream.

### Explicitly deferred (NOT in this PR)

- `publish_event` — actor is structurally `source_hub` (a hub name),
  not a caller. Different semantics; needs Phase 4.1 design clarity.
- `prune_read_inbox` — low-frequency internal call. Add caller threading
  only if Phase 4.1 design requires.
- `subscribe_to_human_messages` convenience wrapper — delegates to
  `subscribe`; once `subscribe` is threaded, this gets the kwarg for
  free at the API level.

## Phase 4.1 dependency (what unblocks after this lands)

Phase 4.1 EventHub subscription identity gate at `phase>=4.1`:

```python
def subscribe(self, agent: str, ..., caller: Optional[str] = None):
    if _phase >= 4.1:
        if caller and caller != agent:
            raise PermissionError(
                f"subscribe: ELABORATION_REFACTOR_PHASE>={_phase:.1f} "
                f"restricts EventHub.subscribe — caller={caller!r} "
                f"cannot subscribe on behalf of agent={agent!r}. "
                "Phase 4.1 identity gate: subscriptions are owner-only."
            )
```

The Phase 4.1 PR is a *one-line flip* once O14 lands — that's the
"closed-by-construction" win the workflow optimized for.

## Why this wasn't shipped autonomously

Three things compound:

1. **10-diff multi-file refactor** — each diff is mechanical but the
   surface is too large for autonomous reliability. Phase 4.0/4.2/4.4/
   4.5/4.6 shipped 1-2 files per gate; O14 touches 7.
2. **JsonStore audit metadata change** — `change_info` dict shape
   widens. Verified no current reader schema-validates this dict, but
   that's an inductive claim; one missed validator breaks production.
3. **Narrowing `except Exception:` blocks** — three sites in the current
   eventhub code swallow everything. Narrowing them is intrusive even
   when the workflow's reasoning is sound.

The plan IS comprehensive and ready to apply. The next operator-side
session should:

1. Re-read this doc + the full workflow output at
   `/tmp/claude-1052/.../tasks/w4wrbq6x5.output`.
2. Apply diffs 1-3 (eventhub + JsonStore + hub_tools) and verify suite.
3. Apply diff 4-6 (communication_tools + team_runtime + agent_spawn)
   and verify suite.
4. Apply diff 7 (live_monitor HTTP shims) and verify suite.
5. Apply diff 8-10 (coverage gaps) and verify suite.
6. Add test_o14_caller_threading.py per plan.
7. Once landed, Phase 4.1 is a one-line flip.

## Out of scope

- `publish_event` caller threading — needs Phase 4.1 design clarity on
  source_hub vs caller semantics.
- MessageBus subscribe/unsubscribe (different from EventHub) —
  separate prep work if Phase 4.1 extends to MessageBus subscriptions.

## Workflow stats

- 17 agents, 544k tokens, 38 min wall-time.
- 6 parallel discovery agents (eventhub + 5 callsite families).
- 3 candidates (kwarg-default / kwarg-required / contextvar).
- Judge picked Candidate A.
- 6-lens adversarial: 2 BLOCKERS + 6 concerns folded into plan.
- Full output: `/tmp/claude-1052/.../tasks/w4wrbq6x5.output`.
