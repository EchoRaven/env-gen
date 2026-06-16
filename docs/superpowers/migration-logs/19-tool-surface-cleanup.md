# Cutover 18: Tool Surface Cleanup & Security Fixes

**Branch:** `haibotong-cutover-18-tool-cleanup`
**Date:** 2026-05-24

## What

Acted on the post-Cutover-17 tool-surface audit. Net effect:
- 2 SSRF security bugs fixed (WebFetchTool, SaveImageTool)
- 2 fully-orphan tool modules deleted (task_tools.py + most of memory_tools.py)
- 3 duplicate tool NAMEs resolved (cleanup_ports, install_dependencies, list_reference_images — the audit only flagged the first two; the dedupe test surfaced the third)
- TOKEN_PRICING table refreshed for Claude 4.x + GPT-5 (was falling through to default; corrected $/1K-token units)
- 4 previously-untested modules gained smoke tests (web_tools, vision_tools, image_search_tools, skill_loader)
- 1 instance-level NAME promoted to class-level + lazy-init bug fixed (vision_tools)
- `_normalize_skill_name` hardened against path traversal

## Why

After 17 cutovers added new gates/hubs/observability, the older tool layer accumulated:
- Dead tool modules (task_tools fully orphan; memory_tools replaced by Cutover 15 structured knowledge)
- Tool NAME collisions across modules (import-resolution roulette decided which class won)
- Stale pricing table producing wrong cost telemetry across every agent run
- 2 SSRF bugs that an LLM prompt-injected via fetched content could exploit (e.g., AWS instance metadata exfiltration)

## Commits

```
56b5a3a9 Cutover 18: record pre-flight baseline (regressions 7 OK, discover 666 OK)
870c1a60 Remove tools/task_tools.py (6 orphan classes; replaced by task_definition + task_suite_executor)
34b7b6dc web_tools: SSRF guard on WebFetchTool (block loopback / RFC1918 / link-local / non-http schemes)
f6fa840d Delete tools/memory_tools.py (6 orphan classes); relocate UpdateMemoryBankTool to agent_interaction_tools
b02a4153 image_search_tools: SSRF guard on SaveImageTool (block loopback / RFC1918 / link-local)
99ff8435 Resolve duplicate tool classes: CleanupPortsTool, InstallDependenciesTool, ListReferenceImagesTool
f2cd4d9c system_tools.TOKEN_PRICING: add Claude 4.x + GPT-5 family (was falling through to default)
d07f7415 vision_tools: promote ExtractComponentsTool.NAME, init _jinja, drop dup attrs + smoke tests
2aebf42f skill_loader: harden _normalize_skill_name against path traversal + add smoke tests
```

## Test deltas
- Regressions: 7 OK -> 7 OK
- Discover: 666 OK -> 698 OK (+32 new)
- Tool NAME uniqueness now enforced via locator test (`test_no_duplicate_tool_names`)

Delta (+32) is higher than the plan estimate (+31) because Task 6's dedupe test
surfaced a third duplicate (`ListReferenceImagesTool`) that the original audit
missed, and Task 4's relocation test set ended at +5 not +4.

## Deleted
- `tools/task_tools.py` (6 orphan tool classes: ExtractActionSpaceTool / GenerateTaskTool / GenerateTrajectoryTool / GenerateJudgeTool / ExportTaskConfigTool / TestActionTool)
- `tools/memory_tools.py` (6 of 7 orphan classes: RememberTool / RecallTool / ShareKnowledgeTool / GetOperationHistoryTool / GetMemoryContextTool / MemoryHealthSummaryTool; UpdateMemoryBankTool relocated to `agent_interaction_tools.py`)
- 12 `memory_tools` references in `agents_config.yaml` profile bundles
- Duplicate definitions of CleanupPortsTool, InstallDependenciesTool, ListReferenceImagesTool (kept one canonical each)

## Security fixes (P0)
Both `WebFetchTool` and `SaveImageTool` now refuse:
- Non-http(s) schemes (file://, ftp://, gopher://, ...)
- Loopback (127.0.0.0/8, ::1)
- RFC1918 private (10/8, 172.16/12, 192.168/16)
- Link-local (169.254/16 — AWS instance metadata)
- IPv6 ULA (fc00::/7) + multicast + reserved

Implementation: `_ssrf_check(url)` helper using stdlib `ipaddress` + `socket.getaddrinfo`. `SaveImageTool` reuses the canonical implementation from `web_tools.py`.

## Known gaps (future cutovers)
- `communication_tools.py` at 1914 LoC / 14 tools still needs a slim-down pass
- Clearbit dependency in LogoSearchTool is dead but not removed (kept the fallback waterfall intact)
- TOKEN_PRICING is hardcoded; a config-file source would be more maintainable
- vision_tools constructors still fall back to Workspace(cwd) on `workspace=None` — flagged in audit but deferred since changing the contract risks parallel-agent runs
- `_ssrf_check` is duplicated logic (import in image_search vs definition in web_tools); a shared `tools/_safety.py` utility would be cleaner if a third caller appears
