# 07 — Hub Tool Surface Fill Cutover

**Branch:** haibotong-cutover-6-tool-surface-fill
**Predecessor:** haibotong-0521-pipeline-web-tools tip (post-CRDT strip merge)
**Spec:** docs/superpowers/specs/2026-05-22-hub-bound-step-pipeline-design.md §9.1-9.3

## Summary

Adds 16 LLM tools wrapping previously-unexposed hub methods, plus 3 new APIHub
methods backing the table-consumer / table-breaking-change tools. No
enforcement / step-pipeline changes yet — those come in Cutovers 7 and 8.

## Tools added (16)

EventHub (7):
- eventhub_subscribe, eventhub_unsubscribe, eventhub_list_subscriptions
- eventhub_get_thread, eventhub_reply_in_thread
- eventhub_mark_all_read, eventhub_get_agent_status

WorkHub (5):
- workhub_invite_attendee, workhub_remove_attendee
- workhub_comment, workhub_reply, workhub_share_implementation

APIHub (4):
- apihub_register_table, apihub_list_tables
- apihub_register_table_consumer, apihub_get_table_breaking_changes

## Hub methods added (APIHub)

- register_table_consumer(table_name, file_path, agent, metadata)
- detect_table_breaking_change(old_schema, new_schema)
- get_table_breaking_changes(since_ts=None)
- update_table_schema now fires breaking-change recording + event when columns removed/typed-changed

## Test additions (4 new files)

- test_apihub_tables_breaking_change.py (7 tests)
- test_eventhub_new_tools.py (8 tests)
- test_workhub_collab_tools.py (6 tests)
- test_apihub_table_tools.py (5 tests)

Also fixed: asyncio.get_event_loop() → asyncio.run() in test_workhub_tools.py and
test_workhub_collab_tools.py for Python 3.11 compatibility (pre-existing pattern,
surfaced by discover run ordering).

## Commits

```
b5ee05c8 Fix asyncio.get_event_loop() in workhub tests for Python 3.11 compatibility
6db07e44 Add APIHub table tools to REQUIRED_TOOLS set in test_apihub_tools
ea4be35a Widen eventhub/workhub/apihub tool bundles to include 16 new tools
d45302de Add APIHub register_table_consumer + get_table_breaking_changes LLM tools
d041ced6 Add APIHub register_table + list_tables LLM tools
d6976a69 Add WorkHub comment / reply / share_implementation LLM tools
51a1d5f9 Add WorkHub invite_attendee + remove_attendee LLM tools
a017f609 Add EventHub mark_all_read + get_agent_status LLM tools
917a3b92 Add EventHub get_thread + reply_in_thread LLM tools
13489012 Add EventHub subscribe/unsubscribe/list_subscriptions LLM tools
fa6e2ec0 Add APIHub.register_table_consumer + table breaking-change detection
```

## Regression evidence

```
----------------------------------------------------------------------
Ran 7 tests in 0.454s

OK
```

Total hub tools after this cutover: 59 (was 43).

## Full test suite

```
----------------------------------------------------------------------
Ran 274 tests in 34.834s

OK
```

## Next

Cutover 7 — schema 3-layer + reviewer gate (codehub_suggest_reviewers,
codehub_force_merge, apihub.register_consumer write-time gate,
codehub.merge_pull_request premerge gate, open_pr 2-reviewer enforcement).
