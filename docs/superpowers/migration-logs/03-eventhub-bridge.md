# 03 — EventHub MessageBus Bridge (Cutover 2)

**Branch:** haibotong-cutover-2-eventhub-bridge
**Predecessor:** Cutover 1.5 (APIHub Completeness, tip 2abbdf61)
**Baseline:** 53bfa316

## Summary

Wires EventHub to the live MessageBus so agents receive push-delivered events instead of only inbox-polled ones. Adds EventHub subscription model (subscribe/unsubscribe/get_subscriptions), durable inbox methods (mark_delivered/mark_all_read/get_event/get_thread), subscription-driven fan-out in publish_event, MessageBusBridge package with deliver() and inbox_only opt-out, and first-step catch-up delivery. Also fixes a Python 3.11 regression: asyncio.coroutine was removed in 3.11 and silently suppressed bridge dispatch; replaced with an async def wrapper.

## Methods added to EventHub

- `subscribe(agent, source_hub, event_type, filter, priority_floor, delivery)` — spec-model subscription
- `unsubscribe(subscription_id)` — soft-delete via CRDT _removed marker
- `get_subscriptions(agent=None)` — return active subscriptions
- `mark_delivered(agent, event_id)` — flip delivered flag after bridge push
- `mark_all_read(agent, before_ts=None)` — bulk mark-read
- `get_event(event_id)` — retrieve single event by id
- `get_thread(thread_id)` — retrieve all events in a thread
- `attach_bridge(bridge)` — attach live delivery bridge

## New packages / modules

- `agent/env_generator/llm_generator/multi_agent/runtime/hubs/eventhub/bridge.py` — MessageBusBridge
- `agent/env_generator/llm_generator/multi_agent/runtime/hubs/eventhub/__init__.py` — package scaffold

## Integration wiring

- HubWorkspace accepts `message_bus` and calls `eventhub.attach_bridge(MessageBusBridge(bus, eventhub))`
- CRDTWorkspace accepts `message_bus` and forwards to HubWorkspace
- Orchestrator passes `message_bus` from its MessageBus instance into CRDTWorkspace
- Agent first-step catch-up: on agent start, EventHub delivers any undelivered inbox items via bridge

## Tests

- New: `agent/tests/test_eventhub_completeness.py`
- New: `agent/tests/test_eventhub_subscription_fanout.py`
- New: `agent/tests/test_eventhub_spawn_catchup.py`
- New: `agent/tests/test_messagebus_bridge.py`
- Combined hub suite: 59 tests (was 29 post-Cutover 1.5; up by 30)

## Commits

c11f6db9 Fix bridge dispatch: replace removed asyncio.coroutine with async wrapper
87df341a Add EventHub catch-up on agent first step
9863a178 Orchestrator passes MessageBus into CRDTWorkspace for EventHub bridge wiring
e0ecef23 CRDTWorkspace accepts optional message_bus and forwards to HubWorkspace
12bc091e HubWorkspace accepts message_bus and attaches MessageBusBridge to EventHub
26ee6f3d Implement MessageBusBridge.deliver with inbox_only opt-out and priority floor
a66e69e1 Scaffold MessageBusBridge stub package
dc47e133 Add EventHub.attach_bridge + subscription-driven fan-out in publish_event
52394ea1 Add EventHub.mark_delivered / mark_all_read / get_event / get_thread
180ba4e9 Add EventHub.unsubscribe and get_subscriptions
a554d0df Reshape EventHub.subscribe to spec model (source_hub/event_type/filter/priority_floor/delivery)

## Regression evidence

----------------------------------------------------------------------
Ran 7 tests in 0.708s

OK

Combined hub suite: 59 tests, all passing.

## Smoke test (real MessageBus + bridge delivery)

backend received 2 live event(s) via bridge

Schema change from `{'posts': []}` to `{'items': []}` (breaking — removes `posts`) triggers:
1. `breaking_change_detected` event → delivered to `backend` (registered consumer)
2. `task_created` event → delivered to `backend` (fix task auto-created by WorkHub integration)

## Code quality verification

- `git log --pretty=%B 53bfa316..HEAD | grep -c "Co-Authored-By:"` returns 0.
- `asyncio.coroutine` usage removed; Python 3.11 compatible.

## Next

Cutover 3 — WorkHub or CodeHub additions can now rely on push-based event delivery via the wired bridge.
