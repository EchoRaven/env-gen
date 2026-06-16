# Cutover 29: Agent Chat Consumer

**Branch:** `haibotong-cutover-29-agent-chat-consumer`
**Date:** 2026-05-26

## What

Cutover 27 built the human -> EventHub -> inbox half. This cutover closes
the loop: agents now actually receive, process, and reply to human_user
messages. Two changes:
1. `MessageBusBridge.priority_map` adds `"human_user" -> MessagePriority.URGENT`
   so the bridge no longer silently downgrades human messages to NORMAL.
2. EnvGenAgent gains `_handle_human_message` (LLM call + publish reply),
   dispatched from `_check_and_handle_urgent` when `metadata.event_type == "human_message"`.

## Why

Before this cutover, sending a chat message via the UI was a black hole:
the message reached EventHub and the inbox, but the bridge mapped its
`human_user` priority to NORMAL, so the agent's urgent-handler loop never
fired and nobody ever replied. The user explicitly identified this as
"the missing half - chat works in UI, agent never responds."

## Commits

- `e7d424d8` Cutover 29: record pre-flight baseline
- `58edc056` Cutover 29: bridge maps human_user EventHub priority to URGENT MessagePriority
- `9df28413` Cutover 29: agent _handle_human_message + urgent-loop dispatch
- `8dd2d01f` Cutover 29: e2e smoke for human -> bridge -> agent URGENT routing
- (this commit) Cutover 29: migration log

## Test deltas
- Regressions: 7 OK -> 7 OK
- Targeted Cutover 29 sweep: 7 new tests pass (3 bridge + 3 handler + 1 e2e)
- Cutover 27 sweep: 28 pre-existing tests still pass

## New surfaces

- `MessageBusBridge.priority_map["human_user"] = MessagePriority.URGENT`
- `EnvGenAgent._handle_human_message(message)` - LLM call + publish_agent_reply
- `EnvGenAgent._generate_text(system, user)` - minimal single-turn text gen helper
  (uses `chat_messages` via `call_with_retry`; tests override this method)
- `_check_and_handle_urgent` new branch: `event_type == "human_message"` -> `_handle_human_message`

## Architecture notes

- The dispatcher checks `event_type` BEFORE `msg_type` so human messages
  take precedence over standard agent comms (question/answer/issue/task_ready).
- Reply uses `publish_agent_reply` (Cutover 27) which routes back to the
  full thread participant set, so the human (via `list_messages`) and any
  other agents on the thread all see the reply.
- LLM failures don't crash the loop - they publish an apology reply so
  the human gets feedback that something went wrong. The apology text
  includes the words "unavailable" and "failed with error" so the user
  has clear language about what happened.
- `_generate_text` calls the agent's existing LLM client via
  `chat_messages(messages)` routed through `call_with_retry` (matching the
  codebase's `_generate_answer` pattern), rather than introspecting the
  client across many method names. This is the Task 3 deviation from the
  plan's introspection sketch - it matches the established convention
  already in `base.py`.

## Known limits (future cutovers)

- Auto-routing: target agents must still be picked explicitly by the human.
- Reply prompt is generic (one paragraph, no tools); future cutovers may
  let agents call tools while replying (e.g. "add the requested feature
  AND tell the user it's done in one turn").
- Multiple human messages in rapid succession may interleave with agent
  work - there's no per-thread mutex yet.
- The orchestrator-as-aware-listener pattern (Cutover 27's
  `subscribe_to_human_messages`) is not auto-installed in this cutover;
  it remains opt-in.
- The e2e smoke test ensures it has a current event loop before publishing
  (some prior tests in the session leave the thread loop-less via
  `asyncio.run`, which would cause `eventhub.publish_event`'s best-effort
  bridge call to be silently swallowed). A unified async lifecycle for
  EventHub delivery would remove that footgun.
