# Cutover 27: Human-Agent Interaction Backend

**Branch:** `haibotong-cutover-27-human-agent-interaction`
**Date:** 2026-05-26

## What

Backend surface for real users to chat with one or many agents. Adds a
top-tier `human_user` priority on EventHub (rank 4, above `critical`),
three EventHub helpers (`publish_human_message`, `publish_agent_reply`,
`list_conversations`), and a `HumanConsole` wrapper on `HubRegistry`
that the new UI (Cutover 28) and CLIs will call.

## Why

Pre-Cutover 27, the only humans interacting with the system were
developers reading logs. The user asked for a system where they can
"select one or multiple agents and interact with them," with messages
classified as "最高等级的信息" (highest-priority information). The new
`human_user` priority guarantees that any subscribed agent receives
the message regardless of their `priority_floor`, and the conversation
persists on EventHub so it survives orchestrator restarts.

## Commits

- de0b37d2 Cutover 27: record pre-flight baseline
- 84808cfa Cutover 27: add human_user priority tier above critical on EventHub
- 82e285e3 Cutover 27: EventHub.publish_human_message/agent_reply/list_conversations
- 646320f1 Cutover 27: HumanConsole on HubRegistry (start/send/list/messages/resolve)
- 9c391036 Cutover 27: EventHub.subscribe_to_human_messages helper for awareness subs
- 5a7bad55 Cutover 27: e2e human-agent conversation + persistence + multi-agent + awareness
- (this commit) Cutover 27: export HumanConsole + migration log

## Test deltas
- Regressions: 7 OK → 7 OK
- Discover: 951 → 979 OK (+28 new)

## New surfaces

- `EventHub._PRIORITY_RANK` — added `"human_user": 4` (above `critical`)
- `EventHub.publish_human_message(text, target_agents, thread_id?, from_user?)`
- `EventHub.publish_agent_reply(thread_id, agent, text)`
- `EventHub.list_conversations(participant?, status?)` — summaries with
  `{thread_id, participants, message_count, last_message_at, last_message_text,
   last_message_source, status}`
- `EventHub.subscribe_to_human_messages(agent)` — convenience for orchestrator/observability
- `HubRegistry.human_console: HumanConsole`
- `HumanConsole.start_conversation(target_agents, text, from_user?)`
- `HumanConsole.send_message(thread_id, text, from_user?)`
- `HumanConsole.list_conversations(participant?, status?)`
- `HumanConsole.list_messages(thread_id)` — chronological transcript
- `HumanConsole.mark_resolved(thread_id)`

## Architecture notes

- Conversations are EventHub threads where the first event has
  `source_hub="human_user"` and `event_type="human_message"`. Reusing
  threads keeps the implementation aligned with the existing
  pub/sub/inbox model rather than introducing a parallel data store.
- Replies are routed back to a synthetic `"human_user"` inbox so the UI
  has a single place to read them (no need to subscribe to every agent).
- Agent reply priority is `high`, not `human_user` — a reply isn't a
  fresh top-tier interrupt; the original message was.

## Known limits (future cutovers)

- No agent auto-routing yet: the user must explicitly target agents.
  Future: a router that picks agents based on message intent.
- No attachments / images in messages — text only for now.
- `mark_resolved` is one-way; no reopen.
- Reply audience inheritance is approximate (uses thread.participants);
  if the human adds a NEW agent mid-conversation via send_message, the
  new agent receives the message but past replies aren't backfilled to
  their inbox.
- No rate limiting or auth — assumed trusted operator at this stage.
- LLM agents need to be wired (Cutover 28+) to actually process and
  reply to human messages; the priority-4 inbox delivery happens, but
  individual agent loops may need to be taught to drain it.
