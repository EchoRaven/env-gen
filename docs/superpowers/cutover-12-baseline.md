# Cutover 12 Baseline (Runtime Feedback Loop)

## Test counts
- regressions: 7 OK
- discover: 491 OK

## Gap this cutover closes
At a fresh HubRegistry, `eventhub.get_subscriptions()` returns []. Verifier and RunHub
publish bug events into the events store, but with no subscriber the events never
reach the BugTriageOrchestrator's inbox. This cutover registers default subscriptions
per agent profile and proves end-to-end with an integration test.

## Approach
- new module runtime/agent_subscriptions.py with DEFAULT_SUBSCRIPTIONS table
- hub_pulse calls ensure_default_subscriptions(hubs, agent_id) at top — idempotent
- end-to-end integration test exercises full chain without LLM
