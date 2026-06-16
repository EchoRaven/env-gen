# Cutover 18 Baseline (Tool Surface Cleanup)

## Test counts
- regressions: 7 OK
- discover: 666 OK

## Scope
- DELETE: tools/task_tools.py (fully orphan)
- DELETE: tools/memory_tools.py (relocate UpdateMemoryBankTool, drop 6 orphan classes)
- SECURITY: SSRF guards on WebFetchTool + SaveImageTool
- DUPE: resolve CleanupPortsTool + InstallDependenciesTool dupes
- STALE: refresh system_tools.TOKEN_PRICING for Claude 4 family
- TESTS: add smoke tests for web/vision/image_search/skill_loader

## Orphan grep (must be empty)
task_tools imports outside tools/__init__.py:
(empty — no matches)

## memory_tools yaml block lines (must be removed by Task 4)
85:      - memory_tools
141:      - memory_tools
178:      - memory_tools
220:      - memory_tools
269:      - memory_tools
321:      - memory_tools
354:      - memory_tools
417:      - memory_tools
455:      - memory_tools
491:      - memory_tools
529:      - memory_tools
569:      - memory_tools

Count: 12 lines (matches expected).
