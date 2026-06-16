# Cutover 22: MCP Integration (APIHub Registration + RunHub Probe)

**Branch:** `haibotong-cutover-22-mcp`
**Date:** 2026-05-25

## What

Treats MCP servers/tools as first-class APIHub resources (mirror endpoint/table
pattern). RunHub probes them post-run (stdio liveness or HTTP reach). Failed
probes route to BugTriageOrchestrator via existing chain. Coverage gate
refuses deliver if any registered MCP tool has zero consumers.

## Why

The "具有 MCP" requirement had zero enforcement. Backend could ship broken
MCP servers; coverage gate only scanned HTTP endpoints + DB tables; RunHub
HTTP probe didn't speak MCP.

## Commits

- `b59ed948` Cutover 22: record pre-flight baseline (regressions 7 OK, discover 829 OK)
- `6df5da51` APIHub: add register_mcp_server / register_mcp_tool / register_mcp_consumer + 3 getters
- `eb483065` RunHub: MCP probe step (stdio liveness + HTTP reach) -> run_failed events on failure
- `6a864438` Add mcp_registry_tools: 5 LLM tools + wire to backend/frontend/orchestrator
- `37c98263` coverage_audit: extend to flag dead MCP tools (registered tool with zero consumers)
- `4905aa20` Backend + frontend prompts: MCP REGISTRATION + CONSUMER discipline
- (this commit) Add Cutover 22 e2e + migration log

## Test deltas
- Regressions: 7 OK -> 7 OK
- Discover: 829 OK -> 862 OK (+33 new)

## New surfaces
- APIHub: register_mcp_server / register_mcp_tool / register_mcp_consumer + 3 getters + _mcp_registry JsonStore
- RunHub.start_run: optional mcp_stdio_probe / mcp_http_probe kwargs; _probe_mcp_servers step; _publish_mcp_failure helper
- runtime/coverage_audit.py: scan_dead_mcp_tools + CoverageReport.dead_mcp_tools field
- tools/mcp_registry_tools.py: 5 LLM tools

## Wiring
- mcp_registry_tools bundle -> backend + frontend + orchestrator profiles
- Backend prompt: MCP REGISTRATION DISCIPLINE
- Frontend prompt: MCP CONSUMER REGISTRATION

## Deviations from plan

- **Tool name prefix renamed `mcp_*` -> `mcp_registry_*`** to avoid collision
  with existing tool namespace. The five LLM tool surfaces are now:
  - `mcp_registry_register_server`
  - `mcp_registry_register_tool`
  - `mcp_registry_register_consumer`
  - `mcp_registry_list_servers`
  - `mcp_registry_list_tools`
  Prompts, tests, and bundle wiring all updated to the renamed prefix; the
  underlying APIHub methods kept their plan-spec names
  (`register_mcp_server` / `register_mcp_tool` / `register_mcp_consumer`).

## Bypass mechanisms (consistent with Cutovers 19-21)
- mark_intentionally_dead("mcp_tool:<server>:<tool>", reason) -> orchestrator allowlist (covered by existing dead-code gate logic)
- force_deliver=True orchestrator-only bypass (existing audit chain)

## Known limits (future cutovers)
- Probe is liveness-only (stdio: 2s; http: HEAD reach). Full JSON-RPC handshake + tools/list verification is a follow-up cutover.
- Websocket transport skipped at probe time (registered, not validated).
- No automatic schema validation against tool responses.
- Backend agent must manually wire the MCP server into the docker compose stack for probe to find it.
