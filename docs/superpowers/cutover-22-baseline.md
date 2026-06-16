# Cutover 22 Baseline (MCP Integration)

## Test counts
- regressions: 7 OK
- discover: 829 OK

## Gap this cutover closes
No mechanical enforcement of "具有 MCP". Backend can ship a broken MCP
server; RunHub HTTP probe doesn't speak MCP; coverage gate doesn't catch
unused MCP tools.

## Approach
- Backend owns MCP. APIHub registers MCP server/tool/consumer (mirror endpoint).
- RunHub probes each declared MCP server (stdio liveness or HTTP reach) post-run.
- Failed probe -> runhub/run_failed -> BugTriageOrch -> backend (existing chain).
- Coverage gate (Cutover 19) extended: registered MCP tool without consumer = dead.
- Force-deliver bypass reuses Cutover 19/20/21 pattern (mcp_audit_bypass event).

## Out of scope
- Full MCP protocol handshake (just liveness)
- WebSocket transport probe (skipped)
- Schema validation against tool responses
